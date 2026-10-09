from dataclasses import replace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.handoff import ProcessingState, pose_extractor_placeholder
from app.main import create_app
from app.video import (VideoError, decoded_frames, prepared_frames, read_metadata,
                       resize_frame, validate_video)


def upload(content, name="sample.mp4", settings=None):
    from unittest.mock import patch
    def download(url, directory, settings):
        path = directory / "input.mp4"
        path.write_bytes(content)
        from app.youtube import DownloadedVideo
        return DownloadedVideo(path, "Sample video")
    with patch("app.main.download_video", download), TestClient(create_app(settings or Settings())) as client:
        return client.post("/reference-videos", json={"url": "https://youtu.be/jNQXAC9IVRw"})


def test_valid_youtube_intake(video):
    response = upload(video.read_bytes())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["persisted"] is True
    from pathlib import Path
    assert Path(body["saved_path"]).read_bytes() == video.read_bytes()
    assert body["pose_processing"] == "not_connected"
    assert body["metadata"]["frame_count"] == 20
    assert body["size_bytes"] == video.stat().st_size
    assert body["source_url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.mark.parametrize("content,code", [(b"", "empty_file"), (b"not a video", "unreadable_video")])
def test_invalid_downloaded_video(content, code):
    response = upload(content)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_oversized_download(video):
    response = upload(video.read_bytes(), settings=Settings(max_upload_bytes=10))
    assert response.status_code == 413


def test_over_duration_download(video):
    response = upload(video.read_bytes(), settings=Settings(max_duration_seconds=1))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "video_too_long"


def test_metadata(video):
    metadata = validate_video(video, Settings())
    assert metadata.width == 160
    assert metadata.height == 120
    assert metadata.fps == pytest.approx(10)
    assert metadata.frame_count == 20
    assert metadata.duration_seconds == pytest.approx(2)


@pytest.mark.parametrize("shape,expected", [
    ((1080, 1920, 3), (720, 1280, 3)),
    ((1920, 1080, 3), (720, 405, 3)),
    ((120, 160, 3), (120, 160, 3)),
])
def test_resize(shape, expected):
    resized = resize_frame(np.zeros(shape, dtype=np.uint8), 1280, 720)
    assert resized.shape == expected


def test_sampling_preserves_source_time_and_rgb(video):
    metadata = read_metadata(video)
    frames = list(prepared_frames(video, metadata, Settings(target_fps=5)))
    assert [f.source_frame_index for f in frames] == list(range(0, 20, 2))
    assert [f.timestamp_seconds for f in frames] == pytest.approx([i / 10 for i in range(0, 20, 2)])
    assert frames[0].image_rgb.dtype == np.uint8
    assert frames[0].image_rgb[50, 50, 0] > 180
    assert frames[0].image_rgb[50, 50, 2] < 20


def test_sampling_does_not_duplicate_slow_source(video):
    frames = list(prepared_frames(video, read_metadata(video), Settings(target_fps=30)))
    assert len(frames) == 20
    assert len({f.source_frame_index for f in frames}) == 20


def test_sampling_irregular_timestamps(video, monkeypatch):
    import app.video as video_module
    timestamps = [0.0, 0.01, 0.04, 0.095, 0.101, 0.2]
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    monkeypatch.setattr(video_module, "decoded_frames", lambda path, metadata:
                        iter((i, timestamp, image) for i, timestamp in enumerate(timestamps)))
    frames = list(prepared_frames(video, read_metadata(video), Settings(target_fps=10)))
    assert [f.source_frame_index for f in frames] == [0, 4, 5]
    assert [f.timestamp_seconds for f in frames] == [0.0, 0.101, 0.2]


def test_detectable_partial_decode(video):
    metadata = replace(read_metadata(video), frame_count=21)
    with pytest.raises(VideoError, match="incomplete"):
        list(decoded_frames(video, metadata))


def test_rotation_before_resizing(video):
    metadata = replace(read_metadata(video), rotation_degrees=90)
    frames = list(prepared_frames(video, metadata, Settings()))
    assert frames[0].image_rgb.shape == (160, 120, 3)


def test_missing_file():
    with TestClient(create_app()) as client:
        response = client.post("/reference-videos")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_internal_error_and_temporary_cleanup(video, monkeypatch):
    import app.main as main
    seen_paths = []

    def broken(path, settings):
        seen_paths.append(path)
        assert path.exists()
        raise RuntimeError("private details")

    monkeypatch.setattr(main, "validate_video", broken)
    response = upload(video.read_bytes())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "processing_failed"
    assert "private details" not in response.text
    assert not seen_paths[0].exists()


def test_successful_temporary_cleanup(video, monkeypatch):
    import app.main as main
    original = main.validate_video
    seen_paths = []

    def inspect(path, settings):
        seen_paths.append(path)
        return original(path, settings)

    monkeypatch.setattr(main, "validate_video", inspect)
    assert upload(video.read_bytes()).status_code == 200
    assert not seen_paths[0].exists()


def test_handoff_is_explicitly_unimplemented(video):
    assert {s.value for s in ProcessingState} == {"uploaded", "processing", "completed", "failed"}
    with pytest.raises(NotImplementedError, match="not connected"):
        pose_extractor_placeholder([], read_metadata(video))


def test_environment_settings(monkeypatch):
    monkeypatch.setenv("STEPSYNC_TARGET_FPS", "12")
    monkeypatch.setenv("STEPSYNC_MAX_UPLOAD_BYTES", "500")
    assert Settings.from_env().target_fps == 12
    assert Settings.from_env().max_upload_bytes == 500


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_settings(value):
    with pytest.raises(ValueError):
        Settings(target_fps=value)


def test_real_mov_validation(tmp_path):
    path = tmp_path / "sample.mov"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    assert writer.isOpened()
    try:
        for _ in range(10):
            writer.write(np.zeros((120, 160, 3), dtype=np.uint8))
    finally:
        writer.release()
    assert validate_video(path, Settings()).frame_count == 10


def test_truncated_video(video, tmp_path):
    path = tmp_path / "truncated.mp4"
    content = video.read_bytes()
    path.write_bytes(content[:len(content) // 2])
    with pytest.raises(VideoError) as caught:
        validate_video(path, Settings())
    assert caught.value.code in {"unreadable_video", "corrupt_video", "invalid_metadata"}


def test_docs_and_openapi_do_not_run_video_intake(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Documentation requests must not download, validate, or save videos")
    for name in ("download_video", "validate_video", "save_video"):
        monkeypatch.setattr("app.main." + name, forbidden)
    with TestClient(create_app()) as client:
        docs = client.get("/docs")
        schema = client.get("/openapi.json")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert schema.status_code == 200
    assert "/reference-videos" in schema.json()["paths"]
    assert "saved_path" in schema.json()["components"]["schemas"]["UploadResponse"]["properties"]
