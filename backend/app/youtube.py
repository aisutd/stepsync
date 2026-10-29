"""Single public YouTube video intake; caller owns the temporary directory."""

import logging
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, PostProcessingError

from .config import Settings
from .video import VideoError

logger = logging.getLogger(__name__)


def validate_url(url: str) -> str:
    url = url.strip()
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise VideoError("invalid_url", "Supply a valid YouTube video URL.")
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or port is not None
            or any(c.isspace() for c in url)):
        raise VideoError("invalid_url", "Supply a valid HTTP(S) YouTube video URL.")
    host = parsed.hostname.lower()
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
        raise VideoError("unsupported_url", "Only YouTube video URLs are supported.")
    query = parse_qs(parsed.query)
    if "list" in query:
        raise VideoError("unsupported_url", "Playlists are not supported; supply a single video URL without list parameters.")
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.removeprefix("/")
    elif parsed.path == "/watch":
        ids = query.get("v", [])
        video_id = ids[0] if len(ids) == 1 else ""
    else:
        match = re.fullmatch(r"/shorts/([A-Za-z0-9_-]{11})/?", parsed.path)
        video_id = match.group(1) if match else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise VideoError("invalid_url", "Supply a YouTube watch, youtu.be, or Shorts URL with a valid video ID.")
    # Drop unrelated parameters and use only the YouTube video extractor.
    return f"https://www.youtube.com/watch?v={video_id}"


def _check_metadata(info, settings):
    if not info:
        raise VideoError("video_unavailable", "The YouTube video is unavailable.")
    if info.get("_type", "video") != "video" or info.get("entries") is not None:
        raise VideoError("unsupported_url", "Only one normal video is supported.")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise VideoError("unsupported_video", "Live or upcoming streams are not supported.")
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and math.isfinite(duration) and duration > settings.max_duration_seconds:
        raise VideoError("video_too_long", f"Video exceeds the {settings.max_duration_seconds:g}-second limit.")


@dataclass(frozen=True)
class DownloadedVideo:
    path: Path
    title: str


def download_video(url: str, directory: Path, settings: Settings) -> DownloadedVideo:
    """Preflight metadata, then download/remux an MP4 within caller-owned storage."""
    url = validate_url(url)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise VideoError("ffmpeg_unavailable", "Install FFmpeg (including ffprobe), add its bin directory to PATH, and restart the backend.", 503)

    def check_size(progress):
        if progress.get("downloaded_bytes", 0) > settings.max_upload_bytes:
            raise VideoError("upload_too_large", f"Download exceeds the {settings.max_upload_bytes}-byte limit.", 413)
        if sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()) > settings.max_upload_bytes:
            raise VideoError("upload_too_large", f"Temporary downloads exceed the {settings.max_upload_bytes}-byte limit.", 413)

    options = {
        "quiet": True, "no_warnings": True, "logger": logger,
        "noplaylist": True, "socket_timeout": 30, "retries": 2,
        "outtmpl": str(directory / "input.%(ext)s"),
        "format": "bv[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[vcodec^=avc1][ext=mp4]/bv[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        "max_filesize": settings.max_upload_bytes,
        "progress_hooks": [check_size],
        "match_filter": lambda info, *, incomplete=False: _check_metadata(info, settings),
    }
    phase = "metadata"
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
            _check_metadata(info, settings)
            phase = "download"
            downloader.process_ie_result(info, download=True)
    except VideoError:
        raise
    except (DownloadError, PostProcessingError) as error:
        logger.warning("YouTube %s failed: %s", phase, error)
        detail = str(error).lower()
        if isinstance(error, PostProcessingError) or any(term in detail for term in ("ffmpeg", "ffprobe", "postprocessing")):
            raise VideoError("ffmpeg_failed", "FFmpeg could not merge or remux the downloaded video.", 502)
        if any(term in detail for term in ("sign in", "login", "age-restricted", "confirm your age", "private video", "unavailable", "removed", "not available")):
            raise VideoError("video_unavailable", "The video is unavailable, private, restricted, or requires login.")
        raise VideoError("download_failed", "YouTube metadata retrieval or download failed. Try again or use another public video.", 502)
    path = directory / "input.mp4"
    if not path.is_file():
        raise VideoError("download_failed", "The downloader did not produce an MP4 (the video may exceed the size limit).", 502)
    return DownloadedVideo(path, info.get("title") or info.get("id") or "YouTube video")
