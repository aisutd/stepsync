"""Save validated MP4s without replacing existing Downloads files."""

import logging
import re
import shutil
from pathlib import Path

from .video import VideoError

logger = logging.getLogger(__name__)


def safe_title(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip().rstrip(". ")
    # Leave room for suffixes and stay below Windows filename/path limits.
    name = name.encode("utf-16-le")[:300].decode("utf-16-le", errors="ignore").rstrip(". ")
    name = name or "YouTube video"
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3]", name.split(".")[0].rstrip(), re.IGNORECASE):
        name = "_" + name
    return name


def save_video(source: Path, title: str, directory: Path) -> Path:
    """Exclusively create a unique file; remove our partial copy on failure."""
    name = safe_title(title)
    try:
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        index = 0
        while True:
            suffix = f" ({index})" if index else ""
            target = directory / f"{name}{suffix}.mp4"
            try:
                destination = target.open("xb")
            except FileExistsError:
                index += 1
                continue
            try:
                with destination, source.open("rb") as original:
                    shutil.copyfileobj(original, destination)
                return target
            except Exception:
                target.unlink(missing_ok=True)
                raise
    except OSError:
        logger.exception("Could not save validated MP4 to Downloads")
        raise VideoError("save_failed", "Could not save the MP4 to Downloads. Check folder permissions and available disk space.", 500)
