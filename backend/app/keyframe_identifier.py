"""Select meaningful pose frames and segment a dance using motion between poses.

This is a heuristic keyframe detector, not a learned choreography segmenter.
All timestamps remain in the original video timeline.
"""
from math import hypot

# MediaPipe indices: shoulders, elbows, wrists, hips, knees and ankles.
JOINTS = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
MIN_CONFIDENCE = 0.45


def _points(frame):
    if not frame.get("pose_present"):
        return {}
    points = {}
    for lm in frame.get("landmarks", []):
        idx = lm.get("landmark_id")
        if idx not in JOINTS:
            continue
        if lm.get("visibility") is not None and lm["visibility"] < MIN_CONFIDENCE:
            continue
        if lm.get("presence") is not None and lm["presence"] < MIN_CONFIDENCE:
            continue
        x = lm.get("smooth_hip_relative_x_norm")
        y = lm.get("smooth_hip_relative_y_norm")
        if x is None or y is None:
            x, y = lm.get("hip_relative_x_norm"), lm.get("hip_relative_y_norm")
        if x is None or y is None:
            x, y = lm.get("smooth_x_norm"), lm.get("smooth_y_norm")
        if x is None or y is None:
            x, y = lm.get("x_norm"), lm.get("y_norm")
        if x is not None and y is not None:
            points[idx] = (float(x), float(y))
    return points if len(points) >= 6 else {}


def _distance(a, b):
    shared = a.keys() & b.keys()
    if len(shared) < 6:
        return None
    return sum(hypot(a[j][0] - b[j][0], a[j][1] - b[j][1]) for j in shared) / len(shared)


def identify_keyframes(frames, min_spacing_ms=400, max_spacing_ms=2000, movement_threshold=0.045):
    """Return ordered indices into frames; exclude frames without reliable body poses.

    Select frames when the pose has moved sufficiently from the last selected pose,
    plus periodic coverage of static holds. Adjacent poses are separated in time.
    """
    if not frames:
        return []
    poses = [_points(f) for f in frames]
    valid = [i for i, p in enumerate(poses) if p]
    if not valid:
        return []
    chosen = [valid[0]]
    for i in valid[1:]:
        prev = chosen[-1]
        elapsed = frames[i]["timestamp_ms"] - frames[prev]["timestamp_ms"]
        if elapsed < min_spacing_ms:
            continue
        distance = _distance(poses[prev], poses[i])
        if elapsed >= max_spacing_ms or (distance is not None and distance >= movement_threshold):
            chosen.append(i)
    last = valid[-1]
    if last != chosen[-1] and frames[last]["timestamp_ms"] - frames[chosen[-1]]["timestamp_ms"] >= min_spacing_ms:
        chosen.append(last)
    return chosen


def group_keyframes(frames, selected, duration_ms, target_step_ms=5000):
    """Return (start_ms, end_ms, frame indices) groups for Supabase steps.

    Groups are time-based practice chunks, not inferred semantic dance moves.
    """
    if not selected:
        return []
    groups = []
    for idx in selected:
        t = frames[idx]["timestamp_ms"]
        bucket = min(max(0, int(t // target_step_ms)), max(0, (duration_ms - 1) // target_step_ms))
        if not groups or groups[-1][0] != bucket:
            groups.append((bucket, []))
        groups[-1][1].append(idx)
    result = []
    for n, (bucket, indices) in enumerate(groups):
        start = 0 if n == 0 else min(duration_ms, bucket * target_step_ms)
        end = duration_ms if n == len(groups) - 1 else min(duration_ms, groups[n + 1][0] * target_step_ms)
        result.append((start, end, indices))
    return result
