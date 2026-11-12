"""StepSync post-session dance comparison from long-format MediaPipe pose CSVs.

Uses 2D joint angles, hip-centered positions, global mirror selection and DTW.
Scores are uncalibrated heuristics: validate against human-rated recordings.
"""

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median

JOINTS = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
ANGLES = {
    "left_elbow": (11, 13, 15), "right_elbow": (12, 14, 16),
    "left_shoulder": (13, 11, 23), "right_shoulder": (14, 12, 24),
    "left_knee": (23, 25, 27), "right_knee": (24, 26, 28),
    "left_hip": (11, 23, 25), "right_hip": (12, 24, 26),
}
REGIONS = {
    "Arms": ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder"),
    "Legs": ("left_knee", "right_knee", "left_hip", "right_hip"),
}
MIRROR_IDS = {11: 12, 12: 11, 13: 14, 14: 13, 15: 16, 16: 15,
              23: 24, 24: 23, 25: 26, 26: 25, 27: 28, 28: 27}
# Landmark-derived measurements contain jitter, so small differences get no penalty.
ANGLE_TOLERANCE = math.radians(7)
POSITION_TOLERANCE = 0.10  # normalized torso lengths


@dataclass
class PoseFrame:
    time: float
    xyz: dict
    angles: dict


def _angle(a, b, c):
    """Planar angle at b in radians; avoid unstable monocular z estimates."""
    ux, uy = a[0] - b[0], a[1] - b[1]
    vx, vy = c[0] - b[0], c[1] - b[1]
    nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
    if nu < 1e-8 or nv < 1e-8:
        return None
    cos_angle = (ux * vx + uy * vy) / (nu * nv)
    return math.acos(max(-1.0, min(1.0, cos_angle)))


def _make_frame(time, points):
    angles = {}
    for name, (a, b, c) in ANGLES.items():
        if a in points and b in points and c in points:
            angle = _angle(points[a], points[b], points[c])
            if angle is not None:
                angles[name] = angle
    return PoseFrame(time, points, angles)


def read_pose_csv(path: str | Path, sample_hz=10.0, min_confidence=0.5,
                  reference_start=None, reference_end=None):
    """Use StepSync's existing keyframe_identifier on previously extracted pose CSVs.

    MediaPipe extraction remains in backend/pose_extraction.py. We do not
    implement another extractor or sample at a fixed FPS for DTW. The existing
    selector chooses movement-sensitive pose frames; the scorer then builds its
    usual normalized 2D joint features from *only* those selected frames.

    sample_hz is retained for compatibility with earlier compare_csv callers;
    it no longer controls the selection rate.
    """
    from .keyframe_identifier import identify_keyframes

    frames = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                index = int(row["frame_index"])
                joint = int(row["landmark_id"])
                if joint not in JOINTS:
                    continue
                if str(row.get("pose_present", "1")).strip().lower() in ("0", "false", "no"):
                    continue
                t_ms = float(row["timestamp_ms"])
                if reference_start is not None and t_ms < reference_start * 1000:
                    continue
                if reference_end is not None and t_ms > reference_end * 1000:
                    continue
                visibility = row.get("visibility")
                presence = row.get("presence")
                if visibility not in (None, "") and float(visibility) < min_confidence:
                    continue
                if presence not in (None, "") and float(presence) < min_confidence:
                    continue
                x, y = float(row["x_norm"]), float(row["y_norm"])
                if not all(map(math.isfinite, (t_ms, x, y))):
                    continue
                frame = frames.setdefault(index, {
                    "timestamp_ms": t_ms, "pose_present": True,
                    "landmarks": [], "points": {},
                })
                frame["points"][joint] = (x, y)
                frame["landmarks"].append({
                    "landmark_id": joint, "x_norm": x, "y_norm": y,
                    "visibility": float(visibility) if visibility not in (None, "") else None,
                    "presence": float(presence) if presence not in (None, "") else None,
                })
            except (ValueError, TypeError, KeyError):
                continue

    valid = []
    for frame in sorted(frames.values(), key=lambda f: f["timestamp_ms"]):
        pts = frame["points"]
        if not all(j in pts for j in (11, 12, 23, 24)):
            continue
        hip = ((pts[23][0] + pts[24][0]) / 2, (pts[23][1] + pts[24][1]) / 2)
        shoulder = ((pts[11][0] + pts[12][0]) / 2, (pts[11][1] + pts[12][1]) / 2)
        if math.dist(hip, shoulder) < 0.025:
            continue
        # Keep frames with enough stable joints for both the selector and DTW.
        normalized = {j: ((xy[0] - hip[0]) / math.dist(hip, shoulder),
                           (xy[1] - hip[1]) / math.dist(hip, shoulder))
                      for j, xy in pts.items()}
        pose = _make_frame(frame["timestamp_ms"] / 1000, normalized)
        if len(pose.angles) < 3 or len(pts) < 6:
            continue
        frame["pose"] = pose
        valid.append(frame)

    indices = identify_keyframes(valid)
    return [valid[i]["pose"] for i in indices]


def _mirror_frame(frame):
    """Flip screen x and exchange left/right body labels consistently."""
    points = {MIRROR_IDS[j]: (-xy[0], xy[1]) for j, xy in frame.xyz.items()}
    return _make_frame(frame.time, points)


def pose_error(a, b):
    common_angles = set(a.angles) & set(b.angles)
    common_points = set(a.xyz) & set(b.xyz)
    if len(common_angles) < 3 or len(common_points) < 6:
        return 1.0
    angle_error = sum(max(0, abs(a.angles[k] - b.angles[k]) - ANGLE_TOLERANCE) / math.pi
                      for k in common_angles) / len(common_angles)
    xy_error = sum(min(2.0, max(0, math.dist(a.xyz[k], b.xyz[k]) - POSITION_TOLERANCE)) / 2
                   for k in common_points) / len(common_points)
    # Missing landmarks should not make a partial pose appear artificially perfect.
    missing_penalty = 0.10 * (1 - len(common_points) / len(JOINTS))
    return 0.75 * angle_error + 0.25 * xy_error + missing_penalty


def _dtw(ref, usr, band_fraction=0.30):
    n, m = len(ref), len(usr)
    if n < 3 or m < 3:
        raise ValueError("Not enough usable body poses in one of the videos.")
    band = max(8, math.ceil(max(n, m) * band_fraction))
    previous = {0: 0.0}
    parents = {}
    for i in range(1, n + 1):
        current = {}
        center = i * m / n
        for j in range(max(1, math.floor(center - band)), min(m, math.ceil(center + band)) + 1):
            options = (
                (previous.get(j - 1, float("inf")), (i - 1, j - 1)),
                (previous.get(j, float("inf")) + 0.03, (i - 1, j)),
                (current.get(j - 1, float("inf")) + 0.03, (i, j - 1)),
            )
            best, parent = min(options, key=lambda item: item[0])
            if not math.isfinite(best):
                continue
            current[j] = best + pose_error(ref[i - 1], usr[j - 1])
            parents[(i, j)] = parent
        previous = current
    if m not in previous:
        raise ValueError("Dance lengths differ too much for constrained DTW.")
    path = []
    position = (n, m)
    while position != (0, 0):
        i, j = position
        if i and j:
            path.append((i - 1, j - 1))
        position = parents[position]
    path.reverse()
    return path


def _avg_path_error(ref, usr, path):
    return sum(pose_error(ref[i], usr[j]) for i, j in path) / len(path)


def _movement_score(cost):
    """Interpret average normalized pose error on a less punitive scale.

    A close match receives less penalty for harmless camera/landmark differences;
    larger mismatches get an increasingly strong penalty instead of a flat bonus.
    This curve is a provisional product calibration, NOT validated percent accuracy.
    Keep DTW path and error calculation unchanged so comparisons are reproducible.
    """
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("Invalid movement comparison cost")
    mismatch = max(0.0, cost - 0.14)
    penalty = 1.3 * cost + 9.0 * mismatch * mismatch
    return round(max(0, min(100, 100 * math.exp(-penalty))))


def _consistent_delta(ref, usr, pairs, measure, min_magnitude, min_fraction=0.70):
    """Return signed median only when enough aligned frames support a correction."""
    values = []
    for i, j in pairs:
        try:
            a = measure(ref[i])
            b = measure(usr[j])
            if a is not None and b is not None and math.isfinite(a) and math.isfinite(b):
                values.append(b - a)
        except (KeyError, ZeroDivisionError):
            continue
    if len(values) < max(3, math.ceil(0.55 * len(pairs))):
        return None
    delta = median(values)
    if abs(delta) < min_magnitude:
        return None
    agreement = sum(1 for x in values if x * delta > 0) / len(values)
    if agreement < min_fraction:
        return None
    return delta


def _location(frame, joint, anchor, axis):
    """Position in torso-length units relative to a nearby body joint."""
    if joint not in frame.xyz or anchor not in frame.xyz:
        return None
    return frame.xyz[joint][axis] - frame.xyz[anchor][axis]


def _outward(frame, joint, anchor, side):
    """Positive when farther sideways from torso; handles front-view orientation."""
    if joint not in frame.xyz or anchor not in frame.xyz:
        return None
    # Use observed shoulder axis to determine image-left / image-right,
    # so corrections still work after a global mirrored-camera transform.
    if 11 not in frame.xyz or 12 not in frame.xyz:
        return None
    sign = 1 if frame.xyz[12][0] > frame.xyz[11][0] else -1
    if side == 'left':
        sign = -sign
    return sign * (frame.xyz[joint][0] - frame.xyz[anchor][0])


def _stable_comparison(ref, usr, pairs, measure, min_change, min_fraction=0.70):
    """Return (reference median, student median, difference) for consistent evidence.

    At least three comparisons and over half the local aligned pairs must have usable
    measurements; at least 70% must agree on the correction direction.
    """
    observations = []
    for i, j in pairs:
        try:
            target = measure(ref[i])
            actual = measure(usr[j])
            if (target is not None and actual is not None
                    and math.isfinite(target) and math.isfinite(actual)):
                observations.append((target, actual))
        except (KeyError, ZeroDivisionError):
            continue
    if len(observations) < max(3, math.ceil(len(pairs) * 0.55)):
        return None
    target = median(v[0] for v in observations)
    actual = median(v[1] for v in observations)
    difference = actual - target
    if abs(difference) < min_change:
        return None
    sign_support = sum(1 for a, b in observations if (b-a) * difference > 0) / len(observations)
    if sign_support < min_fraction:
        return None
    return (target, actual, difference)


def _height_description(height, body_part):
    """Human-readable height relative to shoulder/hip, in normalized torso units."""
    if body_part == 'hand':
        if height < -0.35:
            return 'above shoulder height'
        if height <= 0.20:
            return 'near shoulder height'
        if height <= 0.75:
            return 'between shoulder and waist height'
        return 'down near your waist'
    if height < 0.15:
        return 'near hip height'
    if height < 0.55:
        return 'partway up toward your hip'
    return 'low, below your hip'


def _joint_feedback(ref, usr, pairs):
    """Natural, precise instructor feedback, backed by stable pose differences.

    Describe the visible difference, then the adjustment and why it helps.
    Do not include score labels, degrees, or prefixed 'Coach’s focus'.
    """
    candidates = []
    for side, elbow, wrist, shoulder, hip, knee, ankle in (
        ('left', 13, 15, 11, 23, 25, 27),
        ('right', 14, 16, 12, 24, 26, 28),
    ):
        def add(priority, limb, prose):
            candidates.append((priority, side, limb, prose))

        hand_height = _stable_comparison(
            ref, usr, pairs,
            lambda f, a=wrist, b=shoulder: _location(f, a, b, 1), 0.22)
        if hand_height:
            target, actual, delta = hand_height
            direction = 'lower' if delta > 0 else 'higher'
            target_phrase = _height_description(target, 'hand')
            actual_phrase = _height_description(actual, 'hand')
            add(abs(delta) / 0.35 + .1, 'arm',
                f'Pay attention to your {side} hand here. In the tutorial, it comes {target_phrase}, but yours stays {actual_phrase}. '
                f'Try bringing it {direction} before moving into the next part so your arm matches the dancer’s position.')

        hand_width = _stable_comparison(
            ref, usr, pairs,
            lambda f, a=wrist, b=shoulder, side=side: _outward(f, a, b, side), 0.30)
        if hand_width:
            _, _, delta = hand_width
            if delta > 0:
                prose = (f'Your {side} hand reaches farther out to the side than in the tutorial. '
                         f'Bring that arm a little closer to your body so its position matches the dancer’s more closely.')
            else:
                prose = (f'Your {side} arm stays too close to your body compared with the tutorial. '
                         f'Reach farther to the side to complete the shape of the movement.')
            add(abs(delta) / 0.45, 'arm', prose)

        elbow_bend = _stable_comparison(
            ref, usr, pairs,
            lambda f, name=f'{side}_elbow': math.degrees(f.angles[name]) if name in f.angles else None,
            15.0)
        if elbow_bend:
            _, _, delta = elbow_bend
            if delta > 0:
                prose = (f'Your {side} arm is a little too straight in this part. Notice how the dancer keeps more bend at the elbow. '
                         f'Try relaxing that arm into the same bent position before moving on.')
            else:
                prose = (f'You keep your {side} elbow more bent than the tutorial dancer. '
                         f'Extend that arm farther so you finish with a more open, defined position.')
            add(abs(delta) / 25.0, 'arm', prose)

        knee_height = _stable_comparison(
            ref, usr, pairs,
            lambda f, a=knee, b=hip: _location(f, a, b, 1), 0.20)
        if knee_height:
            target, actual, delta = knee_height
            target_phrase = _height_description(target, 'knee')
            if delta > 0:
                prose = (f'You’ve got the basic step, but your {side} knee isn’t coming up quite as high as the dancer’s. '
                         f'Try lifting it toward {target_phrase} before you move on to the next beat.')
            else:
                prose = (f'You lift your {side} knee higher than the tutorial dancer does here. '
                         f'Keep the lift smaller and match the reference knee height more closely.')
            add(abs(delta) / 0.35 + .1, 'leg', prose)

        knee_width = _stable_comparison(
            ref, usr, pairs,
            lambda f, a=knee, b=hip, side=side: _outward(f, a, b, side), 0.23)
        if knee_width:
            _, _, delta = knee_width
            if delta > 0:
                prose = (f'You’re getting the movement, but watch your {side} knee. It comes a little too far out to the side compared with the dancer in the tutorial. '
                         f'Try keeping it closer to your other leg as you go through the step. That will make the movement look cleaner and more controlled.')
            else:
                prose = (f'Watch your {side} knee here. You’re keeping it closer to your other leg than the dancer does. '
                         f'Let it move a little farther out to the side so you can finish the step with the same shape.')
            add(abs(delta) / 0.35, 'leg', prose)

        knee_bend = _stable_comparison(
            ref, usr, pairs,
            lambda f, name=f'{side}_knee': math.degrees(f.angles[name]) if name in f.angles else None,
            15.0)
        if knee_bend:
            _, _, delta = knee_bend
            if delta > 0:
                prose = (f'Your {side} leg is straighter than the tutorial dancer’s during this move. '
                         f'Keep a little more bend in that knee so your leg matches the intended shape.')
            else:
                prose = (f'Watch your {side} leg as you finish this move. You’re keeping that knee bent longer than the dancer does. '
                         f'Try straightening the leg a little more before going into the next step, so the finish looks sharper.')
            add(abs(delta) / 25.0, 'leg', prose)

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected, used = [], set()
    for _priority, side, limb, prose in candidates:
        if (side, limb) in used:
            continue
        selected.append(prose)
        used.add((side, limb))
        if len(selected) == 2:
            break
    return ' '.join(selected)


def _match_label(score):
    """Qualitative interpretation of a heuristic score, NOT percent accuracy."""
    if score >= 90:
        return 'Very close match'
    if score >= 75:
        return 'Good match — a few things to improve'
    if score >= 60:
        return 'Recognizable move — focus on the biggest difference'
    return 'Needs another try — compare the key positions'


def compare_csv(reference_path, practice_path, sample_hz=10,
                reference_start=None, reference_end=None):
    if reference_start is not None or reference_end is not None:
        if (reference_start is None or reference_end is None
                or not (math.isfinite(reference_start) and math.isfinite(reference_end)
                        and 0 <= reference_start < reference_end)):
            raise ValueError("Invalid tutorial step boundaries.")
    ref = read_pose_csv(reference_path, sample_hz,
                        reference_start=reference_start, reference_end=reference_end)
    usr = read_pose_csv(practice_path, sample_hz)
    if len(ref) < 3 or len(usr) < 3:
        raise ValueError("Too few reliable keyframes. Record the complete move with your full body visible.")

    direct_path = _dtw(ref, usr)
    direct_cost = _avg_path_error(ref, usr, direct_path)
    mirrored_usr = [_mirror_frame(p) for p in usr]
    mirrored_path = _dtw(ref, mirrored_usr)
    mirrored_cost = _avg_path_error(ref, mirrored_usr, mirrored_path)
    # Select a *single* orientation for the whole video, never per frame.
    mirrored = mirrored_cost + 0.01 < direct_cost
    if mirrored:
        usr, path, mean_error = mirrored_usr, mirrored_path, mirrored_cost
    else:
        path, mean_error = direct_path, direct_cost

    movement = _movement_score(mean_error)
    ref_duration = max(0.001, ref[-1].time - ref[0].time)
    usr_duration = max(0.001, usr[-1].time - usr[0].time)
    tempo_ratio = usr_duration / ref_duration
    off_diagonal = sum(1 for a, b in zip(path, path[1:])
                       if a[0] == b[0] or a[1] == b[1])
    hesitation_fraction = off_diagonal / max(1, len(path) - 1)
    timing = round(100 * math.exp(-1.4 * abs(math.log(tempo_ratio))
                                   - 1.5 * hesitation_fraction))

    steps = []
    pieces = min(12, max(3, math.ceil(ref_duration / 1.5)))
    for idx in range(pieces):
        start = ref[0].time + ref_duration * idx / pieces
        end = ref[0].time + ref_duration * (idx + 1) / pieces
        local = [(i, j) for i, j in path
                 if start <= ref[i].time < (end if idx < pieces - 1 else end + 1e-6)]
        if not local:
            continue
        cost = _avg_path_error(ref, usr, local)
        movement_local = _movement_score(cost)
        off = sum(1 for a, b in zip(local, local[1:])
                  if a[0] == b[0] or a[1] == b[1])
        timing_local = round(100 * math.exp(-1.5 * off / max(1, len(local) - 1)))
        score = round(0.8 * movement_local + 0.2 * timing_local)
        correction = _joint_feedback(ref, usr, local)
        if correction:
            message = correction
        elif score >= 80:
            message = "Your position is close to the tutorial here. Keep that same control as you move into the next part."
        else:
            message = ("I can’t identify a consistent position difference from this section’s camera tracking. "
                       "Watch this moment side by side with the tutorial and try again with your whole body in view.")
        if timing_local < 80:
            message += " Your timing shifts slightly here. Try to complete the movement in time with the tutorial before starting the next one."
        steps.append({
            "id": str(idx + 1), "label": f"Section {idx + 1}",
            "start": round(usr[local[0][1]].time, 2),
            "end": round(max(usr[local[0][1]].time, usr[local[-1][1]].time), 2),
            "score": score, "feedback": message,
            "referenceStart": round(start, 2), "referenceEnd": round(end, 2),
        })
    return {
        "overallScore": round(0.8 * movement + 0.2 * timing),
        "movementScore": movement,
        "timingScore": timing,
        "tempoRatio": round(tempo_ratio, 3),
        "hesitationFraction": round(hesitation_fraction, 3),
        "steps": steps,
        "matchedPairs": len(path),
        "referenceSamples": len(ref),
        "practiceSamples": len(usr),
        "mirrored": mirrored,
        "scoringFrames": "keyframes",
        "matchLabel": _match_label(round(0.8 * movement + 0.2 * timing)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two MediaPipe pose CSV files")
    parser.add_argument("reference")
    parser.add_argument("practice")
    args = parser.parse_args()
    print(json.dumps(compare_csv(args.reference, args.practice), indent=2))
