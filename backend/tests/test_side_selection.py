import math

import pytest
from fastapi.testclient import TestClient

from app.comparison import ComparisonConfig, compare
from app.coaching_evidence import build_context
from app.main import create_app
from app.pose_processing import PoseArtifacts
from app.session_store import persist_analysis
from test_comparison import sequence
from test_features import pose_frames, write_csv


def dance(mirrored=False, fps=10, duration=6, error=0):
    rows = sequence(fps=fps, duration=duration, mirror=mirrored)
    for index, row in enumerate(rows):
        row.frame_index = index
        part = "right_knee_angle" if mirrored else "left_knee_angle"
        row.values[part] -= error
    return rows


@pytest.mark.parametrize("mirrored", [False, True])
def test_auto_chooses_proven_mapping_and_equals_one_manual_result(mirrored):
    reference, practice = dance(), dance(mirrored=mirrored, error=10)
    auto = compare(reference, practice)
    manual = compare(reference, practice, ComparisonConfig(mirror_mode="mirrored" if mirrored else "same"))
    selection = auto["alignment"]["mirrorSelection"]
    assert selection["decision"] == "selected" and selection["ambiguous"] is False
    assert selection["selectedMapping"] == ("mirrored" if mirrored else "same")
    for key in ("frameComparisons", "coverage", "steps", "movementScore", "globalScoreAvailable"):
        assert auto[key] == manual[key], key
    assert selection["selectionEvidence"]["windowConsistency"] >= .75
    assert selection["selectionEvidence"]["informativeWindows"] >= 3


@pytest.mark.parametrize("mirrored", [False, True])
def test_manual_mapping_preserves_practice_side_labels_and_measured_angles(mirrored):
    reference, practice = dance(), dance(mirrored=mirrored)
    result = compare(reference, practice, ComparisonConfig(mirror_mode="mirrored" if mirrored else "same"))
    for frame in result["frameComparisons"]:
        if frame["status"] != "compared":
            continue
        for joint in frame["joints"]:
            expected_side = ("right_" + joint["bodyPart"][5:] if joint["bodyPart"].startswith("left_") else "left_" + joint["bodyPart"][6:]) if mirrored else joint["bodyPart"]
            assert joint["referenceBodyPart"] == expected_side
            if joint["expected"] is not None:
                assert joint["expected"] == reference[frame["referenceFrameIndex"]].values[joint["referenceBodyPart"] + "_angle"]
                assert joint["observed"] == practice[frame["practiceFrameIndex"]].values[joint["bodyPart"] + "_angle"]


@pytest.mark.parametrize("mirrored", [False, True])
def test_fps_speed_pose_gaps_and_imperfect_execution(mirrored):
    reference, practice = dance(), dance(mirrored=mirrored, fps=24, duration=7.2, error=7)
    for row in practice:
        if 3 <= row.time <= 3.25:
            row.values, row.confidence = {}, {}
    result = compare(reference, practice)
    assert result["alignment"]["mirrorSelection"]["selectedMapping"] == ("mirrored" if mirrored else "same")
    assert result["scoreAvailable"]
    assert all(f["status"] == "unassessed" for f in result["frameComparisons"] if 3 <= f["practiceTime"] <= 3.25)


def test_symmetric_dynamic_motion_is_not_evidence_for_either_mapping():
    reference, practice = dance(), dance()
    for row in reference + practice:
        for name in list(row.values):
            if name.startswith("right_") and "left_" + name[6:] in row.values:
                row.values[name] = row.values["left_" + name[6:]]
    result = compare(reference, practice)
    selection = result["alignment"]["mirrorSelection"]
    assert selection["ambiguous"] and selection["selectedMapping"] is None
    assert not result["globalScoreAvailable"]


def test_conflicting_side_conventions_never_get_spliced_together():
    practice = dance()
    mirrored = dance(mirrored=True)
    for index, row in enumerate(practice):
        if row.time >= 3:
            row.values = mirrored[index].values
    result = compare(dance(), practice)
    assert result["alignment"]["mirrorSelection"]["ambiguous"]
    convention = result["alignment"]["mirrored"]
    for frame in result["frameComparisons"]:
        for joint in frame["joints"]:
            assert (joint["bodyPart"] != joint["referenceBodyPart"]) is convention


def test_unreliable_discriminative_joints_cannot_choose_a_mapping():
    practice = dance(mirrored=True)
    for row in practice:
        row.confidence = {key: .95 if "shoulder" in key else .1 for key in row.confidence}
    result = compare(dance(), practice)
    assert not result["scoreAvailable"]
    assert result["alignment"]["mirrorSelection"]["selectedMapping"] is None


def test_selector_does_not_choose_using_objective_or_coverage_alone(monkeypatch):
    import app.comparison as module
    original = module.align
    def misleading(reference, practice, config, mirrored):
        path, cost, diagnostics = original(reference, practice, config, mirrored)
        diagnostics["objectiveCost"] = 0 if mirrored else 1
        diagnostics["supportedAnchorFraction"] = 1 if mirrored else .51
        return path, cost, diagnostics
    monkeypatch.setattr(module, "align", misleading)
    result = compare(dance(), dance())
    assert result["alignment"]["mirrorSelection"]["selectedMapping"] == "same"
    assert result["movementScore"] == 100


def test_two_alignments_from_one_shared_feature_pair(monkeypatch):
    import app.comparison as module
    original = module.align
    calls = []
    def counted(reference, practice, config, mirrored):
        calls.append((id(reference), id(practice), mirrored))
        return original(reference, practice, config, mirrored)
    monkeypatch.setattr(module, "align", counted)
    compare(dance(), dance())
    assert len(calls) == 2 and {c[2] for c in calls} == {False, True}
    assert calls[0][:2] == calls[1][:2]


def test_unsupported_temporal_brackets_cannot_vote_for_a_mapping(monkeypatch):
    import app.comparison as module
    original = module.align
    def unsupported(reference, practice, config, mirrored):
        path, cost, diagnostics = original(reference, practice, config, mirrored)
        for anchor in diagnostics.get("anchorDiagnostics", []):
            if anchor["practiceTime"] > .4:
                anchor["accepted"] = False
        return path, cost, diagnostics
    monkeypatch.setattr(module, "align", unsupported)
    result = compare(dance(), dance())
    assert result["alignment"]["mirrorSelection"]["selectedMapping"] is None
    assert result["alignment"]["mirrorSelection"]["ambiguous"]


def test_upload_auto_extracts_each_video_once(video, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.UPLOAD_DIR", tmp_path / "uploads")
    calls = []
    def runner(path, directory, *args):
        calls.append(path.stem)
        directory.mkdir(parents=True)
        return PoseArtifacts(directory / "preview.mp4", write_csv(directory / "pose.csv", pose_frames()))
    client = TestClient(create_app(pose_runner=runner))
    response = client.post("/analyze", files={name: ("v.mp4", video.read_bytes(), "video/mp4") for name in ("reference", "practice")})
    assert response.status_code == 200, response.text
    assert calls == ["reference", "practice"]
    selection = response.json()["alignment"]["mirrorSelection"]
    assert selection["ambiguous"] and selection["selectedMapping"] is None
    assert "selectionEvidence" in selection and "windows" not in selection["selectionEvidence"]


def test_coaching_uses_only_selected_mapping_measurements(tmp_path):
    result = compare(dance(), dance(mirrored=True, error=10))
    session = "d" * 32
    summary = persist_analysis(result, tmp_path, session, 604800)
    assert summary["alignment"]["mirrorSelection"]["selectedMapping"] == "mirrored"
    context = build_context(tmp_path, summary, "knees at 2 seconds")
    for fact in context["facts"]:
        if fact["id"].startswith("frame:"):
            measurements = fact["measurements"]
            assert measurements["bodyPart"] != measurements["referenceBodyPart"]


@pytest.mark.parametrize("kwargs", [{"mirror_min_windows": 1}, {"mirror_window_seconds": 0}, {"mirror_margin_degrees": math.nan}])
def test_invalid_selector_configuration(kwargs):
    with pytest.raises(ValueError):
        ComparisonConfig(**kwargs)
