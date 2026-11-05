"""Local YouTube intake API with synchronous pose extraction."""

import logging
import shutil
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Path as PathParam, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from .config import Settings
from .handoff import ProcessingState
from .pose_processing import PoseArtifacts, run_pose_extraction
from .video import VideoError, validate_video
from .youtube import download_video, validate_url
from .storage import save_video
from .analysis import analyze_videos
from .recompare import RecompareRequest, recompare_session
from .analysis_models import AnalysisSummary, FramePage
from .comparison import ComparisonConfig
from .coaching import CoachingRequest, coach, conversation
from .session_store import (SESSION_PATTERN, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE,
                            load_session, get_frame_page, diagnostics_path)

logger = logging.getLogger(__name__)

# Videos uploaded from the phone app by POST /analyze.
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
BACKEND_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
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
    comparison_config: ComparisonConfig | None = None,
    coaching_generator: Callable | None = None,
) -> FastAPI:
    load_dotenv(BACKEND_ENV_PATH, override=False, encoding="utf-8-sig")
    settings = settings or Settings.from_env()
    pose_runner = pose_runner or run_pose_extraction
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
        if request.url.path == "/analyze":
            message = "Send multipart video files named 'reference' and 'practice'; mirror_mode must be auto, same, or mirrored."
        elif request.url.path == "/reference-videos":
            message = "Send a JSON object with a nonempty string in the 'url' field."
        elif request.url.path.endswith("/recompare"):
            message = "Use a valid session ID and JSON with mirrorMode set to same or mirrored."
        elif request.url.path.endswith("/coaching"):
            message = "Use a valid session ID and a JSON coaching request with message (1-1000 characters) and a distinct requestId for follow-ups."
        else:
            message = "Invalid session ID or pagination parameters. Use a 32-character lowercase hex ID, offset >= 0, and limit from 1 to 100."
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request", "message": message,
            "details": [{"location": list(e["loc"]), "message": e["msg"]} for e in error.errors()],
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

    @app.post("/analyze", response_model=AnalysisSummary,
              summary="Compare two videos and return a compact, coverage-aware summary")
    def analyze(reference: UploadFile = File(...), practice: UploadFile = File(...),
                mirror_mode: Literal["auto", "same", "mirrored"] | None = Form(None)) -> dict:
        """Persists complete measurements; follow returned links for frames or full diagnostics."""
        session_id = uuid.uuid4().hex
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(parents=True)
        try:
            reference_path = save_upload(reference, session_dir, "reference")
            practice_path = save_upload(practice, session_dir, "practice")
        except HTTPException:
            shutil.rmtree(session_dir, ignore_errors=True)
            raise
        try:
            effective_config = (replace(comparison_config or ComparisonConfig(), mirror_mode=mirror_mode)
                                if mirror_mode is not None else comparison_config)
            return analyze_videos(session_id, reference_path, practice_path, session_dir,
                                  settings, pose_runner, effective_config)
        except VideoError as error:
            # Existing phone client displays HTTPException.detail.
            raise HTTPException(error.status_code, error.message) from error
        except Exception as error:
            logger.exception("Comparison failed for session %s", session_id)
            raise HTTPException(500, "Video comparison failed. Check the backend logs.") from error

    @app.post("/analyses/{session_id}/recompare", response_model=AnalysisSummary)
    def recompare(request: RecompareRequest, session_id: str = PathParam(..., pattern=SESSION_PATTERN)):
        source, _ = load_session(UPLOAD_DIR, session_id, settings.analysis_retention_seconds, persist_views=False)
        new_id = uuid.uuid4().hex
        return recompare_session(source, UPLOAD_DIR / new_id, new_id, request.mirrorMode,
                                 settings.analysis_retention_seconds, comparison_config)

    @app.get("/analyses/{session_id}", response_model=AnalysisSummary, summary="Retrieve a saved analysis summary",
             responses={404: {"description": "Unknown or unavailable session"}, 410: {"description": "Expired session"}})
    def analysis_summary(session_id: str = PathParam(..., pattern=SESSION_PATTERN)):
        _, summary = load_session(UPLOAD_DIR, session_id, settings.analysis_retention_seconds)
        return summary

    @app.get("/analyses/{session_id}/frames", response_model=FramePage,
             summary="Retrieve a bounded page of original practice-frame comparisons",
             responses={404: {"description": "Unknown or unavailable session"}, 410: {"description": "Expired session"},
                        416: {"description": "Offset exceeds total frame records"}})
    def analysis_frames(session_id: str = PathParam(..., pattern=SESSION_PATTERN),
                        offset: int = Query(0, ge=0, description="Zero-based record offset, not a video frame index."),
                        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        """Includes assessed and unassessed records, with original timestamps, joint measurements and reasons.

        offset == total returns an empty page; offset > total returns 416.
        Expired sessions return 410; unknown/unavailable sessions return 404.
        """
        directory, summary = load_session(UPLOAD_DIR, session_id, settings.analysis_retention_seconds)
        return get_frame_page(directory, summary, offset, limit)

    @app.get("/analyses/{session_id}/diagnostics", response_class=FileResponse,
             summary="Explicitly retrieve or download the complete persisted analysis",
             responses={200: {"content": {"application/json": {}},
                              "description": "Full JSON including all frame comparisons, alignment evidence and diagnostics."},
                        404: {"description": "Unknown or unavailable session"}, 410: {"description": "Expired session"}})
    def analysis_diagnostics(session_id: str = PathParam(..., pattern=SESSION_PATTERN),
                             download: bool = Query(False, description="Download as an attachment instead of displaying JSON.")):
        """Streams the stored comparison.json without extracting poses or recomputing comparison."""
        directory, _ = load_session(UPLOAD_DIR, session_id, settings.analysis_retention_seconds)
        return FileResponse(diagnostics_path(directory), media_type="application/json",
                            filename=f"analysis-{session_id}.json" if download else None)

    @app.get("/analyses/{session_id}/coaching", summary="Retrieve saved coaching conversation and availability")
    def coaching_history(session_id: str = PathParam(..., pattern=SESSION_PATTERN)):
        import os
        directory, summary = load_session(UPLOAD_DIR, session_id, settings.analysis_retention_seconds)
        return conversation(directory, summary, coaching_generator is not None or bool(os.getenv("GEMINI_API_KEY")))

    @app.post("/analyses/{session_id}/coaching", summary="Generate initial Gemini coaching or ask a follow-up")
    def coaching_message(request: CoachingRequest, session_id: str = PathParam(..., pattern=SESSION_PATTERN)):
        """An empty object requests the cached initial summary. Follow-ups need message and requestId.

        Uses saved evidence only. Does not re-extract videos or alter numerical results.
        Missing/expired sessions use the same 404/410 responses as analysis retrieval.
        Provider failures do not remove or invalidate the comparison.
        """
        directory, summary = load_session(UPLOAD_DIR, session_id, settings.analysis_retention_seconds)
        return coach(directory, summary, request, coaching_generator)

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


app = create_app()
