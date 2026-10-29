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
    directory = tmp_path / "Downloads"
    monkeypatch.setattr("app.main.DOWNLOADS_DIRECTORY", directory)
    return directory
