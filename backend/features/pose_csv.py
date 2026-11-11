"""Read the pose CSV written by pose_extraction.py (one row per landmark per frame)."""

import csv
import math
from dataclasses import dataclass, field


@dataclass
class Landmark:
    landmark_id: int
    name: str
    reliable: bool
    # MediaPipe world coordinates in meters; None when the CSV cell is blank.
    world: tuple[float, float, float] | None


@dataclass
class PoseFrame:
    frame_index: int
    timestamp_ms: int
    frame_status: str  # OK, LOW_CONFIDENCE or NO_POSE
    pose_present: bool
    landmarks: dict[str, Landmark] = field(default_factory=dict)


def _float_or_none(text):
    if text is None or text.strip() == "":
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def read_pose_csv(path):
    """Return PoseFrames in file order, with landmarks keyed by name."""
    frames = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            frame_index = int(row["frame_index"])
            frame = frames.get(frame_index)
            if frame is None:
                frame = PoseFrame(
                    frame_index=frame_index,
                    timestamp_ms=int(row["timestamp_ms"]),
                    frame_status=row["frame_status"],
                    pose_present=row["pose_present"] == "1",
                )
                frames[frame_index] = frame

            if not frame.pose_present:
                continue

            coords = tuple(_float_or_none(row[k]) for k in ("world_x", "world_y", "world_z"))
            frame.landmarks[row["landmark_name"]] = Landmark(
                landmark_id=int(row["landmark_id"]),
                name=row["landmark_name"],
                reliable=row["landmark_reliable"] == "1",
                world=None if None in coords else coords,
            )
    return list(frames.values())
