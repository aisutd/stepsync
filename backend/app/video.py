"""OpenCV decoding and RGB frame preparation. No pose extraction is performed."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from .config import Settings


class VideoError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int
    fps: float
    frame_count: int
    rotation_degrees: float
    timestamp_source: str = "opencv_pos_msec"


@dataclass(frozen=True)
class PreparedFrame:
    source_frame_index: int
    timestamp_seconds: float
    image_rgb: np.ndarray  # uint8 H x W x 3, RGB, upright, never mirrored.


def _open(path: Path):
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise VideoError("unreadable_video", "The file is not a readable video.")
    # Rotate explicitly to avoid decoder-dependent double rotation.
    capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    return capture


def read_metadata(path: Path) -> VideoMetadata:
    capture = _open(path)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        rotation = capture.get(cv2.CAP_PROP_ORIENTATION_META)
        if any(not math.isfinite(v) or v <= 0 for v in (fps, count, width, height)):
            raise VideoError("invalid_metadata", "Video FPS, frame count, or dimensions are unavailable.")
        if not math.isfinite(rotation) or rotation % 360 not in (0, 90, 180, 270):
            raise VideoError("unsupported_orientation", "Unsupported video rotation metadata.")
        return VideoMetadata(count / fps, int(width), int(height), fps,
                             int(count), rotation % 360)
    finally:
        capture.release()


def decoded_frames(path: Path, metadata: VideoMetadata) -> Iterator[tuple[int, float, np.ndarray]]:
    """Decode all source frames sequentially; fail on detectable truncation/timing errors.

    OpenCV cannot distinguish every decoder error from EOF. Comparing decoded
    count with reported count catches many partial files but is not a guarantee.
    Timestamps use decoder POS_MSEC, relative to the first frame, without an FPS fallback.
    """
    capture = _open(path)
    count = 0
    origin = None
    previous = -1.0
    try:
        while True:
            ok, image = capture.read()
            if not ok:
                break
            if image is None or image.size == 0:
                raise VideoError("corrupt_video", "A video frame could not be decoded.")
            timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if not math.isfinite(timestamp) or timestamp < 0:
                raise VideoError("invalid_timestamps", "The decoder did not provide valid frame timestamps.")
            if origin is None:
                origin = timestamp
            timestamp -= origin
            if timestamp <= previous:
                raise VideoError("invalid_timestamps", "Frame timestamps are missing or do not increase.")
            previous = timestamp
            yield count, timestamp, image
            count += 1
        if count == 0 or count != metadata.frame_count:
            raise VideoError("corrupt_video", "The video is unreadable or incomplete: decoded frame count differs from metadata.")
    finally:
        capture.release()


def validate_video(path: Path, settings: Settings) -> VideoMetadata:
    metadata = read_metadata(path)
    if metadata.duration_seconds > settings.max_duration_seconds:
        raise VideoError("video_too_long", f"Video duration is approximately {metadata.duration_seconds:.2f} seconds; the limit is {settings.max_duration_seconds:g} seconds.")
    for _, timestamp, _ in decoded_frames(path, metadata):
        if timestamp >= settings.max_duration_seconds:
            raise VideoError("video_too_long", f"Video exceeds the {settings.max_duration_seconds:g}-second limit.")
    return metadata


def resize_frame(image: np.ndarray, max_width: int, max_height: int) -> np.ndarray:
    """Fit inside the configured box, preserving aspect ratio; never upscale."""
    if max_width <= 0 or max_height <= 0:
        raise ValueError("Frame bounds must be positive.")
    height, width = image.shape[:2]
    scale = min(1.0, max_width / width, max_height / height)
    if scale == 1.0:
        return image
    return cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))),
                      interpolation=cv2.INTER_AREA)


def prepared_frames(path: Path, metadata: VideoMetadata, settings: Settings) -> Iterator[PreparedFrame]:
    """Select at most one source frame per target time bucket; retain source time.

    No frames are duplicated or interpolated. The sampling target is a ceiling
    on time buckets, not a promise of exactly that many frames per second.
    """
    previous_bucket = -1
    rotations = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    for index, timestamp, image in decoded_frames(path, metadata):
        bucket = math.floor(timestamp * settings.target_fps + 1e-7)
        if bucket == previous_bucket:
            continue
        previous_bucket = bucket
        if metadata.rotation_degrees:
            image = cv2.rotate(image, rotations[metadata.rotation_degrees])
        image = resize_frame(image, settings.max_frame_width, settings.max_frame_height)
        yield PreparedFrame(index, timestamp, cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
