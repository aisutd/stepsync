"""Local YouTube intake API with synchronous pose extraction."""

import logging
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import Settings
from .handoff import ProcessingState
from .pose_processing import PoseArtifacts, run_pose_extraction
from .video import VideoError, validate_video
from .youtube import download_video, validate_url
from .storage import save_video
from .supabase_routes import register_supabase

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


def create_app(
    settings: Settings | None = None,
    pose_runner: Callable[[Path, Path, Path, float], PoseArtifacts] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    pose_runner = pose_runner or run_pose_extraction
    app = FastAPI(title="StepSync local video backend", description=(
        "Validated videos are saved locally and processed by the pose extractor. "
        "Supabase routes pass the caller's token on, so row level security decides access."
    ))

    # Lets the Expo web build (a different origin) call the API during development.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    register_supabase(app, settings, pose_runner)

    from .dtw_routes import install_dtw_routes
    install_dtw_routes(app, settings, pose_runner)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.exception_handler(VideoError)
    async def video_error_handler(request, error):
        return JSONResponse(status_code=error.status_code,
                            content={"error": {"code": error.code, "message": error.message}})

    @app.exception_handler(RequestValidationError)
    async def request_error_handler(request, error):
        if request.url.path != "/reference-videos":  # the url message only fits that route
            return await request_validation_exception_handler(request, error)
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request", "message": "Send a JSON object with a nonempty string in the 'url' field."
        }})

    @app.post("/reference-videos", response_model=UploadResponse, status_code=200)
    def upload_video(request: YouTubeRequest):
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
                )
            return UploadResponse(
                status=ProcessingState.completed, source_url=url, filename=saved.name,
                size_bytes=size, metadata=MetadataResponse(**asdict(metadata)),
                pose_processing="completed", persisted=True, saved_path=str(saved),
                pose_preview_path=str(artifacts.preview_path), pose_data_path=str(artifacts.data_path),
            )
        except VideoError:
            raise
        except Exception:
            logger.exception("Local video validation failed")
            raise VideoError("processing_failed", "Video inspection failed unexpectedly. Check the backend logs.", 500)

    @app.post("/analyze")
    def analyze(reference: UploadFile = File(...), practice: UploadFile = File(...)) -> dict:
        """Receives the reference and practice videos from the phone app."""
        session_id = uuid.uuid4().hex
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(parents=True)
        try:
            reference_path = save_upload(reference, session_dir, "reference")
            practice_path = save_upload(practice, session_dir, "practice")
        except HTTPException:
            shutil.rmtree(session_dir, ignore_errors=True)
            raise
        # TODO: replace with the real pipeline (pose estimation, DTW, scoring).
        # The response shape must match AnalysisResult in frontend/src/api/types.ts.
        return placeholder_result(session_id, reference_path, practice_path)

    return app


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
