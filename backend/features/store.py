"""Save and load feature documents by video ID.

Local JSON files for now. When the database exists, `to_db_rows` gives one flat
record per (frame, feature) that maps directly onto a table (see README.md).
"""

import csv
import json
import re
from pathlib import Path

REQUIRED_ROW_FIELDS = {"frame_index", "timestamp_ms", "feature", "value", "units", "status"}
CSV_FIELDS = ["video_id", "frame_index", "timestamp_ms", "frame_status", "feature",
              "value", "units", "status", "missing_reason"]


def features_path(directory, video_id):
    # Video IDs become file names, so keep them to safe characters.
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", video_id) or video_id.strip(".") == "":
        raise ValueError(f"Invalid video ID for a file name: {video_id!r}")
    return Path(directory) / f"{video_id}_features.json"


def save_features(doc, directory):
    path = features_path(directory, doc["video_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return path


def load_features(directory, video_id):
    """Load a saved document and check it belongs to `video_id` and has the expected fields."""
    path = features_path(directory, video_id)
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    if doc.get("video_id") != video_id:
        raise ValueError(f"{path} belongs to video {doc.get('video_id')!r}, not {video_id!r}")
    for i, row in enumerate(doc.get("rows", [])):
        missing = REQUIRED_ROW_FIELDS - row.keys()
        if missing:
            raise ValueError(f"{path} row {i} is missing fields: {sorted(missing)}")
    return doc


def to_db_rows(doc):
    return [{"video_id": doc["video_id"], **row} for row in doc["rows"]]


def save_features_csv(doc, path):
    """Spreadsheet-friendly copy. Missing values are left blank, not 0."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in to_db_rows(doc):
            writer.writerow({k: "" if row.get(k) is None else row[k] for k in CSV_FIELDS})
    return path
