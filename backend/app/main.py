"""Local validation API: Validated YouTube videos are saved to Downloads."""

import logging
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import Settings
from .handoff import ProcessingState
from .video import VideoError, validate_video
from .youtube import download_video, validate_url
from .storage import save_video

logger = logging.getLogger(__name__)
DOWNLOADS_DIRECTORY = Path(r"C:\Users\rodri\Downloads")


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

    return app


app = create_app()
