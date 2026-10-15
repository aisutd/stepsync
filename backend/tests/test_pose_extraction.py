import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pose_extraction import OneEuroFilter, write_no_pose_rows


def test_smoothing_reduces_stationary_jitter_and_reset_removes_history():
    smoother = OneEuroFilter()
    values = [0.5 + (0.01 if index % 2 else -0.01) for index in range(60)]
    filtered = [smoother.update(index / 30, (value, 0, 0))[0] for index, value in enumerate(values)]
    assert max(filtered[10:]) - min(filtered[10:]) < (max(values) - min(values)) / 2
    smoother.reset()
    assert smoother.update(3.0, (0.8, 0.2, 0.1)) == (0.8, 0.2, 0.1)


def test_invalid_point_clears_history():
    smoother = OneEuroFilter()
    smoother.update(0, (0, 0, 0))
    assert smoother.update(0.1, (float("nan"), 0, 0)) is None
    assert smoother.update(0.2, (1, 1, 1)) == (1, 1, 1)


def test_missing_pose_csv_preserves_schema_and_blank_coordinates():
    stream = io.StringIO()
    write_no_pose_rows(csv.writer(stream), 5, 100, "NO_POSE")
    rows = list(csv.reader(io.StringIO(stream.getvalue())))
    assert len(rows) == 33
    assert all(len(row) == 25 and row[3] == "0" and row[6:] == [""] * 19 for row in rows)
