"""Run pose extraction synchronously against a persisted reference video."""

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .video import VideoError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoseArtifacts:
    preview_path: Path
    data_path: Path


def run_pose_extraction(
    video_path: Path, output_directory: Path, model_path: Path, timeout_seconds: float
) -> PoseArtifacts:
    script_path = Path(__file__).resolve().parents[1] / "pose_extraction.py"
    if not model_path.is_file():
        raise VideoError("pose_model_missing", "The pose model file is missing. Set STEPSYNC_POSE_MODEL_PATH to its location.", 500)
    output_directory.mkdir(parents=True, exist_ok=True)
    preview_path = output_directory / "skeleton_preview.mp4"
    data_path = output_directory / "pose_data.csv"

    def remove_partial_outputs():
        for path in (preview_path, data_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove partial pose output %s", path)

    try:
        subprocess.run(
            [sys.executable, str(script_path), "--input", str(video_path),
             "--output-video", str(preview_path), "--output-csv", str(data_path),
             "--model", str(model_path)],
            cwd=script_path.parent, check=True, capture_output=True, text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        remove_partial_outputs()
        logger.error("Pose extraction timed out for %s", video_path)
        raise VideoError("pose_processing_timeout", "Pose extraction exceeded its time limit.", 500) from error
    except (OSError, subprocess.CalledProcessError) as error:
        remove_partial_outputs()
        logger.error("Pose extraction failed for %s: %s", video_path, str(getattr(error, "stderr", None) or error)[-4000:])
        raise VideoError("pose_processing_failed", "Pose extraction failed. Check the backend logs.", 500) from error
    if any(not path.is_file() or path.stat().st_size == 0 for path in (preview_path, data_path)):
        remove_partial_outputs()
        raise VideoError("pose_processing_failed", "Pose extraction completed without producing both output files.", 500)
    return PoseArtifacts(preview_path, data_path)
