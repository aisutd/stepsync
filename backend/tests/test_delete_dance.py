"""DELETE /dances/{id}: removing a dance, everything that points at it, and its files."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.supabase_store import SupabaseConfig, SupabaseStore

AUTH = {"Authorization": "Bearer good-token"}
ME = "user-123"


class FakeSupabase:
    def __init__(self, owner=ME, is_public=False, missing_tables=(), video_shared=False, fail_on=None):
        self.dance = {"id": "d1", "owner_id": owner, "title": "My Dance", "video_path": "My Dance.mp4",
                      "is_public": is_public}
        self.missing = set(missing_tables)
        self.video_shared = video_shared
        self.fail_on = fail_on
        self.deleted = []  # (table, params) in order

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        params = dict(request.url.params)
        if path == "/auth/v1/user":
            ok = request.headers["authorization"] == "Bearer good-token"
            return httpx.Response(200 if ok else 401, json={"id": ME} if ok else {})
        table = path.removeprefix("/rest/v1/")
        if table in self.missing:
            return httpx.Response(404, json={"code": "PGRST205", "message": f"Could not find the table '{table}'"})
        if method == "DELETE":
            if table == self.fail_on:
                return httpx.Response(409, json={"code": "23503", "message": "still referenced"})
            self.deleted.append((table, params))
            return httpx.Response(204)
        if table == "dances":
            if "video_path" in params:  # is the video still used by another dance?
                return httpx.Response(200, json=[{"id": "other"}] if self.video_shared else [])
            return httpx.Response(200, json=[self.dance] if params.get("id") == "eq.d1" else [])
        if table == "steps":
            return httpx.Response(200, json=[
                {"id": "s1", "step_order": 1, "name": "Step 1", "start_ms": 0, "end_ms": 1000, "description": "Fast"},
                {"id": "s2", "step_order": 2, "name": "Step 2", "start_ms": 1000, "end_ms": 2000, "description": "Slow"},
            ])
        if table == "practice_sessions":
            return httpx.Response(200, json=[{"id": "ps1"}, {"id": "ps2"}])
        return httpx.Response(200, json=[])


@pytest.fixture
def files(tmp_path):
    settings = Settings(data_directory=tmp_path / "data")
    settings.video_directory.mkdir(parents=True)
    video = settings.video_directory / "My Dance.mp4"
    video.write_bytes(b"video")
    poses = settings.pose_results_directory / "My Dance"
    poses.mkdir(parents=True)
    (poses / "pose_data.csv").write_text("x")
    return settings, video, poses


def client_for(settings, fake):
    store = None if fake is None else SupabaseStore(
        SupabaseConfig("https://proj.supabase.co", "secret"), httpx.Client(transport=httpx.MockTransport(fake)))
    return TestClient(create_app(settings, supabase_store=store))


def test_deletes_everything_children_first(files):
    settings, video, poses = files
    fake = FakeSupabase()
    with client_for(settings, fake) as client:
        response = client.delete("/dances/d1", headers=AUTH)
    assert response.status_code == 204, response.text
    tables = [table for table, _ in fake.deleted]
    # Practice data first, then keyframes and poses, then steps, the dance last.
    assert tables == ["step_attempts", "step_attempts", "user_dance_progress", "practice_sessions", "saved_dances",
                      "dance_jobs", "keyframes", "pose_frames", "steps", "dances"]
    by_table = dict(fake.deleted)
    assert fake.deleted[0][1] == {"session_id": "in.(ps1,ps2)"}
    assert fake.deleted[1][1] == {"step_id": "in.(s1,s2)"}
    assert by_table["keyframes"] == {"step_id": "in.(s1,s2)"}
    assert by_table["steps"] == {"dance_id": "eq.d1"} and by_table["dances"] == {"id": "eq.d1"}
    assert not video.exists() and not poses.exists(), "the video and pose files go too"


def test_tables_this_project_does_not_have_are_skipped(files):
    settings, video, _ = files
    fake = FakeSupabase(missing_tables={"saved_dances", "dance_jobs", "practice_sessions", "user_dance_progress"})
    with client_for(settings, fake) as client:
        assert client.delete("/dances/d1", headers=AUTH).status_code == 204
    assert [t for t, _ in fake.deleted][-2:] == ["steps", "dances"]


def test_video_kept_when_another_dance_uses_it(files):
    settings, video, poses = files
    with client_for(settings, FakeSupabase(video_shared=True)) as client:
        assert client.delete("/dances/d1", headers=AUTH).status_code == 204
    assert video.exists() and poses.exists()


def test_only_the_owner_can_delete(files):
    settings, video, _ = files
    shared = FakeSupabase(owner="someone-else", is_public=True)
    with client_for(settings, shared) as client:
        response = client.delete("/dances/d1", headers=AUTH)
    assert response.status_code == 403 and "your own" in response.json()["detail"]
    assert not shared.deleted and video.exists()
    hidden = FakeSupabase(owner="someone-else")
    with client_for(settings, hidden) as client:
        assert client.delete("/dances/d1", headers=AUTH).status_code == 404, "private dances stay invisible"
    assert not hidden.deleted


def test_unknown_dance_and_login(files):
    settings, _, _ = files
    with client_for(settings, FakeSupabase()) as client:
        assert client.delete("/dances/nope", headers=AUTH).status_code == 404
        assert client.delete("/dances/d1").status_code == 401
    with client_for(settings, None) as client:
        assert client.delete("/dances/d1", headers=AUTH).status_code == 503


def test_supabase_failure_keeps_the_files(files):
    settings, video, poses = files
    with client_for(settings, FakeSupabase(fail_on="steps")) as client:
        response = client.delete("/dances/d1", headers=AUTH)
    assert response.status_code == 502 and "steps" in response.json()["detail"]
    assert video.exists() and poses.exists(), "nothing on disk is removed unless the dance is gone"
