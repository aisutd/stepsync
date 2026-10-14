"""Joint-angle features from pose frames.

Each feature is the angle at a joint between the two body segments that meet
there, e.g. the left elbow angle is between elbow->shoulder and elbow->wrist.
A straight limb is ~180 degrees.

Angles use MediaPipe's 3D world coordinates (meters), so they don't depend on
video size or aspect ratio and include depth. A value is missing (None, with a
reason) when the frame has no pose or a needed landmark is unreliable or has
no coordinates. Missing values are never written as 0.
"""

import math
from dataclasses import dataclass

FEATURE_SET_VERSION = 1


@dataclass(frozen=True)
class AngleFeature:
    """Angle at `vertex`, between the segments vertex->a and vertex->c."""

    name: str
    a: str
    vertex: str
    c: str
    units: str = "degrees"


FEATURES = [
    AngleFeature("left_elbow_angle", "left_shoulder", "left_elbow", "left_wrist"),
    AngleFeature("right_elbow_angle", "right_shoulder", "right_elbow", "right_wrist"),
    AngleFeature("left_knee_angle", "left_hip", "left_knee", "left_ankle"),
    AngleFeature("right_knee_angle", "right_hip", "right_knee", "right_ankle"),
    AngleFeature("left_shoulder_angle", "left_elbow", "left_shoulder", "left_hip"),
    AngleFeature("right_shoulder_angle", "right_elbow", "right_shoulder", "right_hip"),
    AngleFeature("left_hip_angle", "left_shoulder", "left_hip", "left_knee"),
    AngleFeature("right_hip_angle", "right_shoulder", "right_hip", "right_knee"),
]


def angle_degrees(a, vertex, c):
    """Angle in degrees at `vertex` for 2D or 3D points; None if a segment has zero length."""
    v1 = [p - q for p, q in zip(a, vertex)]
    v2 = [p - q for p, q in zip(c, vertex)]
    len1 = math.hypot(*v1)
    len2 = math.hypot(*v2)
    if len1 == 0 or len2 == 0:
        return None
    cos_angle = sum(p * q for p, q in zip(v1, v2)) / (len1 * len2)
    # Floating-point error can push this just outside [-1, 1].
    cos_angle = max(-1.0, min(1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def frame_feature_rows(frame, features=FEATURES):
    """One row per feature for a single PoseFrame."""
    rows = []
    for feature in features:
        row = {
            "frame_index": frame.frame_index,
            "timestamp_ms": frame.timestamp_ms,
            "frame_status": frame.frame_status,
            "feature": feature.name,
            "value": None,
            "units": feature.units,
            "status": "missing",
            "missing_reason": None,
        }

        if not frame.pose_present:
            row["missing_reason"] = "no_pose_detected"
            rows.append(row)
            continue

        points = []
        for joint in (feature.a, feature.vertex, feature.c):
            landmark = frame.landmarks.get(joint)
            if landmark is None or landmark.world is None:
                row["missing_reason"] = f"no_coordinates:{joint}"
                break
            if not landmark.reliable:
                row["missing_reason"] = f"unreliable:{joint}"
                break
            points.append(landmark.world)

        if row["missing_reason"] is None:
            angle = angle_degrees(*points)
            if angle is None:
                row["missing_reason"] = "degenerate_geometry"
            else:
                row["value"] = round(angle, 3)
                row["status"] = "ok"

        rows.append(row)
    return rows


def compute_features(video_id, frames, source_file=None, features=FEATURES):
    """Build the features document for one video."""
    rows = []
    for frame in frames:
        rows.extend(frame_feature_rows(frame, features))
    return {
        "schema_version": 1,
        "feature_set_version": FEATURE_SET_VERSION,
        "video_id": video_id,
        "source_pose_file": source_file,
        "coordinate_space": "mediapipe_world_meters",
        "feature_definitions": [
            {"name": f.name, "units": f.units, "joints": [f.a, f.vertex, f.c]}
            for f in features
        ],
        "rows": rows,
    }
