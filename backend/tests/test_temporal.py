"""Generated, unseen choreography; no named video or precomputed pose fixture."""

import math

import numpy as np
import pytest

from app.comparison import ComparisonConfig, Sample, compare
from app.temporal import align
from features.angles import FEATURES


def generated(seed, fps=24, duration=8, warp=False, dancer=False, gap=False, mistake=False):
    rng = np.random.default_rng(seed)
    phases = rng.uniform(-math.pi, math.pi, len(FEATURES))
    frequencies = rng.uniform(0.6, 1.4, len(FEATURES))
    noise = np.random.default_rng(seed + 100)
    result = []
    for index in range(round(duration * fps) + 1):
        t = index / fps
        phase = np.interp(t / duration, [0, 0.3, 0.65, 1], [0, 0.4, 0.6, 1]) if warp else t / duration
        values = {}
        for k, feature in enumerate(FEATURES):
            value = 110 + 30 * math.sin(2 * math.pi * frequencies[k] * phase + phases[k])
            value += 12 * math.sin(5 * math.pi * phase + phases[k] / 2)
            if dancer:
                value = 110 + 0.95 * (value - 110) + 3 * math.cos(k) + noise.normal(0, 0.5)
            if mistake and feature.name == "left_knee_angle" and 0.45 <= t / duration <= 0.7:
                value -= 30
            values[feature.name] = value
        if gap and 0.18 < t / duration < 0.25:
            values = {}
        result.append(Sample(t, values, {k: 0.95 for k in values}, (1, 0, 0)))
    return result


@pytest.mark.parametrize("seed", [7, 31, 2026])
def test_unseen_dancer_local_tempo_gap_and_imperfect_knee(seed):
    reference = generated(seed)
    practice = generated(seed, fps=30, duration=10, warp=True, dancer=True, gap=True, mistake=True)
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert result["scoreAvailable"], result
    assert len(result["frameComparisons"]) == len(practice)
    frame_rows = result["frameComparisons"]
    errors = []
    for row in frame_rows:
        if row["status"] != "compared":
            continue
        truth = 8 * np.interp(row["practiceTime"] / 10, [0, 0.3, 0.65, 1], [0, 0.4, 0.6, 1])
        errors.append(abs(row["referenceTime"] - truth))
    assert np.median(errors) < 0.18
    knee = [s for s in result["steps"] if s["label"] == "Left Knee"]
    assert knee, result
    assert any(s["start"] <= 5 and s["end"] >= 6.5 for s in knee)
    # Occluded instants are represented, never filled with synthetic joint values.
    gap_rows = [r for r in frame_rows if 1.9 < r["practiceTime"] < 2.4]
    assert gap_rows and all(r["status"] == "unassessed" for r in gap_rows)


def test_constraints_hold_during_search_not_after_path_selection():
    reference = generated(8, fps=10, duration=8)
    practice = generated(8, fps=24, duration=12, warp=True)
    config = ComparisonConfig(mirror_mode="same")
    path, cost, diagnostics = align(reference, practice, config, False)
    assert path and math.isfinite(cost)
    knots = diagnostics["timeMap"]
    normalized_slopes = [(b["reference"] - a["reference"]) / (b["practice"] - a["practice"]) * 12 / 8
                         for a, b in zip(knots, knots[1:])]
    assert min(normalized_slopes) >= 0.5 - 1e-4
    assert max(normalized_slopes) <= 2 + 1e-4


def test_static_practice_cannot_claim_to_match_dynamic_routine():
    reference = generated(17)
    practice = generated(17)
    for row in practice:
        row.values = dict(reference[0].values)
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert not result["scoreAvailable"]
    assert result["movementScore"] is None
    assert result["reason"]
    assert result["steps"] == []


def test_wrong_movement_order_withholds_score():
    reference = generated(37)
    practice = generated(37)
    reversed_values = [dict(s.values) for s in reversed(practice)]
    for row, values in zip(practice, reversed_values):
        row.values = values
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert not result["scoreAvailable"], result
    assert result["reason"]


def test_missing_frames_do_not_change_score_or_hide_persistent_joint_error():
    reference = generated(42)
    practice = generated(42, gap=True)
    for row in practice:
        if row.values:
            row.values["left_knee_angle"] -= 30
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert result["scoreAvailable"], result
    knee_frames = [joint for row in result["frameComparisons"] for joint in row["joints"]
                   if joint["bodyPart"] == "left_knee" and joint["status"] != "unassessed"]
    assert np.median([j["difference"] for j in knee_frames]) == pytest.approx(30, abs=1)


def test_sparse_reference_timestamps_are_not_interpolated_into_poses():
    reference = [s for s in generated(42) if not 3 < s.time < 4]
    practice = generated(42)
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert result["scoreAvailable"], result
    rows = [r for r in result["frameComparisons"] if 3.3 < r["practiceTime"] < 3.7]
    assert rows and all(r["status"] == "unassessed" for r in rows)


def test_local_tempo_errors_have_timestamped_timing_feedback():
    reference = generated(31, duration=10)
    practice = generated(31, duration=10, warp=True)
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert result["scoreAvailable"], result
    assert result["overallScore"] > 95
    local = [s for s in result["steps"] if s["evidence"].get("timingType") == "local_offset"]
    assert local
    assert all(s["start"] < s["end"] and abs(s["evidence"]["offsetSeconds"]) >= 0.25 for s in local)


def test_low_confidence_direct_features_cannot_be_scored():
    reference, practice = generated(19), generated(19)
    for row in practice:
        row.confidence = {k: 0.4 for k in row.values}
    result = compare(reference, practice)
    assert not result["scoreAvailable"]
    assert result["coverage"]["practice"] == 0
    assert result["movementScore"] is None


def test_repeated_source_timestamps_have_clear_explanation():
    reference, practice = generated(19), generated(19)
    practice[5].time = practice[4].time
    result = compare(reference, practice)
    assert not result["scoreAvailable"]
    assert "timestamps" in result["reason"]
