"""Diagnostics and partial evidence use generated data, not particular videos."""

import math

import pytest

from app.comparison import ComparisonConfig, Sample, compare, samples_from_frames
from app.comparison_diagnostics import pair_evidence
from app.temporal import _matrices
from test_comparison import sequence
from test_features import pose_frames
from test_temporal import generated


def test_unassessed_video_still_has_every_frame_and_real_observations():
    reference, practice = sequence(), sequence()
    for s in practice:
        s.axis = (0, 0, 1)
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert not result["scoreAvailable"]
    assert len(result["frameComparisons"]) == len(practice)
    assert all(r["status"] == "unassessed" and r["reason"] for r in result["frameComparisons"])
    assert all(j["expected"] is None and j["difference"] is None and j["confidence"] == 0
               for r in result["frameComparisons"] for j in r["joints"])
    assert result["frameComparisons"][0]["joints"][0]["observed"] is not None
    rejection = result["alignment"]["anchorRejections"]
    assert rejection["rejected"] == rejection["total"]
    assert rejection["rejectionReasons"]["viewpoint_axis_mismatch"] == rejection["total"]
    assert all(j["rejected"] == rejection["total"] for j in rejection["byJoint"].values())


def test_source_confidence_reason_survives_adapter():
    config = ComparisonConfig()
    reference = samples_from_frames(pose_frames(), config, sample=False)
    practice = samples_from_frames(pose_frames(confidence=0.6), config, sample=False)
    result = compare(reference, practice, config)
    summary = result["diagnostics"]["practice"]["byJoint"]["left_knee_angle"]
    assert summary["rejected"] == len(practice)
    assert summary["rejectionReasons"] == {"below_comparison_confidence": len(practice)}
    assert len(result["frameComparisons"]) == len(practice)
    assert "practice:below_comparison_confidence" in result["frameComparisons"][0]["joints"][2]["reasons"]


def test_mirror_reflects_camera_geometry_and_swaps_angles_together():
    reference, practice = sequence(), sequence(mirror=True)
    theta = math.radians(30)
    for a, b in zip(reference, practice):
        a.axis = (math.cos(theta), 0, math.sin(theta))
        b.axis = (math.cos(theta), 0, -math.sin(theta))
    same = pair_evidence(reference[0], practice[0], ComparisonConfig(), False)
    reflected = pair_evidence(reference[0], practice[0], ComparisonConfig(), True)
    assert not same["view"]["accepted"]
    assert reflected["view"]["accepted"]
    result = compare(reference, practice, ComparisonConfig(mirror_mode="mirrored"))
    assert result["scoreAvailable"], result["reason"]
    assert result["overallScore"] == 100
    assert result["alignment"]["mirrorSelection"]["decision"] == "user_specified"


def test_shared_angle_coverage_is_not_subsidized_by_high_confidence():
    config = ComparisonConfig()
    ref, practice = sequence()[0], sequence()[0]
    # The old confidence-coupled threshold could admit <50% angle-weight
    # coverage; coverage must be checked independently of confidence.
    keep = {"left_knee_angle", "right_knee_angle", "left_elbow_angle"}  # 8/20
    practice.values = {k: v for k, v in practice.values.items() if k in keep}
    practice.confidence = {k: 1 for k in keep}
    evidence = pair_evidence(ref, practice, config, False)
    assert evidence["angleWeightCoverage"] == 0.4
    assert not evidence["angleEvidenceAccepted"]
    _, supported = _matrices([ref], [practice], config, False)
    assert not supported[0, 0]


def test_partial_analysis_preserves_unassessed_sections_without_lowering_thresholds():
    reference, practice = generated(7), generated(7)
    for row in practice:
        if row.time > 3:
            row.axis = (0, 0, 1)
    config = ComparisonConfig(mirror_mode="same")
    result = compare(reference, practice, config)
    assert result["alignment"]["supportedAnchorFraction"] < 0.5
    assert result["status"] == "partial", result["reason"]
    assert result["scoreAvailable"]
    assert not result["globalScoreAvailable"]
    assert result["scoreScope"] == "supported_segments"
    assert result["movementScore"] > 99
    assert config.min_coverage == 0.5 and config.viewpoint_agreement == 0.85
    assert any(s["status"] == "supported" and s["angleScore"] > 99 for s in result["comparisonSegments"])
    assert any(s["status"] == "unassessed" for s in result["comparisonSegments"])
    assert all(r["status"] == "unassessed" for r in result["frameComparisons"] if r["practiceTime"] > 3)


def test_scattered_short_support_does_not_make_a_partial_score():
    reference, practice = generated(11), generated(11)
    for s in practice:
        if int(s.time / 0.4) % 3:
            s.axis = (0, 0, 1)
    result = compare(reference, practice, ComparisonConfig(mirror_mode="same"))
    assert not result["scoreAvailable"]
    assert len(result["frameComparisons"]) == len(practice)
    assert result["movementScore"] is None


def test_both_mirror_hypotheses_are_audited_even_when_undetermined():
    reference, practice = sequence(), sequence()
    for a, b in zip(reference, practice):
        for k in a.values:
            if k.endswith("_angle"):
                a.values[k], b.values[k] = 160, 130
    result = compare(reference, practice)
    selection = result["alignment"]["mirrorSelection"]
    assert selection["decision"] == "undetermined"
    assert len(selection["candidates"]) == 2
    assert all("anchorRejections" in c and "objectiveCost" in c for c in selection["candidates"])
    assert len(result["frameComparisons"]) == len(practice)
    assert not result["scoreAvailable"]


@pytest.mark.parametrize("mirrored", [False, True])
def test_vectorized_alignment_and_frame_diagnostics_use_identical_masks(mirrored):
    config = ComparisonConfig()
    reference, practice = sequence()[:8], sequence()[:8]
    practice[2].axis = None
    practice[3].axis = (0, 0, 1)
    practice[4].values = {"left_elbow_angle": 150}
    for a, b in zip(reference[5:], practice[5:]):
        a.axis = (0.9, 0, math.sqrt(0.19))
        b.axis = (0.9, 0, -math.sqrt(0.19))
    _, supported = _matrices(reference, practice, config, mirrored)
    for i, a in enumerate(reference):
        for j, b in enumerate(practice):
            assert supported[i, j] == pair_evidence(a, b, config, mirrored)["accepted"]
