import cv2
import numpy as np
import pytest


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    assert writer.isOpened(), "The test environment needs an MP4 encoder."
    try:
        for index in range(20):
            image = np.zeros((120, 160, 3), dtype=np.uint8)
            image[:, :, 2] = 200  # Red in OpenCV BGR.
            image[:, index:index + 10, 1] = 100
            writer.write(image)
    finally:
        writer.release()
    return path



@pytest.fixture(autouse=True)
def isolated_downloads(tmp_path, monkeypatch):
    directory = tmp_path / "data" / "videos"
    monkeypatch.setenv("STEPSYNC_DATA_DIRECTORY", str(directory.parent))
    return directory


@pytest.fixture(autouse=True)
def fake_pose_runner(monkeypatch):
    from app.pose_processing import PoseArtifacts

    def run(video_path, output_directory, model_path, timeout_seconds):
        assert video_path.is_file()
        output_directory.mkdir(parents=True, exist_ok=True)
        preview = output_directory / "skeleton_preview.mp4"
        data = output_directory / "pose_data.csv"
        preview.write_bytes(b"mock preview")
        data.write_text("frame_index,pose_present\n0,0\n")
        return PoseArtifacts(preview, data)

    monkeypatch.setattr("app.main.run_pose_extraction", run)
