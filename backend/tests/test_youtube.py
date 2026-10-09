from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from yt_dlp.utils import DownloadError, PostProcessingError

from app.config import Settings
from app.main import create_app
from app.video import VideoError
from app.youtube import validate_url, download_video

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.mark.parametrize("url", [URL, "https://youtu.be/jNQXAC9IVRw", "https://www.youtube.com/shorts/jNQXAC9IVRw", "https://m.youtube.com/watch?v=jNQXAC9IVRw&t=1"])
def test_url_forms(url):
    assert validate_url(url) == URL


@pytest.mark.parametrize("body,code", [
    ({}, "invalid_request"), ({"url": None}, "invalid_request"),
    ({"url": 123}, "invalid_request"), ({"url": ""}, "invalid_url"),
    ({"url": "not a URL"}, "invalid_url"),
    ({"url": "https://example.com/watch?v=jNQXAC9IVRw"}, "unsupported_url"),
    ({"url": "https://youtube.com.evil.test/watch?v=jNQXAC9IVRw"}, "unsupported_url"),
    ({"url": "https://youtube.com/playlist?list=abc"}, "unsupported_url"),
    ({"url": URL + "&list=abc"}, "unsupported_url"),
    ({"url": "https://youtube.com/@channel"}, "invalid_url"),
    ({"url": "https://[bad"}, "invalid_url"),
    ({"url": "https://user@youtube.com/watch?v=jNQXAC9IVRw"}, "invalid_url"),
])
def test_bad_requests(body, code, monkeypatch):
    def forbidden(*args):
        pytest.fail("Invalid URL must not invoke the downloader")
    monkeypatch.setattr("app.main.download_video", forbidden)
    with TestClient(create_app()) as client:
        response = client.post("/reference-videos", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


@pytest.fixture
def downloader(monkeypatch):
    instance = MagicMock()
    instance.extract_info.return_value = {"id": "jNQXAC9IVRw", "duration": 2, "_type": "video", "title": "Dance: practice?"}
    factory = MagicMock()
    factory.return_value.__enter__.return_value = instance
    monkeypatch.setattr("app.youtube.YoutubeDL", factory)
    monkeypatch.setattr("app.youtube.shutil.which", lambda name: "C:/ffmpeg/bin/" + name + ".exe")
    return instance, factory


@pytest.mark.parametrize("info,code", [
    ({"duration": 61}, "video_too_long"),
    ({"duration": 2, "is_live": True}, "unsupported_video"),
    ({"live_status": "is_upcoming"}, "unsupported_video"),
    ({"_type": "playlist", "entries": []}, "unsupported_url"),
    (None, "video_unavailable"),
])
def test_preflight_prevents_download(tmp_path, downloader, info, code):
    instance, _ = downloader
    instance.extract_info.return_value = info
    with pytest.raises(VideoError) as caught:
        download_video(URL, tmp_path, Settings())
    assert caught.value.code == code
    instance.process_ie_result.assert_not_called()


def test_download_options_and_mp4(tmp_path, downloader):
    instance, factory = downloader
    instance.process_ie_result.side_effect = lambda *a, **kw: (tmp_path / "input.mp4").write_bytes(b"mp4")
    downloaded = download_video(URL, tmp_path, Settings())
    assert downloaded.path == tmp_path / "input.mp4"
    assert downloaded.title == "Dance: practice?"
    instance.extract_info.assert_called_once_with(URL, download=False)
    instance.process_ie_result.assert_called_once_with(instance.extract_info.return_value, download=True)
    options = factory.call_args.args[0]
    assert options["noplaylist"] is True
    assert options["merge_output_format"] == "mp4"
    assert options["postprocessors"][0]["key"] == "FFmpegVideoRemuxer"
    with pytest.raises(VideoError):
        options["match_filter"]({"duration": 61}, incomplete=False)
    with pytest.raises(VideoError) as caught:
        options["progress_hooks"][0]({"downloaded_bytes": 100000001})
    assert caught.value.code == "upload_too_large"


@pytest.mark.parametrize("phase,error,code,status", [
    ("metadata", DownloadError("Video unavailable private details"), "video_unavailable", 422),
    ("metadata", DownloadError("Sign in to confirm your age private details"), "video_unavailable", 422),
    ("download", DownloadError("network internal details"), "download_failed", 502),
    ("download", PostProcessingError("private details"), "ffmpeg_failed", 502),
    ("download", DownloadError("Postprocessing: ffmpeg private details"), "ffmpeg_failed", 502),
    ("download", RuntimeError("private details"), "processing_failed", 500),
])
def test_failure_cleanup(downloader, monkeypatch, phase, error, code, status):
    instance, factory = downloader
    seen = []
    def fail(*args, **kwargs):
        from pathlib import Path
        directory = Path(factory.call_args.args[0]["outtmpl"]).parent
        seen.append(directory)
        (directory / "partial.part").write_bytes(b"partial")
        (directory / "audio.m4a").write_bytes(b"audio")
        raise error
    getattr(instance, "extract_info" if phase == "metadata" else "process_ie_result").side_effect = fail
    with TestClient(create_app()) as client:
        response = client.post("/reference-videos", json={"url": URL})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private details" not in response.text
    assert not seen[0].exists()


def test_missing_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr("app.youtube.shutil.which", lambda name: None)
    with pytest.raises(VideoError) as caught:
        download_video(URL, tmp_path, Settings())
    assert caught.value.code == "ffmpeg_unavailable"
    assert caught.value.status_code == 503


def test_no_mp4(tmp_path, downloader):
    with pytest.raises(VideoError) as caught:
        download_video(URL, tmp_path, Settings())
    assert caught.value.code == "download_failed"


def test_download_into_existing_pipeline(video, downloader, monkeypatch):
    import app.main as main
    from pathlib import Path
    instance, factory = downloader
    seen = []
    original = main.validate_video
    def write(*args, **kwargs):
        directory = Path(factory.call_args.args[0]["outtmpl"]).parent
        (directory / "input.mp4").write_bytes(video.read_bytes())
        (directory / "leftover.part").write_bytes(b"partial")
    def inspect(path, settings):
        assert path.suffix == ".mp4"
        assert path.read_bytes() == video.read_bytes()
        seen.append(path.parent)
        return original(path, settings)
    instance.process_ie_result.side_effect = write
    monkeypatch.setattr(main, "validate_video", inspect)
    with TestClient(create_app()) as client:
        response = client.post("/reference-videos", json={"url": URL})
    assert response.status_code == 200
    assert response.json()["metadata"]["frame_count"] == 20
    assert not seen[0].exists()


def test_api_persistence_and_unique_names(video, downloader, isolated_downloads):
    from pathlib import Path
    instance, factory = downloader
    def write(*args, **kwargs):
        directory = Path(factory.call_args.args[0]["outtmpl"]).parent
        (directory / "input.mp4").write_bytes(video.read_bytes())
    instance.process_ie_result.side_effect = write
    with TestClient(create_app()) as client:
        responses = [client.post("/reference-videos", json={"url": URL}) for _ in range(2)]
    assert [r.status_code for r in responses] == [200, 200]
    assert [r.json()["filename"] for r in responses] == ["Dance_ practice_.mp4", "Dance_ practice_ (1).mp4"]
    for response in responses:
        body = response.json()
        saved = Path(body["saved_path"])
        assert saved.is_absolute()
        assert saved.parent == isolated_downloads
        assert saved.read_bytes() == video.read_bytes()
        assert body["persisted"] is True


def test_api_save_failure_cleans_temporary_files(video, downloader, isolated_downloads, monkeypatch):
    from pathlib import Path
    instance, factory = downloader
    seen = []
    def write(*args, **kwargs):
        directory = Path(factory.call_args.args[0]["outtmpl"]).parent
        seen.append(directory)
        (directory / "input.mp4").write_bytes(video.read_bytes())
        (directory / "leftover.part").write_bytes(b"partial")
    def broken_copy(original, destination):
        destination.write(b"partial")
        raise OSError("secret disk details")
    instance.process_ie_result.side_effect = write
    monkeypatch.setattr("app.storage.shutil.copyfileobj", broken_copy)
    with TestClient(create_app()) as client:
        response = client.post("/reference-videos", json={"url": URL})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "save_failed"
    assert "secret disk details" not in response.text
    assert "persisted" not in response.json()
    assert not seen[0].exists()
    assert list(isolated_downloads.iterdir()) == []


def test_validation_failure_does_not_save(downloader, isolated_downloads):
    from pathlib import Path
    instance, factory = downloader
    def write(*args, **kwargs):
        directory = Path(factory.call_args.args[0]["outtmpl"]).parent
        (directory / "input.mp4").write_bytes(b"unreadable")
    instance.process_ie_result.side_effect = write
    with TestClient(create_app()) as client:
        response = client.post("/reference-videos", json={"url": URL})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_video"
    assert not isolated_downloads.exists()
