"""Tests of Lucy's reused calculations and the comparison adapter."""

import csv
import math

import pytest

from features import angle_degrees, compute_features, read_pose_csv, save_features, load_features
from features.pose_csv import Landmark, PoseFrame
from app.comparison import ComparisonConfig, samples_from_frames


def pose_frames(fps=30, seconds=2, knee=160, confidence=0.95):
    points = {
        "left_shoulder": (-0.2, 0, 0), "right_shoulder": (0.2, 0, 0),
        "left_hip": (-0.15, 0.5, 0), "right_hip": (0.15, 0.5, 0),
        "left_knee": (-0.15, 0.9, 0), "right_knee": (0.15, 0.9, 0),
        "left_ankle": (-0.15 + 0.4 * math.sin(math.radians(180 - knee)),
                       0.9 + 0.4 * math.cos(math.radians(180 - knee)), 0),
        "right_ankle": (0.15, 1.3, 0),
        "left_elbow": (-0.4, 0.3, 0), "right_elbow": (0.4, 0.3, 0),
        "left_wrist": (-0.5, 0.6, 0), "right_wrist": (0.5, 0.6, 0),
    }
    return [PoseFrame(i, round(i * 1000 / fps), "OK", True,
                      {name: Landmark(j, name, confidence >= 0.5, xyz, confidence)
                       for j, (name, xyz) in enumerate(points.items())})
            for i in range(round(seconds * fps) + 1)]


def write_csv(path, frames):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["frame_index", "timestamp_ms", "frame_status",
            "pose_present", "landmark_id", "landmark_name", "landmark_reliable", "visibility",
            "presence", "world_x", "world_y", "world_z"])
        writer.writeheader()
        for frame in frames:
            for p in frame.landmarks.values():
                writer.writerow(dict(frame_index=frame.frame_index, timestamp_ms=frame.timestamp_ms,
                    frame_status=frame.frame_status, pose_present=int(frame.pose_present),
                    landmark_id=p.landmark_id, landmark_name=p.name,
                    landmark_reliable=int(p.reliable), visibility=p.confidence, presence=p.confidence,
                    world_x=p.world[0], world_y=p.world[1], world_z=p.world[2]))
    return path


def test_lucy_angle_math():
    assert angle_degrees((0, 0, 0), (1, 0, 0), (2, 0, 0)) == 180
    assert angle_degrees((1, 0, 0), (0, 0, 0), (0, 0, 1)) == 90
    assert angle_degrees((0, 0), (0, 0), (1, 1)) is None


def test_csv_confidence_features_and_storage(tmp_path):
    path = write_csv(tmp_path / "pose.csv", pose_frames())
    frames = read_pose_csv(path)
    assert frames[0].landmarks["left_knee"].confidence == 0.95
    doc = compute_features("test", frames)
    knees = [r for r in doc["rows"] if r["feature"] == "left_knee_angle"]
    assert knees[0]["value"] == pytest.approx(160, abs=0.01)
    save_features(doc, tmp_path)
    assert load_features(tmp_path, "test") == doc


def test_unreliable_and_low_confidence_masked():
    config = ComparisonConfig()
    assert all(not s.values for s in samples_from_frames(pose_frames(confidence=0.4), config))
    assert all(not s.values for s in samples_from_frames(pose_frames(confidence=0.6), config))


def test_adapter_sampling_retains_original_times():
    samples = samples_from_frames(pose_frames(fps=30), ComparisonConfig())
    assert len(samples) == 21
    assert samples[10].time == 1
    assert samples[-1].time == 2


def test_sampling_keeps_last_source_timestamp_and_limit():
    frames = pose_frames(fps=24, seconds=1.25)
    samples = samples_from_frames(frames, ComparisonConfig(max_samples=10))
    assert len(samples) <= 10
    assert samples[-1].time == frames[-1].timestamp_ms / 1000


def test_velocity_never_crosses_missing_interval():
    frames = pose_frames()
    frames[5].landmarks["left_wrist"].reliable = False
    samples = samples_from_frames(frames, ComparisonConfig(sample_hz=30))
    assert "left_wrist_speed" not in samples[6].values
    assert "left_elbow_velocity" not in samples[6].values
    assert "left_wrist_speed" in samples[10].values


def test_nonincreasing_timestamps_rejected():
    frames = pose_frames()
    frames[1].timestamp_ms = 0
    with pytest.raises(ValueError, match="timestamps"):
        samples_from_frames(frames, ComparisonConfig())


def test_lucy_velocity_known_angle_change():
    frames = pose_frames(fps=10)
    bent = pose_frames(knee=130)[0].landmarks["left_ankle"]
    frames[4].landmarks["left_ankle"] = bent
    rows = compute_features("test", frames)["rows"]
    velocity = next(r for r in rows if r["frame_index"] == 4 and r["feature"] == "left_knee_velocity")
    assert velocity["value"] == pytest.approx(-75, abs=0.01)
