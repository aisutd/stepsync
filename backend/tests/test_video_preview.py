"""GET /videos/{filename}: streaming saved reference videos to the app."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

CONTENT = bytes(range(256)) * 40  # 10,240 bytes


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_directory=tmp_path / "data")
    settings.video_directory.mkdir(parents=True)
    (settings.video_directory / "Gnarly Dance Cover (5).mp4").write_bytes(CONTENT)
    (tmp_path / "data" / "secret.txt").write_text("not a video")
    with TestClient(create_app(settings, supabase_store=None)) as client:
        yield client


def test_serves_saved_video(client):
    response = client.get("/videos/Gnarly%20Dance%20Cover%20(5).mp4")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == CONTENT


def test_supports_range_requests_for_ios(client):
    response = client.get("/videos/Gnarly%20Dance%20Cover%20(5).mp4", headers={"Range": "bytes=0-1"})
    assert response.status_code == 206
    assert response.content == CONTENT[:2]
    assert response.headers["content-range"] == f"bytes 0-1/{len(CONTENT)}"
    assert response.headers.get("accept-ranges") == "bytes"


def test_unknown_video_is_404(client):
    assert client.get("/videos/missing.mp4").status_code == 404


@pytest.mark.parametrize("name", ["..%2Fsecret.txt", "..", "%2Fetc%2Fpasswd", "..%5Csecret.txt"])
def test_never_serves_files_outside_the_videos_folder(client, name):
    assert client.get(f"/videos/{name}").status_code in (400, 404)
