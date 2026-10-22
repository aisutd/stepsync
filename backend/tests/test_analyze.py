"""POST /analyze: the phone app's upload endpoint."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.main import create_app

VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"0" * 2000


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    settings = Settings(data_directory=tmp_path / "data")
    settings.video_directory.mkdir(parents=True)
    with TestClient(create_app(settings)) as client:
        client.settings = settings
        yield client


def practice_file():
    return {"practice": ("practice.mov", VIDEO, "video/quicktime")}


def test_two_uploaded_files(client):
    files = {**practice_file(), "reference": ("ref.mp4", VIDEO, "video/mp4")}
    response = client.post("/analyze", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["steps"] and "sessionId" in body
    saved = main.UPLOAD_DIR / body["sessionId"]
    assert (saved / "reference.mp4").is_file() and (saved / "practice.mov").is_file()


def test_reference_from_youtube_import(client):
    (client.settings.video_directory / "My Dance.mp4").write_bytes(VIDEO)
    response = client.post("/analyze", files=practice_file(), data={"reference_video": "My Dance.mp4"})
    assert response.status_code == 200
    saved = main.UPLOAD_DIR / response.json()["sessionId"]
    assert (saved / "practice.mov").is_file()
    assert not (saved / "reference.mp4").exists()  # the saved YouTube file is used in place


def test_unknown_youtube_filename(client):
    response = client.post("/analyze", files=practice_file(), data={"reference_video": "missing.mp4"})
    assert response.status_code == 404


@pytest.mark.parametrize("name", ["../secret.mp4", "sub/x.mp4", "..", "..\\\\x.mp4", "/etc/passwd"])
def test_rejects_paths(client, tmp_path, name):
    (tmp_path / "secret.mp4").write_bytes(VIDEO)
    response = client.post("/analyze", files=practice_file(), data={"reference_video": name})
    assert response.status_code == 400


def test_needs_exactly_one_reference(client):
    assert client.post("/analyze", files=practice_file()).status_code == 422
    both = {**practice_file(), "reference": ("ref.mp4", VIDEO, "video/mp4")}
    assert client.post("/analyze", files=both, data={"reference_video": "x.mp4"}).status_code == 422


def test_rejects_non_video(client):
    files = {**practice_file(), "reference": ("notes.txt", b"hello", "text/plain")}
    assert client.post("/analyze", files=files).status_code == 415
