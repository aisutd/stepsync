import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pose_processing import run_pose_extraction
from app.video import VideoError
from app.youtube import DownloadedVideo


def test_failed_pose_retains_source(video, monkeypatch):
    def download(url, directory, settings):
        destination = directory / "input.mp4"
        destination.write_bytes(video.read_bytes())
        return DownloadedVideo(destination, "Dance")

    def fail(*args):
        raise VideoError("pose_processing_timeout", "Pose extraction exceeded its time limit.", 500)

    monkeypatch.setattr("app.main.download_video", download)
    with TestClient(create_app(pose_runner=fail)) as client:
        response = client.post("/reference-videos", json={"url": "https://youtu.be/jNQXAC9IVRw"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == body["pose_processing"] == "failed"
    assert body["pose_error_code"] == "pose_processing_timeout"
    assert body["persisted"] is True
    assert Path(body["saved_path"]).read_bytes() == video.read_bytes()
    assert body["pose_data_path"] is None


@pytest.mark.parametrize("failure", ["timeout", "process", "missing_output", "empty_output"])
def test_runner_failure_removes_partial_artifacts(tmp_path, monkeypatch, failure):
    model = tmp_path / "model.task"
    model.write_bytes(b"model")
    output = tmp_path / "pose"

    def run(command, **kwargs):
        preview = Path(command[command.index("--output-video") + 1])
        data = Path(command[command.index("--output-csv") + 1])
        preview.write_bytes(b"partial")
        if failure == "empty_output":
            data.touch()
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if failure == "process":
            raise subprocess.CalledProcessError(1, command, stderr="inference failed")

    monkeypatch.setattr("app.pose_processing.subprocess.run", run)
    with pytest.raises(VideoError) as caught:
        run_pose_extraction(tmp_path / "source.mp4", output, model, 5)
    assert caught.value.code == ("pose_processing_timeout" if failure == "timeout" else "pose_processing_failed")
    assert not list(output.iterdir())


def test_runner_invokes_cli_and_returns_outputs(tmp_path, monkeypatch):
    import sys
    model = tmp_path / "model.task"
    model.touch()

    def run(command, **kwargs):
        assert command[0] == sys.executable
        assert Path(command[1]).name == "pose_extraction.py"
        assert kwargs["timeout"] == 7
        for flag in ("--output-video", "--output-csv"):
            Path(command[command.index(flag) + 1]).write_bytes(b"complete")

    monkeypatch.setattr("app.pose_processing.subprocess.run", run)
    artifacts = run_pose_extraction(tmp_path / "source.mp4", tmp_path / "output", model, 7)
    assert artifacts.preview_path.read_bytes() == artifacts.data_path.read_bytes() == b"complete"


def test_missing_model(tmp_path):
    with pytest.raises(VideoError) as caught:
        run_pose_extraction(tmp_path / "source.mp4", tmp_path / "output", tmp_path / "missing.task", 5)
    assert caught.value.code == "pose_model_missing"


def test_storage_and_processing_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("STEPSYNC_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("STEPSYNC_MAX_DURATION_SECONDS", "300")
    monkeypatch.setenv("STEPSYNC_POSE_PROCESSING_TIMEOUT_SECONDS", "1200")
    settings = Settings.from_env()
    assert settings.video_directory == tmp_path / "videos"
    assert settings.pose_results_directory == tmp_path / "pose-results"
    assert settings.max_duration_seconds == 300
    assert settings.pose_processing_timeout_seconds == 1200


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_pose_timeout(timeout):
    with pytest.raises(ValueError):
        Settings(pose_processing_timeout_seconds=timeout)
