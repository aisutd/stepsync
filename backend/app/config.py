"""Provisional team defaults; override with STEPSYNC_* environment variables."""

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def default_data_directory() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "StepSync"


def default_pose_model_path() -> Path:
    return Path(__file__).resolve().parents[1] / "models" / "pose_landmarker_full.task"


@dataclass(frozen=True)
class Settings:
    allowed_extensions: tuple[str, ...] = (".mp4", ".mov")
    max_upload_bytes: int = 100_000_000  # Decimal 100 MB.
    max_duration_seconds: float = 60.0
    target_fps: float = 30.0
    max_frame_width: int = 1280
    max_frame_height: int = 720
    data_directory: Path = field(default_factory=default_data_directory)
    pose_model_path: Path = field(default_factory=default_pose_model_path)
    pose_processing_timeout_seconds: float = 600.0

    def __post_init__(self):
        object.__setattr__(self, "data_directory", Path(self.data_directory).expanduser().resolve())
        object.__setattr__(self, "pose_model_path", Path(self.pose_model_path).expanduser().resolve())
        if not self.allowed_extensions or any(
            not ext.startswith(".") for ext in self.allowed_extensions
        ):
            raise ValueError("Allowed extensions must start with a dot.")
        for name in ("max_upload_bytes", "max_duration_seconds", "target_fps",
                     "max_frame_width", "max_frame_height", "pose_processing_timeout_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite.")

    @property
    def video_directory(self) -> Path:
        return self.data_directory / "videos"

    @property
    def pose_results_directory(self) -> Path:
        return self.data_directory / "pose-results"

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
            data_directory=Path(os.getenv("STEPSYNC_DATA_DIRECTORY", default_data_directory())),
            pose_model_path=Path(os.getenv("STEPSYNC_POSE_MODEL_PATH", default_pose_model_path())),
            pose_processing_timeout_seconds=float(os.getenv("STEPSYNC_POSE_PROCESSING_TIMEOUT_SECONDS", "600")),
        )
