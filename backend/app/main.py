"""Local validation API: Validated YouTube videos are saved to Downloads."""

import logging
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import Settings
from .handoff import ProcessingState
from .video import VideoError, validate_video
from .youtube import download_video, validate_url
from .storage import save_video

logger = logging.getLogger(__name__)
DOWNLOADS_DIRECTORY = Path(r"C:\Users\rodri\Downloads")

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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="StepSync local video backend", description=(
        "Validated videos are saved to the local Windows Downloads folder; no authentication, "
        "database, or pose extraction is connected."
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
                saved = save_video(path, downloaded.title, DOWNLOADS_DIRECTORY)
                return UploadResponse(
                    status=ProcessingState.uploaded, source_url=url, filename=saved.name,
                    size_bytes=size, metadata=MetadataResponse(**asdict(metadata)),
                    pose_processing="not_connected", persisted=True, saved_path=str(saved),
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
