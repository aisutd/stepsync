import json

import pytest

from features import compute_features, read_pose_csv
from features.supabase_store import load_features_supabase, save_features_supabase
from test_features import BENT_ARM, OUTPUT, STRAIGHT_ARM, row, write_pose_csv


@pytest.fixture
def moving(tmp_path, monkeypatch):
    
    monkeypatch.setattr("features.velocity.FRAME_GAP",1)
    
    path = write_pose_csv(tmp_path / "pose.csv", [
        (0, 0, "OK", STRAIGHT_ARM),
        (1, 500, "OK", BENT_ARM),     # elbow 180 -> 90 degrees in 0.5 s
        (2, 600, "NO_POSE", {}),
        (3, 700, "OK", BENT_ARM),
    ])
    return compute_features("moving", read_pose_csv(path))


def test_angle_velocity_degrees_per_second(moving):
    r = row(moving, 1, "left_elbow_velocity")
    assert r["value"] == pytest.approx(-180, abs=1)  # closing at 180 degrees/s
    assert r["units"] == "degrees/s" and r["timestamp_ms"] == 500


def test_keypoint_speed_meters_per_second(moving):
    # Wrist moves from (0, 0.6, 0) to (0, 0.3, -0.25): ~0.39 m in 0.5 s.
    assert row(moving, 1, "left_wrist_speed")["value"] == pytest.approx(0.781, abs=0.01)


def test_velocity_missing_not_zero(moving):
    assert row(moving, 0, "left_elbow_velocity")["missing_reason"] == "first_frame"
    assert row(moving, 2, "left_elbow_velocity")["value"] is None
    after_gap = row(moving, 3, "left_elbow_velocity")
    assert after_gap["value"] is None and after_gap["status"] == "missing"


def test_real_reze_velocities_present():
    doc = compute_features("reze", read_pose_csv(OUTPUT / "reze_pose_data.csv"))
    ok = [r for r in doc["rows"] if r["status"] == "ok" and r["units"] == "m/s"]
    assert ok and all(r["value"] >= 0 for r in ok)


class FakeSupabase:
    """Stands in for urllib so the REST calls can be checked without a network."""

    def __init__(self):
        self.table, self.calls = [], []

    def urlopen(self, request, timeout):
        self.calls.append((request.method, request.full_url))
        assert request.headers["Apikey"] == "test-key"
        body = b""
        if request.method == "DELETE":
            self.table = [r for r in self.table if r["video_id"] != "moving"]
        elif request.method == "POST":
            self.table.extend(json.loads(request.data))
        elif request.method == "GET":
            offset = int(request.full_url.split("offset=")[1])
            body = json.dumps(self.table[offset:offset + 1000]).encode()
        return FakeResponse(body)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_supabase_save_then_load_matches(moving, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)
    settings = {"url": "https://example.supabase.co", "key": "test-key"}

    assert save_features_supabase(moving, **settings) == len(moving["rows"])
    save_features_supabase(moving, **settings)  # re-saving replaces, not duplicates
    loaded = load_features_supabase("moving", **settings)

    assert len(loaded) == len(moving["rows"])
    assert loaded[0]["video_id"] == "moving"
    assert {(r["frame_index"], r["feature"], r["value"], r["timestamp_ms"]) for r in loaded} == \
        {(r["frame_index"], r["feature"], r["value"], r["timestamp_ms"]) for r in moving["rows"]}
    assert fake.calls[0][0] == "DELETE" and "video_id=eq.moving" in fake.calls[0][1]


def test_supabase_needs_settings(moving, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        save_features_supabase(moving)
