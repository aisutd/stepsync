from datetime import timedelta
import json
import uuid

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.comparison import ComparisonConfig, compare, samples_from_frames
from app.session_store import persist_analysis, utc_now
from features import read_pose_csv
from test_features import pose_frames, write_csv


@pytest.fixture
def saved_pair(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr("app.main.UPLOAD_DIR", root)
    session_id = uuid.uuid4().hex
    source = root / session_id
    for name in ("reference", "practice"):
        folder = source / name
        folder.mkdir(parents=True)
        write_csv(folder / "pose_data.csv", pose_frames(knee=160 if name == "reference" else 130))
    config = ComparisonConfig()
    result = compare(*[samples_from_frames(read_pose_csv(source / name / "pose_data.csv"), config, sample=False)
                       for name in ("reference", "practice")], config)
    persist_analysis({"sessionId": session_id, **result}, source, session_id, 604800)

    def forbidden(*args, **kwargs):
        pytest.fail("Recomparison must not upload, validate video, or extract poses")
    monkeypatch.setattr("app.main.save_upload", forbidden)
    monkeypatch.setattr("app.analysis.validate_video", forbidden)
    return TestClient(create_app(pose_runner=forbidden)), source


def snapshot(folder):
    return {str(path.relative_to(folder)): path.read_bytes() for path in folder.rglob("*") if path.is_file()}


def test_recompare_isolated_repeatable_and_uses_existing_math(saved_pair):
    client, source = saved_pair
    before = snapshot(source)
    ids = {source.name}
    for mode in ("same", "mirrored"):
        response = client.post(f"/analyses/{source.name}/recompare", json={"mirrorMode": mode})
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["sessionId"] not in ids
        ids.add(summary["sessionId"])
        assert summary["alignment"]["mirrorSelection"]["requestedMode"] == mode
        assert not summary["alignment"]["mirrorSelection"]["ambiguous"]
        new_folder = source.parent / summary["sessionId"]
        for name in ("reference", "practice"):
            assert (new_folder / name / "pose_data.csv").read_bytes() == (source / name / "pose_data.csv").read_bytes()
        config = ComparisonConfig(mirror_mode=mode)
        expected = compare(*[samples_from_frames(read_pose_csv(source / name / "pose_data.csv"), config, sample=False)
                             for name in ("reference", "practice")], config)
        detailed = client.get(summary["links"]["diagnostics"]).json()
        for key in ("movementScore", "coverage", "scoreAvailable", "globalScoreAvailable", "frameComparisons"):
            assert detailed[key] == expected[key]
        assert client.get(summary["links"]["summary"]).json() == summary
        assert client.post(f"/analyses/{summary['sessionId']}/recompare", json={"mirrorMode": "same"}).status_code == 200
    assert snapshot(source) == before


@pytest.mark.parametrize("body", [{}, {"mirrorMode": "auto"}, {"mirrorMode": "bad"},
    {"mirrorMode": None}, {"mirrorMode": 1}, {"mirrorMode": "same", "extra": True}])
def test_validation(saved_pair, body):
    client, source = saved_pair
    assert client.post(f"/analyses/{source.name}/recompare", json=body).status_code == 422
    assert len(list(source.parent.iterdir())) == 1


def test_missing_unknown_and_expired_sessions(saved_pair):
    client, source = saved_pair
    assert client.post("/analyses/invalid/recompare", json={"mirrorMode": "same"}).status_code == 422
    assert client.post(f"/analyses/{'f' * 32}/recompare", json={"mirrorMode": "same"}).status_code == 404
    manifest = source / "analysis-manifest.json"
    data = json.loads(manifest.read_text())
    data["expiresAt"] = (utc_now() - timedelta(seconds=1)).isoformat()
    manifest.write_text(json.dumps(data))
    before = snapshot(source)
    assert client.post(f"/analyses/{source.name}/recompare", json={"mirrorMode": "same"}).status_code == 410
    assert snapshot(source) == before
    assert len(list(source.parent.iterdir())) == 1


def test_missing_pose_csv_has_explicit_fallback_error(saved_pair):
    client, source = saved_pair
    (source / "practice" / "pose_data.csv").rename(source / "practice" / "legacy.csv")
    before = snapshot(source)
    response = client.post(f"/analyses/{source.name}/recompare", json={"mirrorMode": "same"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pose_data_missing"
    assert snapshot(source) == before
    assert len(list(source.parent.iterdir())) == 1


def test_invalid_pose_data_does_not_publish_a_session(saved_pair):
    client, source = saved_pair
    (source / "practice" / "pose_data.csv").write_text("frame_index\nnot-a-number\n")
    before = snapshot(source)
    assert client.post(f"/analyses/{source.name}/recompare", json={"mirrorMode": "same"}).status_code == 422
    assert snapshot(source) == before
    assert len(list(source.parent.iterdir())) == 1


def test_legacy_session_is_not_modified_to_create_storage_views(saved_pair):
    client, source = saved_pair
    for name in ("analysis-manifest.json", "summary.json", "frames.jsonl"):
        (source / name).rename(source / (name + ".legacy"))
    before = snapshot(source)
    response = client.post(f"/analyses/{source.name}/recompare", json={"mirrorMode": "same"})
    assert response.status_code == 200, response.text
    assert snapshot(source) == before
