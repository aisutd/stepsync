"""Local YouTube intake API with synchronous pose extraction."""

import logging
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import Settings
from .handoff import ProcessingState
from .pose_processing import PoseArtifacts, run_pose_extraction
from .video import VideoError, validate_video
from .youtube import download_video, validate_url
from .storage import save_video
from .segmentation import segment_steps
from .supabase_store import SupabaseError, SupabaseStore, add_motion_features, load_pose_frames

logger = logging.getLogger(__name__)

# Videos uploaded from the phone app by POST /analyze.
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024  # 300 MB per video


class MetadataResponse(BaseModel):
    duration_seconds: float
    width: int
    height: int
    fps: float
    frame_count: int
    rotation_degrees: float
    timestamp_source: str


class YouTubeRequest(BaseModel):
    url: str


class StepResponse(BaseModel):
    step_index: int
    label: str
    start_ms: int
    end_ms: int
    intensity: str
    focus: list[str]


class UploadResponse(BaseModel):
    status: ProcessingState
    source_url: str
    filename: str
    size_bytes: int
    metadata: MetadataResponse
    pose_processing: str
    persisted: bool
    saved_path: str
    pose_preview_path: str | None = None
    pose_data_path: str | None = None
    pose_error_code: str | None = None
    pose_error: str | None = None
    # Supabase: "saved", "not_configured", "skipped" (no keypoints) or "failed".
    supabase_status: str = "not_configured"
    supabase_dance_id: str | None = None
    supabase_error: str | None = None
    frames_saved: int | None = None
    # Learnable steps found in the dance (empty when no dancer was detected).
    steps: list[StepResponse] = []


_FROM_ENV = object()


def create_app(
    settings: Settings | None = None,
    pose_runner: Callable[[Path, Path, Path, float], PoseArtifacts] | None = None,
    supabase_store: "SupabaseStore | None | object" = _FROM_ENV,
) -> FastAPI:
    settings = settings or Settings.from_env()
    pose_runner = pose_runner or run_pose_extraction
    store = SupabaseStore.from_env() if supabase_store is _FROM_ENV else supabase_store
    app = FastAPI(title="StepSync local video backend", description=(
        "Validated videos are saved locally and processed by the pose extractor. "
        "No authentication or database is connected."
    ))

    # Lets the Expo web build (a different origin) call the API during development.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.exception_handler(VideoError)
    async def video_error_handler(request, error):
        return JSONResponse(status_code=error.status_code,
                            content={"error": {"code": error.code, "message": error.message}})

    @app.exception_handler(RequestValidationError)
    async def request_error_handler(request, error):
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request", "message": "Send a JSON object with a nonempty string in the 'url' field."
        }})

    @app.post("/reference-videos", response_model=UploadResponse, status_code=200)
    def upload_video(request: YouTubeRequest, authorization: str | None = Header(default=None)):
        try:
            url = validate_url(request.url)
            with TemporaryDirectory(prefix="stepsync-youtube-") as directory:
                downloaded = download_video(url, Path(directory), settings)
                path = downloaded.path
                if path.suffix.lower() not in settings.allowed_extensions:
                    raise VideoError("unsupported_format", "MP4 is not enabled in the configured extension allowlist.", 415)
                size = path.stat().st_size
                if size > settings.max_upload_bytes:
                    raise VideoError("upload_too_large", f"File exceeds the {settings.max_upload_bytes}-byte limit.", 413)
                if size == 0:
                    raise VideoError("empty_file", "The downloaded video is empty.")
                metadata = validate_video(path, settings)
                saved = save_video(path, downloaded.title, settings.video_directory)
            try:
                artifacts = pose_runner(
                    saved, settings.pose_results_directory / saved.stem,
                    settings.pose_model_path, settings.pose_processing_timeout_seconds,
                )
            except Exception as error:
                logger.exception("Pose processing failed for saved video %s", saved)
                return UploadResponse(
                    status=ProcessingState.failed, source_url=url, filename=saved.name,
                    size_bytes=size, metadata=MetadataResponse(**asdict(metadata)),
                    pose_processing="failed", persisted=True, saved_path=str(saved),
                    pose_error_code=error.code if isinstance(error, VideoError) else "pose_processing_failed",
                    pose_error=error.message if isinstance(error, VideoError) else "Pose extraction failed. Check the backend logs.",
                    supabase_status="skipped",
                    supabase_error="Nothing was saved to Supabase because pose extraction failed.",
                )
            supabase_result = save_to_supabase(
                store, artifacts.data_path, url, downloaded.title, saved, metadata, authorization,
            )
            return UploadResponse(
                status=ProcessingState.completed, source_url=url, filename=saved.name,
                size_bytes=size, metadata=MetadataResponse(**asdict(metadata)),
                pose_processing="completed", persisted=True, saved_path=str(saved),
                pose_preview_path=str(artifacts.preview_path), pose_data_path=str(artifacts.data_path),
                **supabase_result,
            )
        except VideoError:
            raise
        except Exception:
            logger.exception("Local video validation failed")
            raise VideoError("processing_failed", "Video inspection failed unexpectedly. Check the backend logs.", 500)

    @app.get("/videos/{filename}")
    def video_file(filename: str):
        """Stream a video saved by /reference-videos, so the app can preview it.

        Supports HTTP range requests, which iOS needs to play video.
        Only bare filenames from the saved-videos folder are served (see find_saved_video).
        """
        path = find_saved_video(filename, settings.video_directory)
        return FileResponse(path, media_type="video/mp4")

    @app.post("/analyze")
    def analyze(
        practice: UploadFile = File(...),
        reference: UploadFile | None = File(None),
        reference_video: str | None = Form(None),
    ) -> dict:
        """Receives the practice video from the phone app plus the reference, sent either
        as a video file or as the `filename` POST /reference-videos returned for a YouTube link."""
        if (reference is None) == (reference_video is None):
            raise HTTPException(
                422, "Send exactly one of 'reference' (a video file) or 'reference_video' "
                "(a filename from /reference-videos).",
            )
        saved_reference = (
            find_saved_video(reference_video, settings.video_directory)
            if reference_video is not None else None
        )
        session_id = uuid.uuid4().hex
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(parents=True)
        try:
            reference_path = saved_reference or save_upload(reference, session_dir, "reference")
            practice_path = save_upload(practice, session_dir, "practice")
        except HTTPException:
            shutil.rmtree(session_dir, ignore_errors=True)
            raise
        # TODO: replace with the real pipeline (pose estimation, DTW, scoring).
        # The response shape must match AnalysisResult in frontend/src/api/types.ts.
        return placeholder_result(session_id, reference_path, practice_path)

    return app


def save_to_supabase(store, data_path: Path, url: str, title: str, saved: Path, metadata, authorization) -> dict:
    """Split the dance into steps and store keypoints, features and steps.

    Never fails the import: Supabase problems are reported in the response instead.
    """
    try:
        frames = load_pose_frames(data_path)
        add_motion_features(frames)
        steps = segment_steps(frames)
    except Exception:
        logger.exception("Could not read pose data from %s", data_path)
        return {"supabase_status": "failed", "supabase_error": "Couldn't read the pose data. Check the backend logs."}

    step_info = [{k: step[k] for k in StepResponse.model_fields} for step in steps]
    if store is None:
        return {"steps": step_info, "supabase_status": "not_configured", "supabase_error": (
            "The backend isn't connected to Supabase. Set STEPSYNC_SUPABASE_URL and "
            "STEPSYNC_SUPABASE_SECRET_KEY in backend/.env and restart it."
        )}
    try:
        owner_id = None
        if authorization and authorization.lower().startswith("bearer "):
            owner_id = store.user_id_for_token(authorization[7:].strip())
        if owner_id is None:
            return {"steps": step_info, "supabase_status": "failed",
                    "supabase_error": "Log in to save dances to Supabase; every dance needs an owner."}
        dance = {
            "owner_id": owner_id, "title": title or saved.stem, "source_url": url,
            "video_path": saved.name,  # the name /analyze accepts as reference_video
            "duration_ms": round(metadata.duration_seconds * 1000), "status": "ready",
        }
        dance_id = store.save_dance(dance, frames, steps)
        return {"steps": step_info, "supabase_status": "saved", "supabase_dance_id": dance_id,
                "frames_saved": len(frames)}
    except SupabaseError as error:
        return {"steps": step_info, "supabase_status": "failed", "supabase_error": str(error)}
    except Exception:
        logger.exception("Saving to Supabase failed")
        return {"steps": step_info, "supabase_status": "failed",
                "supabase_error": "Saving to Supabase failed unexpectedly. Check the backend logs."}


def find_saved_video(name: str, directory: Path) -> Path:
    """Look up a video saved by /reference-videos. Only a bare filename is accepted,
    never a path, so a client can't point the server at other files."""
    if not name or name in {".", ".."} or Path(name).name != name or "\\" in name:
        raise HTTPException(400, "reference_video must be a filename returned by /reference-videos.")
    directory = directory.resolve()
    path = (directory / name).resolve()
    if path.parent != directory or not path.is_file():
        raise HTTPException(404, "That reference video was not found on the server. Import the link again.")
    return path


def save_upload(upload: UploadFile, folder: Path, stem: str) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    is_video = (upload.content_type or "").startswith("video/") or suffix in UPLOAD_SUFFIXES
    if not is_video:
        raise HTTPException(415, f"{stem} must be a video file, got {upload.content_type}.")

    path = folder / f"{stem}{suffix if suffix in UPLOAD_SUFFIXES else '.mp4'}"
    written = 0
    with path.open("wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"{stem} video is larger than 300 MB.")
            out.write(chunk)
    if written == 0:
        raise HTTPException(400, f"{stem} video is empty.")
    return path


def placeholder_result(session_id: str, reference: Path, practice: Path) -> dict:
    ref_mb = reference.stat().st_size / 1_000_000
    prac_mb = practice.stat().st_size / 1_000_000
    note = (
        f"Upload received: reference {ref_mb:.1f} MB, practice {prac_mb:.1f} MB "
        f"(session {session_id[:8]}). Real analysis isn't wired up yet."
    )
    return {
        "sessionId": session_id,
        "overallScore": 0,
        "steps": [
            {"id": "1", "label": "Upload", "start": 0, "end": 0, "score": 0, "feedback": note},
        ],
    }


app = create_app()
