"""Splitting a dance into learnable steps from its movement."""

from pathlib import Path

import pytest

from app.segmentation import MAX_STEP_SECONDS, MIN_STEP_SECONDS, segment_steps
from app.supabase_store import add_motion_features, load_pose_frames

SAMPLE_CSV = Path(__file__).resolve().parents[1] / "output" / "reze_pose_data.csv"
needs_sample = pytest.mark.skipif(not SAMPLE_CSV.is_file(), reason="sample pose CSV not in repo")


def synthetic(energies, fps=30, pose=None):
    """Frames with a given motion energy per frame (no keypoints needed)."""
    return [{
        "frame_index": i, "timestamp_ms": round(i * 1000 / fps),
        "pose_present": True if pose is None else pose[i],
        "motion_energy": e, "keypoints": {},
    } for i, e in enumerate(energies)]


def check_shape(steps, frames):
    assert steps, "expected at least one step"
    assert [s["step_index"] for s in steps] == list(range(len(steps)))
    assert [s["label"] for s in steps] == [f"Step {i + 1}" for i in range(len(steps))]
    for a, b in zip(steps, steps[1:]):
        assert a["end_ms"] == b["start_ms"], "steps must be back to back"
    for s in steps:
        seconds = (s["end_ms"] - s["start_ms"]) / 1000
        assert MIN_STEP_SECONDS - 0.05 <= seconds <= MAX_STEP_SECONDS + 0.05, seconds
        assert s["intensity"] in {"slow", "medium", "fast"}
        assert set(s["focus"]) <= {"arms", "legs", "head", "torso"}


@needs_sample
def test_sample_dance():
    frames = load_pose_frames(SAMPLE_CSV)
    add_motion_features(frames)
    steps = segment_steps(frames)
    check_shape(steps, frames)
    assert 6 <= len(steps) <= 14
    with_pose = [f for f in frames if f["pose_present"]]
    # Trimmed to when the dancer is visible (they leave at about 16 s of the 20.5 s clip).
    assert steps[0]["start_ms"] == with_pose[0]["timestamp_ms"]
    assert steps[-1]["end_ms"] == with_pose[-1]["timestamp_ms"]
    assert any(s["focus"] != steps[0]["focus"] for s in steps), "focus should vary between steps"


def test_cuts_at_pauses():
    # 2 s of dancing, a 0.3 s pause, repeated 4 times: cuts should land in the pauses.
    move, pause = [2.0] * 60, [0.1] * 9
    energies = (move + pause) * 4 + move
    steps = segment_steps(synthetic(energies))
    check_shape(steps, None)
    pause_centres_ms = [round((k * 69 + 64) * 1000 / 30) for k in range(4)]
    cuts = [s["start_ms"] for s in steps[1:]]
    assert len(cuts) == 4
    for cut, centre in zip(cuts, pause_centres_ms):
        assert abs(cut - centre) <= 200, (cut, centre)


def test_long_steady_motion_is_split():
    # 10 s with no pauses at all must still become steps of at most 4 s.
    steps = segment_steps(synthetic([1.5] * 300))
    check_shape(steps, None)
    assert len(steps) >= 3


def test_close_pauses_respect_minimum():
    # Pauses every 0.5 s would make tiny steps; none may be shorter than the minimum.
    energies = ([2.0] * 12 + [0.1] * 3) * 20
    check_shape(segment_steps(synthetic(energies)), None)


def test_trims_frames_without_dancer():
    pose = [False] * 30 + [True] * 120 + [False] * 30
    energies = [None] * 30 + [1.0] * 120 + [None] * 30
    steps = segment_steps(synthetic(energies, pose=pose))
    assert steps[0]["start_frame"] == 30 and steps[-1]["end_frame"] == 149


def test_no_dancer_gives_no_steps():
    assert segment_steps(synthetic([None] * 60, pose=[False] * 60)) == []
    assert segment_steps([]) == []


def test_short_clip_is_one_step():
    steps = segment_steps(synthetic([1.0] * 40))  # 1.3 s
    assert len(steps) == 1
