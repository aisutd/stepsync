"""Split a dance into learnable steps using the dancer's movement.

Cuts go where movement dips (the dancer pauses, lands or changes direction):
local minima of the smoothed per-frame motion energy from supabase_store.add_motion_features.
Every step is kept between MIN_STEP_SECONDS and MAX_STEP_SECONDS so it's short enough to
learn: dips too close together are skipped, and long stretches are split at their quietest point.
Frames before the dancer appears and after they leave are trimmed off.
"""

import statistics

MIN_STEP_SECONDS = 1.0
MAX_STEP_SECONDS = 4.0
SMOOTHING_SECONDS = 0.3
# A dip only counts as a cut if it's quieter than this share of the dance's frames.
CUT_PERCENTILE = 40

BODY_PARTS = {
    "arms": ("elbow", "wrist", "pinky", "index", "thumb"),
    "legs": ("knee", "ankle", "heel", "foot_index"),
    "head": ("nose", "eye", "ear", "mouth"),
    "torso": ("shoulder", "hip"),
}


def _part(landmark_name: str) -> str | None:
    for part, words in BODY_PARTS.items():
        if any(word in landmark_name for word in words):
            return part
    return None


def _filled_energy(frames: list[dict]) -> list[float]:
    """Motion energy per frame with gaps (no speed yet, brief detection drops) interpolated."""
    raw = [f.get("motion_energy") for f in frames]
    known = [i for i, v in enumerate(raw) if v is not None]
    if not known:
        return [0.0] * len(frames)
    filled = []
    for i, value in enumerate(raw):
        if value is not None:
            filled.append(value)
            continue
        before = max((k for k in known if k < i), default=None)
        after = min((k for k in known if k > i), default=None)
        if before is None or after is None:
            filled.append(raw[before if after is None else after])
        else:
            share = (i - before) / (after - before)
            filled.append(raw[before] + share * (raw[after] - raw[before]))
    return filled


def _smooth(values: list[float], window: int) -> list[float]:
    half = window // 2
    return [statistics.fmean(values[max(0, i - half): i + half + 1]) for i in range(len(values))]


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct / 100))]


def segment_steps(frames: list[dict]) -> list[dict]:
    """Return steps as dicts: step_index, start/end frame and ms, motion stats, intensity, focus."""
    with_pose = [i for i, f in enumerate(frames) if f.get("pose_present")]
    if len(with_pose) < 2:
        return []
    first, last = with_pose[0], with_pose[-1]
    span = frames[first: last + 1]
    times = [f["timestamp_ms"] for f in span]
    duration_ms = times[-1] - times[0]
    if duration_ms <= 0:
        return []

    fps = (len(span) - 1) / (duration_ms / 1000)
    energy = _smooth(_filled_energy(span), max(1, round(SMOOTHING_SECONDS * fps)))
    min_ms, max_ms = MIN_STEP_SECONDS * 1000, MAX_STEP_SECONDS * 1000

    def fits(cut: int, cuts: list[int]) -> bool:
        return all(abs(times[cut] - times[other]) >= min_ms for other in cuts)

    # Deepest dips first, keeping steps at least MIN_STEP_SECONDS long.
    threshold = _percentile(energy, CUT_PERCENTILE)
    dips = [i for i in range(1, len(span) - 1) if energy[i] <= energy[i - 1] and energy[i] < energy[i + 1]]
    cuts = [0, len(span) - 1]
    for i in sorted(dips, key=lambda i: energy[i]):
        if energy[i] <= threshold and fits(i, cuts):
            cuts.append(i)
    cuts.sort()

    # Split any step longer than MAX_STEP_SECONDS at its quietest allowed frame.
    changed = True
    while changed:
        changed = False
        for a, b in zip(cuts, cuts[1:]):
            if times[b] - times[a] <= max_ms:
                continue
            inside = [k for k in range(a + 1, b) if times[k] - times[a] >= min_ms and times[b] - times[k] >= min_ms]
            if inside:
                cuts.append(min(inside, key=lambda k: energy[k]))
                cuts.sort()
                changed = True
                break

    overall = statistics.fmean(energy) or 1e-9
    baseline = _part_speeds(span)
    steps = []
    for index, (a, b) in enumerate(zip(cuts, cuts[1:])):
        segment = span[a: b + 1]
        values = [f["motion_energy"] for f in segment if f.get("motion_energy") is not None]
        avg = statistics.fmean(values) if values else 0.0
        ratio = avg / overall
        steps.append({
            "step_index": index,
            "label": f"Step {index + 1}",
            "start_frame": span[a]["frame_index"],
            "end_frame": span[b]["frame_index"],
            "start_ms": times[a],
            "end_ms": times[b],
            "avg_motion_energy": round(avg, 4),
            "peak_motion_energy": round(max(values), 4) if values else 0.0,
            "intensity": "slow" if ratio < 0.75 else "fast" if ratio > 1.25 else "medium",
            "focus": _focus(segment, baseline),
        })
    return steps


def _part_speeds(frames: list[dict]) -> dict[str, float]:
    speeds: dict[str, list[float]] = {}
    for frame in frames:
        for name, keypoint in frame.get("keypoints", {}).items():
            part = _part(name)
            if part and keypoint.get("speed") is not None:
                speeds.setdefault(part, []).append(keypoint["speed"])
    return {part: statistics.fmean(v) for part, v in speeds.items() if v}


def _focus(segment: list[dict], baseline: dict[str, float]) -> list[str]:
    """Body parts moving more than they usually do in this dance, most active first (at most two).

    Compared with the whole dance rather than in absolute terms, because hands always move fastest.
    """
    means = _part_speeds(segment)
    ratios = {p: m / baseline[p] for p, m in means.items() if baseline.get(p)}
    if not ratios:
        return []
    above = sorted((p for p, r in ratios.items() if r >= 1.1), key=lambda p: -ratios[p])
    return above[:2] or [max(ratios, key=ratios.get)]
