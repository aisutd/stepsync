"""Validate uploads, reuse Kaitlyn's extractor and Lucy's local feature code."""

from features import read_pose_csv, compute_features, save_features

from .comparison import ComparisonConfig, compare, samples_from_frames
from .video import VideoError, validate_video
from .session_store import persist_analysis


def analyze_videos(session_id, reference, practice, directory, settings, pose_runner,
                   config=None):
    config = config or ComparisonConfig()
    sequences = []
    for name, path in (("reference", reference), ("practice", practice)):
        metadata = validate_video(path, settings)
        if metadata.rotation_degrees:
            raise VideoError("unsupported_comparison_orientation",
                             "Export both clips upright without rotation metadata before comparison.")
        artifacts = pose_runner(path, directory / name, settings.pose_model_path,
                                settings.pose_processing_timeout_seconds)
        try:
            frames = read_pose_csv(artifacts.data_path)
            save_features(compute_features(name, frames, source_file=str(artifacts.data_path)), directory)
            sequences.append(samples_from_frames(frames, config, sample=False))
        except (ValueError, KeyError) as error:
            raise VideoError("invalid_pose_data",
                             f"The {name} pose data has invalid timestamps or coordinates; comparison was not scored.") from error
    result = {"sessionId": session_id, **compare(*sequences, config)}
    # Presentation metadata only: these counts never affect eligibility or scores.
    rows = result["frameComparisons"]
    assessed = sum(row["status"] == "compared" for row in rows)
    result["assessment"] = {"totalFrames": len(rows), "assessedFrames": assessed,
                            "unassessedFrames": len(rows) - assessed}
    return persist_analysis(result, directory, session_id, settings.analysis_retention_seconds)
