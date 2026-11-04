import csv
from pathlib import Path

import pytest

from features import (angle_degrees, compute_features, load_features, read_pose_csv,
                      save_features, save_features_csv, to_db_rows)
from features.store import CSV_FIELDS

OUTPUT = Path(__file__).resolve().parents[1] / "output"
HEADER = ["frame_index", "timestamp_ms", "frame_status", "pose_present", "landmark_id",
          "landmark_name", "x_norm", "y_norm", "z_relative", "visibility", "presence",
          "landmark_reliable", "world_x", "world_y", "world_z", "hip_relative_x_norm",
          "hip_relative_y_norm", "hip_relative_z_norm", "torso_scale_m"]


def write_pose_csv(path, frames):
    """frames: list of (frame_index, timestamp_ms, status, {name: (x, y, z, reliable)})."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        for frame_index, ts, status, joints in frames:
            if status == "NO_POSE":
                writer.writerow([frame_index, ts, status, 0, 0, "nose"] + [""] * 13)
                continue
            for i, (name, (x, y, z, reliable)) in enumerate(joints.items()):
                writer.writerow([frame_index, ts, status, 1, i, name, 0.5, 0.5, 0, 0.9, 0.9,
                                 int(reliable), x, y, z, "", "", "", ""])
    return path


def row(doc, frame_index, feature):
    return next(r for r in doc["rows"]
                if r["frame_index"] == frame_index and r["feature"] == feature)


# Arm hanging straight down in frame 0, bent forward 90 degrees (depth axis) in frame 1.
STRAIGHT_ARM = {"left_shoulder": (0, 0, 0, True), "left_elbow": (0, 0.3, 0, True),
                "left_wrist": (0, 0.6, 0, True)}
BENT_ARM = {"left_shoulder": (0, 0, 0, True), "left_elbow": (0, 0.3, 0, True),
            "left_wrist": (0, 0.3, -0.25, True)}


@pytest.fixture
def synthetic(tmp_path):
    path = write_pose_csv(tmp_path / "pose.csv", [
        (0, 0, "OK", STRAIGHT_ARM),
        (1, 33, "OK", BENT_ARM),
        (2, 67, "NO_POSE", {}),
        (3, 100, "LOW_CONFIDENCE", {**STRAIGHT_ARM, "left_wrist": (0, 0.6, 0, False)}),
    ])
    return compute_features("synthetic", read_pose_csv(path))


def test_angle_math():
    assert angle_degrees((0, 0), (1, 0), (2, 0)) == pytest.approx(180)
    assert angle_degrees((0, 1, 0), (0, 0, 0), (0, 0, 1)) == pytest.approx(90)
    assert angle_degrees((1, 1), (1, 1), (2, 2)) is None


def test_straight_limb_near_180(synthetic):
    assert row(synthetic, 0, "left_elbow_angle")["value"] == pytest.approx(180, abs=1)


def test_right_angle_uses_depth(synthetic):
    # The bend is purely in z, so a 2D-only calculation would see a straight line.
    assert row(synthetic, 1, "left_elbow_angle")["value"] == pytest.approx(90, abs=1)


def test_no_pose_is_missing_not_zero(synthetic):
    for r in (r for r in synthetic["rows"] if r["frame_index"] == 2):
        assert r["value"] is None
        assert r["status"] == "missing"
        assert r["missing_reason"] == "no_pose_detected"


def test_unreliable_landmark_is_missing(synthetic):
    r = row(synthetic, 3, "left_elbow_angle")
    assert r["value"] is None
    assert r["missing_reason"] == "unreliable:left_wrist"
    assert r["frame_status"] == "LOW_CONFIDENCE"


def test_absent_joint_reports_which(synthetic):
    assert row(synthetic, 0, "right_elbow_angle")["missing_reason"] == "no_coordinates:right_shoulder"


def test_timestamps_and_units_carried_through(synthetic):
    assert row(synthetic, 1, "left_elbow_angle")["timestamp_ms"] == 33
    assert {r["units"] for r in synthetic["rows"]} == {"degrees", "degrees/s", "m/s"}
    assert {r["units"] for r in synthetic["rows"] if r["feature"].endswith("_angle")} == {"degrees"}


# Kaitlyn's real outputs.

def test_real_reze_file():
    frames = read_pose_csv(OUTPUT / "reze_pose_data.csv")
    assert len(frames) == 616
    assert sum(f.frame_status == "NO_POSE" for f in frames) == 129
    doc = compute_features("reze", frames)
    values = [r["value"] for r in doc["rows"] if r["status"] == "ok" and r["units"] == "degrees"]
    assert values
    assert all(0 <= v <= 180 for v in values)


def test_real_no_person_file_all_missing():
    doc = compute_features("no_person", read_pose_csv(OUTPUT / "no_person_pose_data.csv"))
    assert doc["rows"]
    assert all(r["value"] is None and r["missing_reason"] == "no_pose_detected"
               for r in doc["rows"])


def test_real_low_confidence_frames_handled():
    doc = compute_features("forest", read_pose_csv(OUTPUT / "forest_pose_data.csv"))
    low = [r for r in doc["rows"] if r["frame_status"] == "LOW_CONFIDENCE"]
    assert low
    assert any(r["missing_reason"] and r["missing_reason"].startswith("unreliable:") for r in low)


# Storage.

def test_save_then_load_matches(tmp_path):
    doc = compute_features("reze", read_pose_csv(OUTPUT / "reze_pose_data.csv"))
    save_features(doc, tmp_path)
    assert load_features(tmp_path, "reze") == doc


def test_load_rejects_wrong_video(tmp_path):
    doc = compute_features("reze", read_pose_csv(OUTPUT / "no_person_pose_data.csv"))
    save_features(doc, tmp_path)
    (tmp_path / "reze_features.json").rename(tmp_path / "other_features.json")
    with pytest.raises(ValueError, match="belongs to video"):
        load_features(tmp_path, "other")


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "..", ""])
def test_unsafe_video_ids_rejected(tmp_path, bad_id):
    with pytest.raises(ValueError):
        save_features({"video_id": bad_id, "rows": []}, tmp_path)


def test_db_rows_and_csv(tmp_path, synthetic):
    rows = to_db_rows(synthetic)
    assert len(rows) == len(synthetic["rows"])
    assert all(r["video_id"] == "synthetic" for r in rows)

    path = save_features_csv(synthetic, tmp_path / "f.csv")
    with open(path, newline="", encoding="utf-8") as f:
        written = list(csv.DictReader(f))
    assert list(written[0].keys()) == CSV_FIELDS
    missing = next(r for r in written if r["frame_index"] == "2")
    assert missing["value"] == ""  # blank, not 0
