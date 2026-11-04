import math

import pytest

from app.comparison import ComparisonConfig, Sample, compare


def sequence(fps=10, duration=3, knee_error=0, wrist_error=0, missing=False, mirror=False):
    samples = []
    for i in range(round(fps * duration) + 1):
        t = i / fps
        phase = t / duration * 2 * math.pi
        values = {
            "left_knee_angle": 140 + 25 * math.sin(phase) - knee_error,
            "right_knee_angle": 150 + 15 * math.cos(phase),
            "left_hip_angle": 150 + 10 * math.cos(phase), "right_hip_angle": 155,
            "left_elbow_angle": 120 + 30 * math.sin(phase), "right_elbow_angle": 150,
            "left_shoulder_angle": 70, "right_shoulder_angle": 80,
            "left_wrist_speed": 0.8 + wrist_error, "right_wrist_speed": 0.8,
        }
        if mirror:
            values = {(k.replace("left_", "right_") if k.startswith("left_")
                       else k.replace("right_", "left_")): v for k, v in values.items()}
        if missing:
            values = {}
        samples.append(Sample(t, values, {k: 0.95 for k in values}, (1, 0, 0)))
    return samples


def test_identical():
    result = compare(sequence(), sequence())
    assert result["scoreAvailable"]
    assert result["overallScore"] == 100
    assert not result["steps"]


def test_known_knee_difference():
    result = compare(sequence(), sequence(knee_error=30), ComparisonConfig(mirror_mode="same"))
    knee = next(s for s in result["steps"] if s["label"] == "Left Knee")
    assert knee["evidence"]["difference"] == pytest.approx(30)
    assert knee["evidence"]["units"] == "degrees"
    assert 0 < knee["evidence"]["confidence"] <= 1
    assert knee["start"] == 0
    assert knee["end"] == 3


def test_weighted_wrist_vs_knee():
    ref = sequence()
    wrist = compare(ref, sequence(wrist_error=0.15))
    knee = compare(ref, sequence(knee_error=30), ComparisonConfig(mirror_mode="same"))
    assert wrist["overallScore"] > knee["overallScore"]


def test_configurable_weights():
    config = ComparisonConfig(weights={"left_knee_angle": 1}, mirror_mode="same")
    reference, practice = sequence(), sequence(knee_error=30)
    # Static poses isolate the scoring formula from temporal warping.
    for s in reference:
        s.values["left_knee_angle"] = 160
    for s in practice:
        s.values["left_knee_angle"] = 130
    result = compare(reference, practice, config)
    assert result["overallScore"] == pytest.approx(66.67, abs=0.1)


def test_known_arm_error():
    reference, practice = sequence(), sequence()
    for s in practice:
        s.values["right_elbow_angle"] -= 35
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    arm = next(s for s in result["steps"] if s["label"] == "Right Elbow")
    assert arm["evidence"]["difference"] == pytest.approx(35)


def test_viewpoint_changes_mask_local_frames():
    practice = sequence()
    for s in practice[10:15]:
        s.axis = (0, 0, 1)
        s.values["left_knee_angle"] -= 40
    result = compare(sequence(), practice)
    assert result["scoreAvailable"]
    assert result["coverage"]["compared"] < 1
    assert not any(s["label"] == "Left Knee" for s in result["steps"])


@pytest.mark.parametrize("fps,duration", [(24, 3), (15, 4.5), (30, 2)])
def test_fps_and_execution_speed(fps, duration):
    result = compare(sequence(), sequence(fps=fps, duration=duration))
    assert result["scoreAvailable"]
    assert result["overallScore"] > 97
    if duration != 3:
        timing = next(s for s in result["steps"] if s["evidence"]["kind"] == "timing")
        assert timing["evidence"]["durationRatio"] == pytest.approx(duration / 3, abs=0.02)


def test_missing_does_not_lower_movement_score():
    practice = sequence()
    for s in practice[10:15]:
        s.values = {}
        s.confidence = {}
    result = compare(sequence(), practice)
    assert result["scoreAvailable"]
    assert result["overallScore"] == 100
    assert result["coverage"]["practice"] < result["coverage"]["reference"]
    assert result["coverage"]["compared"] < 1


def test_no_pose_abstains():
    result = compare(sequence(), sequence(missing=True))
    assert result["status"] == "insufficient_data"
    assert not result["scoreAvailable"]
    assert result["steps"] == []


def test_feedback_uses_practice_seconds_and_groups_frames():
    ref, practice = sequence(), sequence()
    for s in practice:
        if 1 <= s.time <= 2:
            s.values["left_knee_angle"] -= 30
    config = ComparisonConfig(mirror_mode="same", band_fraction=0.01)
    result = compare(ref, practice, config)
    knee = [s for s in result["steps"] if s["label"] == "Left Knee"]
    assert len(knee) == 1
    assert knee[0]["start"] == pytest.approx(1, abs=0.2)
    assert knee[0]["end"] == pytest.approx(2, abs=0.2)


def test_mirrored_match():
    result = compare(sequence(), sequence(mirror=True))
    assert result["overallScore"] == 100
    assert result["alignment"]["mirrored"]
    assert not result["steps"]


def test_ambiguous_laterality_withholds_judgment():
    reference, practice = sequence(), sequence()
    for a, b in zip(reference, practice):
        for name in a.values:
            if name.endswith("_angle"):
                a.values[name] = 160
                b.values[name] = 130
    result = compare(reference, practice)
    assert result["status"] == "uncertain_alignment"
    assert not result["scoreAvailable"]
    assert result["steps"] == []


def test_viewpoint_difference_abstains():
    practice = sequence()
    for s in practice:
        s.axis = (0, 0, 1)
    result = compare(sequence(), practice)
    assert result["status"] == "uncertain_viewpoint"
    assert not result["steps"]


def test_static_motion_has_no_timing_claim():
    ref, practice = sequence(), sequence(duration=4.5)
    for s in ref + practice:
        s.values = dict(ref[0].values)
    result = compare(ref, practice)
    assert not any(s["evidence"]["kind"] == "timing" for s in result["steps"])


@pytest.mark.parametrize("weights", [{"nonsense": 1}, {"left_knee_angle": -1},
                                     {"left_knee_angle": float("nan")}, {"left_wrist_speed": 1}])
def test_invalid_weights(weights):
    with pytest.raises(ValueError):
        ComparisonConfig(weights=weights)
