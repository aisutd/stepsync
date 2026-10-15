"""Provisional team defaults; override with STEPSYNC_* environment variables."""

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    allowed_extensions: tuple[str, ...] = (".mp4", ".mov")
    max_upload_bytes: int = 100_000_000  # Decimal 100 MB.
    max_duration_seconds: float = 60.0
    target_fps: float = 30.0
    max_frame_width: int = 1280
    max_frame_height: int = 720

    def __post_init__(self):
        if not self.allowed_extensions or any(
            not ext.startswith(".") for ext in self.allowed_extensions
        ):
            raise ValueError("Allowed extensions must start with a dot.")
        for name in ("max_upload_bytes", "max_duration_seconds", "target_fps",
                     "max_frame_width", "max_frame_height"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite.")

    @classmethod
    def from_env(cls):
        return cls(
            allowed_extensions=tuple(
                ext.strip().lower() for ext in os.getenv(
                    "STEPSYNC_ALLOWED_EXTENSIONS", ".mp4,.mov"
                ).split(",")
            ),
            max_upload_bytes=int(os.getenv("STEPSYNC_MAX_UPLOAD_BYTES", "100000000")),
            max_duration_seconds=float(os.getenv("STEPSYNC_MAX_DURATION_SECONDS", "60")),
            target_fps=float(os.getenv("STEPSYNC_TARGET_FPS", "30")),
            max_frame_width=int(os.getenv("STEPSYNC_MAX_FRAME_WIDTH", "1280")),
            max_frame_height=int(os.getenv("STEPSYNC_MAX_FRAME_HEIGHT", "720")),
        )
