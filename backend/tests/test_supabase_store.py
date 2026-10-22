"""Saving keypoints and motion features to Supabase (no real network)."""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pose_processing import PoseArtifacts
from app.supabase_store import (FRAME_BATCH, SupabaseConfig, SupabaseError, SupabaseStore,
                                add_motion_features, load_pose_frames)

SAMPLE_CSV = Path(__file__).resolve().parents[1] / "output" / "reze_pose_data.csv"
needs_sample = pytest.mark.skipif(not SAMPLE_CSV.is_file(), reason="sample pose CSV not in repo")


@needs_sample
def test_groups_csv_into_frames():
    frames = load_pose_frames(SAMPLE_CSV)
    assert len(frames) == 616
    assert [f["frame_index"] for f in frames] == sorted(f["frame_index"] for f in frames)
    with_pose = [f for f in frames if f["pose_present"]]
    assert len(with_pose) == 487
    assert all(len(f["keypoints"]) == 33 for f in with_pose)
    assert all(f["keypoints"] == {} for f in frames if not f["pose_present"])
    nose = with_pose[0]["keypoints"]["nose"]
    assert set(nose) >= {"x", "y", "z", "visibility", "reliable", "wx", "hx"}


@needs_sample
def test_motion_features():
    frames = load_pose_frames(SAMPLE_CSV)
    summary = add_motion_features(frames)
    assert summary["frames_with_pose"] == 487
    assert summary["pose_coverage"] == pytest.approx(487 / 616, abs=1e-3)
    assert 0 < summary["avg_motion_energy"] <= summary["peak_motion_energy"]
    angles = [a for f in frames for a in f["joint_angles"].values() if a is not None]
    assert angles and all(0 <= a <= 180 for a in angles)
    speeds = [k["speed"] for f in frames for k in f["keypoints"].values() if "speed" in k]
    assert speeds and min(speeds) >= 0
    # Frames without a dancer carry no features.
    assert all(f["motion_energy"] is None and f["joint_angles"] == {} for f in frames if not f["pose_present"])
    json.dumps(frames, allow_nan=False)  # must be valid JSON for Supabase


def test_csv_without_landmark_columns(tmp_path):
    path = tmp_path / "pose.csv"
    path.write_text("frame_index,pose_present\n0,0\n")
    frames = load_pose_frames(path)
    assert frames == [{"frame_index": 0, "timestamp_ms": 0, "pose_present": False, "torso_scale_m": None, "keypoints": {}}]
    assert add_motion_features(frames)["frames_with_pose"] == 0


class FakeSupabase:
    """Records requests and answers like Supabase's REST API."""

    def __init__(self, frames_status=201, video_status=201):
        self.requests = []
        self.frames_status, self.video_status = frames_status, video_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/auth/v1/user":
            ok = request.headers["authorization"] == "Bearer good-token"
            return httpx.Response(200 if ok else 401, json={"id": "user-123"} if ok else {})
        if request.method == "POST" and path == "/rest/v1/dance_videos":
            return httpx.Response(self.video_status, json=[{"id": "video-1"}] if self.video_status < 300 else {"code": "PGRST205"})
        if request.method == "POST" and path == "/rest/v1/pose_frames":
            return httpx.Response(self.frames_status, json={} if self.frames_status < 300 else {"message": "boom"})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)


def make_store(fake):
    return SupabaseStore(SupabaseConfig("https://proj.supabase.co", "secret"), httpx.Client(transport=httpx.MockTransport(fake)))


def frames_fixture(count):
    return [{"frame_index": i, "timestamp_ms": i * 33, "pose_present": False, "torso_scale_m": None,
             "keypoints": {}, "joint_angles": {}, "motion_energy": None} for i in range(count)]


def test_save_reference_batches_frames():
    fake = FakeSupabase()
    video_id = make_store(fake).save_reference({"title": "x"}, frames_fixture(FRAME_BATCH * 2 + 5))
    assert video_id == "video-1"
    posts = [r for r in fake.requests if r.url.path == "/rest/v1/pose_frames"]
    assert [len(json.loads(r.content)) for r in posts] == [FRAME_BATCH, FRAME_BATCH, 5]
    assert all(json.loads(r.content)[0]["video_id"] == "video-1" for r in posts)
    assert all(r.headers["apikey"] == "secret" for r in fake.requests)


def test_failed_frames_insert_removes_video_row():
    fake = FakeSupabase(frames_status=500)
    with pytest.raises(SupabaseError):
        make_store(fake).save_reference({"title": "x"}, frames_fixture(3))
    deletes = [r for r in fake.requests if r.method == "DELETE"]
    assert len(deletes) == 1 and deletes[0].url.params["id"] == "eq.video-1"


def test_missing_tables_hint():
    with pytest.raises(SupabaseError, match="migrations"):
        make_store(FakeSupabase(video_status=404)).save_reference({"title": "x"}, [])


def test_user_lookup():
    store = make_store(FakeSupabase())
    assert store.user_id_for_token("good-token") == "user-123"
    assert store.user_id_for_token("bad-token") is None


def test_config_from_env(monkeypatch):
    assert SupabaseConfig.from_env() is None
    monkeypatch.setenv("STEPSYNC_SUPABASE_URL", "https://proj.supabase.co/")
    monkeypatch.setenv("STEPSYNC_SUPABASE_SECRET_KEY", "secret")
    assert SupabaseConfig.from_env() == SupabaseConfig("https://proj.supabase.co", "secret")


# --- through the endpoint ---------------------------------------------------

def import_short(tmp_path, store, video, headers=None, pose_csv=SAMPLE_CSV):
    def download(url, directory, settings):
        from app.youtube import DownloadedVideo
        path = directory / "input.mp4"
        path.write_bytes(video.read_bytes())
        return DownloadedVideo(path, "Dance Short")

    def pose_runner(video_path, output_directory, model_path, timeout_seconds):
        output_directory.mkdir(parents=True, exist_ok=True)
        data = output_directory / "pose_data.csv"
        shutil.copy(pose_csv, data)
        preview = output_directory / "skeleton_preview.mp4"
        preview.write_bytes(b"preview")
        return PoseArtifacts(preview, data)

    app = create_app(Settings(data_directory=tmp_path / "data"), pose_runner=pose_runner, supabase_store=store)
    with patch("app.main.download_video", download), TestClient(app) as client:
        return client.post("/reference-videos", json={"url": "https://youtube.com/shorts/jNQXAC9IVRw"}, headers=headers or {})


@needs_sample
def test_endpoint_saves_to_supabase(tmp_path, video):
    fake = FakeSupabase()
    response = import_short(tmp_path, make_store(fake), video, headers={"Authorization": "Bearer good-token"})
    body = response.json()
    assert response.status_code == 200, body
    assert body["supabase_status"] == "saved"
    assert body["supabase_video_id"] == "video-1"
    assert body["frames_saved"] == 616
    row = json.loads(next(r for r in fake.requests if r.url.path == "/rest/v1/dance_videos").content)
    assert row["user_id"] == "user-123"
    assert row["youtube_id"] == "jNQXAC9IVRw"
    assert row["title"] == "Dance Short"
    assert row["frames_with_pose"] == 487


@needs_sample
def test_endpoint_reports_supabase_failure_but_keeps_video(tmp_path, video):
    response = import_short(tmp_path, make_store(FakeSupabase(video_status=404)), video)
    body = response.json()
    assert response.status_code == 200
    assert body["persisted"] is True
    assert body["supabase_status"] == "failed"
    assert "migrations" in body["supabase_error"]


def test_endpoint_without_supabase(tmp_path, video):
    csv = tmp_path / "pose.csv"
    csv.write_text("frame_index,pose_present\n0,0\n")
    response = import_short(tmp_path, None, video, pose_csv=csv)
    assert response.json()["supabase_status"] == "not_configured"
