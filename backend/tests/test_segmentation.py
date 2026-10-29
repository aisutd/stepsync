"""Splitting a dance into steps at the strongest pose changes (segment_dance)."""

from pathlib import Path

import numpy as np
import pytest

from app.segmentation import LANDMARKS, MIN_STEP_SECONDS, pose_feature_matrix, segment_dance, segment_steps
from app.supabase_store import add_motion_features, load_pose_frames

SAMPLE_CSV = Path(__file__).resolve().parents[1] / "output" / "reze_pose_data.csv"
needs_sample = pytest.mark.skipif(not SAMPLE_CSV.is_file(), reason="sample pose CSV not in repo")


def posed_frames(poses, fps=30, pose_present=None):
    """Frames whose hip-relative keypoints follow `poses` (frames x 33 x 3)."""
    frames = []
    for i, pose in enumerate(poses):
        present = True if pose_present is None else pose_present[i]
        keypoints = {name: {"hx": float(p[0]), "hy": float(p[1]), "hz": float(p[2]), "reliable": True}
                     for name, p in zip(LANDMARKS, pose)} if present else {}
        frames.append({"frame_index": i, "timestamp_ms": round(i * 1000 / fps), "pose_present": present,
                       "motion_energy": 1.0 if present else None, "joint_angles": {}, "keypoints": keypoints})
    return frames


def routine(changes_at_s, total_s, fps=30, seed=0):
    """Hold a pose, switch to a new one at each time in changes_at_s (0.2 s transition)."""
    rng = np.random.default_rng(seed)
    n = round(total_s * fps)
    targets = [rng.normal(size=(33, 3)) for _ in range(len(changes_at_s) + 1)]
    poses, current = [], 0
    for i in range(n):
        t = i / fps
        while current < len(changes_at_s) and t >= changes_at_s[current] + 0.1:
            current += 1
        pose = targets[current]
        if current < len(changes_at_s):
            start = changes_at_s[current] - 0.1
            if t >= start:
                share = (t - start) / 0.2
                pose = (1 - share) * targets[current] + share * targets[current + 1]
        poses.append(pose)
    return poses


def check_shape(steps):
    assert steps
    assert [s["step_index"] for s in steps] == list(range(len(steps)))
    assert [s["label"] for s in steps] == [f"Step {i + 1}" for i in range(len(steps))]
    for a, b in zip(steps, steps[1:]):
        assert a["end_ms"] == b["start_ms"], "steps must be back to back"
    for s in steps:
        assert s["intensity"] in {"slow", "medium", "fast"}
        assert set(s["focus"]) <= {"arms", "legs", "head", "torso"}


def test_cuts_where_pose_changes():
    changes = [1.0, 2.2, 3.5, 4.6]
    steps = segment_steps(posed_frames(routine(changes, 6.0)))
    check_shape(steps)
    cuts = [s["start_ms"] / 1000 for s in steps[1:]]
    assert len(cuts) == len(changes), cuts
    for cut, change in zip(cuts, changes):
        assert abs(cut - change) <= 0.15, (cut, change)


def test_cuts_are_at_least_min_step_apart():
    # Pose changes every 0.2 s: closer than the minimum, so some must be skipped.
    steps = segment_steps(posed_frames(routine([0.2 * k for k in range(2, 25)], 5.0)))
    check_shape(steps)
    cuts = [s["start_ms"] for s in steps[1:]]
    assert all(b - a >= MIN_STEP_SECONDS * 1000 - 40 for a, b in zip(cuts, cuts[1:]))


def test_held_pose_is_one_step():
    pose = np.random.default_rng(1).normal(size=(33, 3))
    steps = segment_steps(posed_frames([pose] * 90))
    assert len(steps) == 1


def test_trims_frames_without_dancer():
    poses = routine([1.5], 3.0)
    present = [False] * 15 + [True] * (len(poses) - 30) + [False] * 15
    steps = segment_steps(posed_frames(poses, pose_present=present))
    assert steps[0]["start_frame"] == 15 and steps[-1]["end_frame"] == len(poses) - 16


def test_gaps_are_interpolated():
    frames = posed_frames(routine([1.0], 2.0))
    for frame in frames[20:25]:
        frame["keypoints"]["left_wrist"]["reliable"] = False
    frames[40]["keypoints"] = {}
    matrix = pose_feature_matrix(frames)
    assert matrix.shape == (len(frames), 33 * 3 + 8)
    assert not np.isnan(matrix).any()
    check_shape(segment_steps(frames))


def test_no_dancer_gives_no_steps():
    assert segment_steps(posed_frames([np.zeros((33, 3))] * 30, pose_present=[False] * 30)) == []
    assert segment_steps([]) == []


def test_segment_dance_returns_seconds_and_scores():
    features = pose_feature_matrix(posed_frames(routine([1.0, 2.0], 3.0)))
    boundaries, score = segment_dance(features, fps=30)
    assert score.shape == (len(features),)
    assert np.allclose(boundaries, [1.0, 2.0], atol=0.15)


@needs_sample
def test_sample_dance():
    frames = load_pose_frames(SAMPLE_CSV)
    add_motion_features(frames)
    steps = segment_steps(frames)
    check_shape(steps)
    assert len(steps) >= 6
    with_pose = [f for f in frames if f["pose_present"]]
    assert steps[0]["start_ms"] == with_pose[0]["timestamp_ms"]
    assert steps[-1]["end_ms"] == with_pose[-1]["timestamp_ms"]
    cuts = [s["start_ms"] for s in steps[1:]]
    assert all(b - a >= MIN_STEP_SECONDS * 1000 - 40 for a, b in zip(cuts, cuts[1:]))
    assert any(s["focus"] != steps[0]["focus"] for s in steps), "focus should vary between steps"
