import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings
from app.comparison import ComparisonConfig
from app.pose_processing import PoseArtifacts
from app.video import VideoError
from test_features import pose_frames, write_csv


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.UPLOAD_DIR", tmp_path / "uploads")
    def runner(path, directory, model, timeout):
        directory.mkdir(parents=True)
        data = write_csv(directory / "pose.csv", pose_frames(knee=130 if path.stem == "practice" else 160))
        preview = directory / "preview.mp4"
        preview.write_bytes(b"preview")
        return PoseArtifacts(preview, data)
    # These stationary poses test numerical/API contracts, not automatic
    # choreography-side inference, for which they contain no motion evidence.
    return TestClient(create_app(Settings(data_directory=tmp_path), pose_runner=runner,
                                 comparison_config=ComparisonConfig(mirror_mode="same")))


def test_analyze_response_contract_and_artifacts(api, video, tmp_path):
    response = api.post("/analyze", files={name: ("test.mp4", video.read_bytes(), "video/mp4")
                                         for name in ("reference", "practice")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["scoreAvailable"]
    assert 0 <= result["overallScore"] <= 100
    assert result["sessionId"]
    assert "frameComparisons" not in result
    assert "diagnostics" not in result
    detailed = api.get(result["links"]["diagnostics"]).json()
    assert len(detailed["frameComparisons"]) == len(pose_frames())
    frame = detailed["frameComparisons"][15]
    assert frame["practiceFrameIndex"] == 15
    assert frame["practiceTime"] == 0.5
    knee = next(j for j in frame["joints"] if j["bodyPart"] == "left_knee")
    assert knee["difference"] == pytest.approx(30)
    assert knee["status"] == "different"
    assert result["movementScore"] == result["overallScore"]
    assert result["assessment"] == {"totalFrames": len(detailed["frameComparisons"]),
        "assessedFrames": sum(r["status"] == "compared" for r in detailed["frameComparisons"]),
        "unassessedFrames": sum(r["status"] == "unassessed" for r in detailed["frameComparisons"])}
    step = next(s for s in result["steps"] if s["label"] == "Left Knee")
    assert {"id", "label", "start", "end", "score", "feedback"} <= step.keys()
    assert step["evidence"]["expected"] == pytest.approx(160, abs=0.1)
    assert step["evidence"]["observed"] == pytest.approx(130, abs=0.1)
    folder = tmp_path / "uploads" / result["sessionId"]
    assert json.loads((folder / "comparison.json").read_text())["sessionId"] == result["sessionId"]
    assert (folder / "reference_features.json").is_file()


def test_analyze_rejects_invalid_video(api):
    response = api.post("/analyze", files={name: ("test.mp4", b"invalid", "video/mp4")
                                         for name in ("reference", "practice")})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_missing_uploads(api):
    response = api.post("/analyze")
    assert response.status_code == 422
    assert "multipart" in response.json()["error"]["message"]


def test_empty_upload(api):
    response = api.post("/analyze", files={"reference": ("r.mp4", b"", "video/mp4"),
                                         "practice": ("p.mp4", b"x", "video/mp4")})
    assert response.status_code == 400


def test_pose_failure_is_not_a_movement_score(video, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.UPLOAD_DIR", tmp_path / "uploads")
    def failed(*args):
        raise VideoError("pose_processing_failed", "Pose extraction failed", 500)
    client = TestClient(create_app(pose_runner=failed))
    response = client.post("/analyze", files={name: ("v.mp4", video.read_bytes(), "video/mp4")
                                             for name in ("reference", "practice")})
    assert response.status_code == 500
    assert "overallScore" not in response.json()


def test_no_person_response(video, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.UPLOAD_DIR", tmp_path / "uploads")
    def no_pose(path, directory, *args):
        directory.mkdir(parents=True)
        data = directory / "pose.csv"
        data.write_text("frame_index,timestamp_ms,frame_status,pose_present\n" +
                        "\n".join(f"{i},{i * 100},NO_POSE,0" for i in range(20)))
        return PoseArtifacts(directory / "preview.mp4", data)
    client = TestClient(create_app(pose_runner=no_pose))
    response = client.post("/analyze", files={name: ("v.mp4", video.read_bytes(), "video/mp4")
                                             for name in ("reference", "practice")})
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert not response.json()["scoreAvailable"]
    assert response.json()["movementScore"] is None
    assert response.json()["reason"]
    assert response.json()["steps"] == []
    detailed = client.get(response.json()["links"]["diagnostics"]).json()
    assert len(detailed["frameComparisons"]) == 20
    assert all(r["status"] == "unassessed" and r["reason"] for r in detailed["frameComparisons"])
    assert detailed["diagnostics"]["practice"]["frames"] == 20
    assert response.json()["assessment"] == {"totalFrames": 20, "assessedFrames": 0, "unassessedFrames": 20}


def test_invalid_extractor_timestamps_have_clear_api_error(video, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.UPLOAD_DIR", tmp_path / "uploads")
    def invalid(path, directory, *args):
        directory.mkdir(parents=True)
        frames = pose_frames()
        frames[1].timestamp_ms = frames[0].timestamp_ms
        return PoseArtifacts(directory / "preview.mp4", write_csv(directory / "pose.csv", frames))
    client = TestClient(create_app(pose_runner=invalid))
    response = client.post("/analyze", files={name: ("v.mp4", video.read_bytes(), "video/mp4")
                                             for name in ("reference", "practice")})
    assert response.status_code == 422
    assert "not scored" in response.json()["detail"]


def test_optional_mirror_mode_is_additive_and_validated(api, video):
    files = {name: ("v.mp4", video.read_bytes(), "video/mp4") for name in ("reference", "practice")}
    response = api.post("/analyze", files=files, data={"mirror_mode": "same"})
    assert response.status_code == 200, response.text
    selection = response.json()["alignment"]["mirrorSelection"]
    assert selection["requestedMode"] == "same"
    assert selection["decision"] == "user_specified"
    assert "diagnostics" not in response.json()
    assert "diagnostics" in api.get(response.json()["links"]["diagnostics"]).json()
    invalid = api.post("/analyze", files=files, data={"mirror_mode": "unknown"})
    assert invalid.status_code == 422


def test_completed_global_score_does_not_imply_complete_frame_assessment(video, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.UPLOAD_DIR", tmp_path / "uploads")
    def runner(path, directory, *args):
        directory.mkdir(parents=True)
        frames = pose_frames(fps=10, seconds=1.9)
        if path.stem == "practice":
            for frame in frames[5:8]:
                frame.pose_present = False
                frame.frame_status = "NO_POSE"
        return PoseArtifacts(directory / "preview.mp4", write_csv(directory / "pose.csv", frames))
    client = TestClient(create_app(pose_runner=runner))
    response = client.post("/analyze", data={"mirror_mode": "same"}, files={
        name: ("v.mp4", video.read_bytes(), "video/mp4") for name in ("reference", "practice")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed"
    assert result["globalScoreAvailable"] is True
    assert result["scoreScope"] == "aligned_observations"
    assert 0 < result["coverage"]["assessed"] < 1
    counts = result["assessment"]
    assert counts["totalFrames"] == 20
    assert counts["assessedFrames"] + counts["unassessedFrames"] == 20
    assert counts["unassessedFrames"] >= 3
    for frame in client.get(result["links"]["diagnostics"]).json()["frameComparisons"]:
        if frame["status"] == "unassessed":
            assert all(j["difference"] is None and j["status"] == "unassessed" for j in frame["joints"])
