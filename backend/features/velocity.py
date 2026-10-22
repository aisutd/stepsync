"""Velocity features: how fast joints move between consecutive frames.

- `<angle>_velocity`: change in each joint angle per second (degrees/s).
  Positive means the joint is opening (straightening), negative closing.
- `<joint>_speed`: how fast a keypoint moves in MediaPipe's 3D world
  coordinates (meters/s). World coordinates are centred on the hips, so this is
  speed relative to the body, not travel across the room.

Each value compares a frame with the frame just before it. It is missing (None,
with a reason) when the frame has no pose, for the first frame, when either frame lacks the value, or when
the timestamps don't increase. Missing values are never written as 0.
"""

import math
from dataclasses import dataclass

from .angles import FEATURES


@dataclass(frozen=True)
class SpeedFeature:
    name: str
    joint: str
    units: str = "m/s"


SPEED_FEATURES = [SpeedFeature(f"{j}_speed", j) for j in
                  ("left_wrist", "right_wrist", "left_ankle", "right_ankle")]
ANGLE_VELOCITY_UNITS = "degrees/s"


def _missing(row, reason):
    row["missing_reason"] = reason
    return row


def _base_row(frame, name, units):
    return {"frame_index": frame.frame_index, "timestamp_ms": frame.timestamp_ms,
            "frame_status": frame.frame_status, "feature": name, "value": None,
            "units": units, "status": "missing", "missing_reason": None}


def _point(frame, joint):
    landmark = frame.landmarks.get(joint) if frame.pose_present else None
    if landmark is None or landmark.world is None or not landmark.reliable:
        return None
    return landmark.world


def velocity_rows(frames, angle_rows):
    """Velocity rows for all frames. `angle_rows` are the rows from angles.py."""
    angle_value = {(r["frame_index"], r["feature"]): r["value"] for r in angle_rows}
    rows = []
    previous = None
    for frame in frames:
        dt = None if previous is None else (frame.timestamp_ms - previous.timestamp_ms) / 1000

        for feature in FEATURES:
            row = _base_row(frame, f"{feature.name.removesuffix('_angle')}_velocity",
                            ANGLE_VELOCITY_UNITS)
            if not frame.pose_present:
                rows.append(_missing(row, "no_pose_detected"))
                continue
            if previous is None:
                rows.append(_missing(row, "first_frame"))
                continue
            if dt <= 0:
                rows.append(_missing(row, "non_increasing_timestamp"))
                continue
            now = angle_value.get((frame.frame_index, feature.name))
            before = angle_value.get((previous.frame_index, feature.name))
            if now is None or before is None:
                rows.append(_missing(row, "angle_missing_in_this_or_previous_frame"))
                continue
            row["value"] = round((now - before) / dt, 3)
            row["status"] = "ok"
            rows.append(row)

        for feature in SPEED_FEATURES:
            row = _base_row(frame, feature.name, feature.units)
            if not frame.pose_present:
                rows.append(_missing(row, "no_pose_detected"))
                continue
            if previous is None:
                rows.append(_missing(row, "first_frame"))
                continue
            if dt <= 0:
                rows.append(_missing(row, "non_increasing_timestamp"))
                continue
            now, before = _point(frame, feature.joint), _point(previous, feature.joint)
            if now is None or before is None:
                rows.append(_missing(row, f"unavailable:{feature.joint}"))
                continue
            row["value"] = round(math.dist(now, before) / dt, 4)
            row["status"] = "ok"
            rows.append(row)

        previous = frame
    return rows
