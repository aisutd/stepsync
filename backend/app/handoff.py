"""Future teammate boundary; no MediaPipe or features are implemented here."""

from enum import Enum
from typing import Iterable, Protocol

from .video import PreparedFrame, VideoMetadata


class ProcessingState(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class PoseExtractor(Protocol):
    def __call__(self, frames: Iterable[PreparedFrame], metadata: VideoMetadata) -> None:
        """Consume RGB frames synchronously; output contract awaits Kaitlyn.

        The temporary source is valid only during the caller's context. Consume
        the iterator before returning. Video ID/result persistence will be added
        when the team agrees on those contracts.
        """
        ...


def pose_extractor_placeholder(frames: Iterable[PreparedFrame], metadata: VideoMetadata) -> None:
    raise NotImplementedError("Kaitlyn's pose extractor is not connected yet.")
