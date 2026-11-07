"""Validate uploads, reuse Kaitlyn's extractor and Lucy's local feature code."""

import csv
from pathlib import Path

from features import read_pose_csv, compute_features, save_features

from .comparison import ComparisonConfig, compare, samples_from_frames
from .video import VideoError, validate_video
from .session_store import persist_analysis


def analyze_videos(session_id, reference, practice, directory, settings, pose_runner,
                   config=None, *, reference_csv=None, reference_start=None, reference_end=None):
    config = config or ComparisonConfig()
    sequences = []
    for name, path in (("reference", reference), ("practice", practice)):
        cached = Path(reference_csv) if name == "reference" and reference_csv is not None else None
        if cached is None or not cached.is_file():
            metadata = validate_video(path, settings)
            if metadata.rotation_degrees:
                raise VideoError("unsupported_comparison_orientation",
                                 "Export both clips upright without rotation metadata before comparison.")
            artifacts = pose_runner(path, cached.parent if cached is not None else directory / name, settings.pose_model_path,
                                    settings.pose_processing_timeout_seconds)
            source_csv = artifacts.data_path
        else:
            source_csv = cached
        # Persist the exact input measurements, so mirror retries use the same step.
        with open(source_csv, newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            fields = reader.fieldnames
            rows = [row for row in reader if name != "reference" or reference_start is None
                    or reference_start * 1000 <= int(row["timestamp_ms"]) < reference_end * 1000]
        if name == "reference" and reference_start is not None and not rows:
            raise VideoError("invalid_step_range", "No pose frames were found in the selected step.")
        target = directory / name / "pose_data.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        try:
            frames = read_pose_csv(target)
            save_features(compute_features(name, frames, source_file=str(target)), directory)
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
