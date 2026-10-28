"""Offline tests for the Supabase routes. Supabase itself is faked, so these need no network.
The real RLS checks against Supabase are in test_rls.py (run it by hand, see its docstring)."""
import base64
import csv
import json

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app import supabase_client, supabase_routes
from app.config import Settings
from app.main import create_app
from app.pose_processing import PoseArtifacts


def make_token(sub="user-1", role="authenticated"):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'HS256'})}.{part({'sub': sub, 'role': role})}.sig"


AUTH = {"Authorization": f"Bearer {make_token()}"}
HEADER = ["frame_index", "timestamp_ms", "frame_status", "pose_present", "landmark_id",
          "landmark_name", "x_norm", "y_norm", "z_relative", "visibility", "presence",
          "landmark_reliable", "world_x", "world_y", "world_z", "hip_relative_x_norm",
          "hip_relative_y_norm", "hip_relative_z_norm", "torso_scale_m", "smooth_x_norm",
          "smooth_y_norm", "smooth_z_relative", "smooth_hip_relative_x_norm",
          "smooth_hip_relative_y_norm", "smooth_hip_relative_z_norm"]


@pytest.fixture(autouse=True)
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_test")


def pose_runner(frames=20):  # the `video` fixture has 20 frames
    """Stands in for the real pose extraction: writes a valid 33 landmarks per frame CSV."""
    def run(video_path, output_directory, model_path, timeout_seconds):
        output_directory.mkdir(parents=True, exist_ok=True)
        preview, data = output_directory / "skeleton_preview.mp4", output_directory / "pose_data.csv"
        preview.write_bytes(b"preview")
        with data.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            for i in range(frames):
                ok = i < frames - 1  # last frame has nobody in it
                for lm in range(33):
                    row = [i, i * 100, "OK" if ok else "NO_POSE", 1 if ok else 0, lm, f"lm{lm}"]
                    row += [0.5, 0.5, 0.0, 0.9, 0.9, 1, 0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 0.4,
                            0.5, 0.5, 0.0, 0.0, 0.0, 0.0] if ok else [""] * 19
                    writer.writerow(row)
        return PoseArtifacts(preview, data)
    return run


def client_with(runner=None, **kwargs):
    return TestClient(create_app(Settings.from_env(), runner or pose_runner()), **kwargs)


def test_unknown_table_is_404():
    assert client_with().get("/tables/secrets", headers=AUTH).status_code == 404


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_update_and_delete_need_a_filter(method):
    kwargs = {"json": {"title": "x"}} if method == "patch" else {}
    response = getattr(client_with(), method)("/tables/dances", headers=AUTH, **kwargs)
    assert response.status_code == 400


def test_table_routes_hand_filters_to_the_client_functions(monkeypatch):
    seen = {}
    monkeypatch.setattr(supabase_routes, "select_rows", lambda c, t, f, cols, lim, order: seen.update(
        select=(t, f, cols, lim, order)) or [{"id": "1"}])
    monkeypatch.setattr(supabase_routes, "insert_rows", lambda c, t, rows: seen.update(insert=(t, rows)) or [rows])
    monkeypatch.setattr(supabase_routes, "update_rows", lambda c, t, v, f: seen.update(update=(t, v, f)) or [v])
    monkeypatch.setattr(supabase_routes, "delete_rows", lambda c, t, f: seen.update(delete=(t, f)) or [f])
    client = client_with()
    assert client.get("/tables/dances?id=abc&limit=5&order=created_at&select=id", headers=AUTH).json()["count"] == 1
    assert seen["select"] == ("dances", {"id": "abc"}, "id", 5, "created_at")
    assert client.post("/tables/dances", json={"title": "t"}, headers=AUTH).status_code == 201
    assert seen["insert"] == ("dances", {"title": "t"})
    assert client.patch("/tables/dances?id=abc", json={"title": "n"}, headers=AUTH).json()["count"] == 1
    assert seen["update"] == ("dances", {"title": "n"}, {"id": "abc"})
    assert client.delete("/tables/dances?id=abc", headers=AUTH).json()["count"] == 1
    assert seen["delete"] == ("dances", {"id": "abc"})


@pytest.mark.parametrize("code,status", [("42501", 403), ("PGRST301", 401), ("23503", 409), ("22P02", 400)])
def test_supabase_errors_become_http_errors(monkeypatch, code, status):
    def refuse(*args):
        raise APIError({"code": code, "message": "nope"})
    monkeypatch.setattr(supabase_routes, "insert_rows", refuse)
    response = client_with().post("/tables/dances", json={"title": "t"}, headers=AUTH)
    assert response.status_code == status and response.json()["code"] == code


def test_routes_answer_503_when_supabase_is_not_set_up(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    monkeypatch.delenv("SUPABASE_ANON_KEY")
    assert client_with().get("/tables/dances", headers=AUTH).status_code == 503
    assert client_with().get("/health").status_code == 200  # the rest of the app is fine


def test_keys_that_skip_rls_are_refused(monkeypatch):
    for key in ("sb_secret_abc", make_token(role="service_role")):
        monkeypatch.setenv("SUPABASE_ANON_KEY", key)
        with pytest.raises(RuntimeError, match="skips RLS"):
            supabase_client.check_config()
        with pytest.raises(RuntimeError, match="skips RLS"):
            create_app(Settings.from_env(), pose_runner())  # the server will not even start


def test_user_id_comes_from_the_token():
    assert supabase_client.user_id_from_token(make_token("abc-123")) == "abc-123"


def test_import_needs_a_login(video):
    response = client_with().post("/dances/import", data={"title": "t"},
                                  files={"file": ("a.mp4", video.read_bytes(), "video/mp4")})
    assert response.status_code == 401


def test_import_rejects_other_file_types():
    response = client_with().post("/dances/import", data={"title": "t"}, headers=AUTH,
                                  files={"file": ("a.txt", b"hello", "text/plain")})
    assert response.status_code == 415 and response.json()["error"]["code"] == "unsupported_format"


def import_video(client, video):
    return client.post("/dances/import", data={"title": "My dance"}, headers=AUTH,
                       files={"file": ("a.mp4", video.read_bytes(), "video/mp4")})


def fake_database(monkeypatch):
    log = {"inserts": [], "deletes": []}
    def insert(client, table, rows):
        log["inserts"].append((table, rows))
        return [{**rows, "id": f"{table}-id"}] if isinstance(rows, dict) else rows
    monkeypatch.setattr(supabase_routes, "select_rows", lambda *a, **k: [{"id": "me"}])
    monkeypatch.setattr(supabase_routes, "insert_rows", insert)
    monkeypatch.setattr(supabase_routes, "delete_rows", lambda c, t, f: log["deletes"].append((t, f)) or [f])
    return log


def test_import_saves_dance_step_and_every_keyframe(monkeypatch, video):
    log = fake_database(monkeypatch)
    response = import_video(client_with(), video)
    assert response.status_code == 200
    assert response.json() == {"dance_id": "dances-id", "frames": 20, "keyframes": 20, "ok_frames": 19,
                               "low_confidence_frames": 0, "no_pose_frames": 1}
    (t1, dance), (t2, step), (t3, keyframes) = log["inserts"]
    assert (t1, t2, t3) == ("dances", "steps", "keyframes")
    assert dance["owner_id"] == "user-1" and dance["title"] == "My dance" and dance["status"] == "ready"
    assert step["dance_id"] == "dances-id" and step["end_ms"] == dance["duration_ms"] > 0
    assert [k["frame_order"] for k in keyframes] == list(range(1, 21))
    assert all(k["step_id"] == "steps-id" and len(k["pose_data"]["landmarks"]) == 33 for k in keyframes)
    assert keyframes[0]["pose_data"]["torso_scale_m"] == 0.4
    assert keyframes[0]["pose_data"]["landmarks"][0]["smooth_x_norm"] == 0.5
    assert keyframes[19]["pose_data"]["frame_status"] == "NO_POSE"
    assert not log["deletes"]


def test_a_video_that_lost_most_of_its_frames_is_rejected(monkeypatch, video):
    log = fake_database(monkeypatch)
    response = import_video(client_with(pose_runner(frames=5)), video)
    assert response.status_code == 422 and response.json()["error"]["code"] == "corrupt_video"
    assert not log["inserts"]


def test_a_few_missing_frames_are_fine(monkeypatch, video):
    fake_database(monkeypatch)  # real videos decode a few frames short of what their metadata says
    assert import_video(client_with(pose_runner(frames=19)), video).status_code == 200


def test_a_video_over_the_length_limit_is_rejected(monkeypatch, video):
    log = fake_database(monkeypatch)
    app = create_app(Settings(max_duration_seconds=1), pose_runner())
    response = import_video(TestClient(app), video)
    assert response.status_code == 422 and response.json()["error"]["code"] == "video_too_long"
    assert not log["inserts"]


def test_a_failed_import_removes_the_half_saved_dance(monkeypatch, video):
    log = fake_database(monkeypatch)
    def insert(client, table, rows):
        if table == "keyframes":
            raise APIError({"code": "42501", "message": "RLS"})
        return [{**rows, "id": f"{table}-id"}]
    monkeypatch.setattr(supabase_routes, "insert_rows", insert)
    assert import_video(client_with(), video).status_code == 403
    assert log["deletes"] == [("dances", {"id": "dances-id"})]


def test_get_dance_is_404_when_rls_hides_it(monkeypatch):
    monkeypatch.setattr(supabase_routes, "select_rows", lambda *a, **k: [])
    assert client_with().get("/dances/someone-elses", headers=AUTH).status_code == 404


def test_get_dance_returns_steps_with_keyframes(monkeypatch):
    tables = {"dances": [{"id": "d"}], "steps": [{"id": "s", "step_order": 1}],
              "keyframes": [{"id": "k1"}, {"id": "k2"}]}
    monkeypatch.setattr(supabase_routes, "select_rows", lambda c, t, f=None, *a, **k: [dict(r) for r in tables[t]])
    body = client_with().get("/dances/d", headers=AUTH).json()
    assert body["keyframe_count"] == 2 and body["steps"][0]["keyframes"] == tables["keyframes"]


def test_csv_without_the_smoothing_columns_still_loads(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text("frame_index,timestamp_ms,frame_status,pose_present,landmark_id,landmark_name,x_norm\n"
                    "0,0,OK,1,0,nose,0.5\n")
    frames = supabase_routes.load_frames(path)
    assert frames[0]["landmarks"][0]["x_norm"] == 0.5 and frames[0]["landmarks"][0]["smooth_x_norm"] is None
