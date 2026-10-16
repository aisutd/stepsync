import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pose_extraction import ConditionalJitterSmoother, write_no_pose_rows


def test_smoothing_reduces_stationary_jitter_and_reset_removes_history():
    smoother = ConditionalJitterSmoother()
    values = [0.5 + (0.01 if index % 2 else -0.01) for index in range(60)]
    filtered = [smoother.update(index / 30, (value, 0, 0), 0.9, 0.9)[0] for index, value in enumerate(values)]
    assert max(filtered[10:]) - min(filtered[10:]) < (max(values) - min(values)) / 2
    smoother.reset()
    assert smoother.update(3.0, (0.8, 0.2, 0.1), 0.9, 0.9) == (0.8, 0.2, 0.1)


def test_invalid_point_clears_history():
    smoother = ConditionalJitterSmoother()
    smoother.update(0, (0, 0, 0), 0.9, 0.9)
    assert smoother.update(0.1, (float("nan"), 0, 0), 0.9, 0.9) is None
    assert smoother.update(0.2, (1, 1, 1), 0.9, 0.9) == (1, 1, 1)


@pytest.mark.parametrize("visibility,presence", [(0.49, 0.9), (0.9, 0.49), (None, 0.9), (0.9, float("nan"))])
def test_low_confidence_returns_blank_and_resets_history(visibility, presence):
    smoother = ConditionalJitterSmoother()
    smoother.update(0, (0, 0, 0), 1, 1)
    assert smoother.update(0.1, (100, 100, 100), visibility, presence) is None
    assert smoother.update(0.2, (1, 2, 3), 0.5, 0.5) == (1, 2, 3)


def test_steady_motion_passes_through_without_averaging():
    smoother = ConditionalJitterSmoother(window_size=3)
    for index in range(5):
        result = smoother.update(index / 30, (index, 2 * index, -index), 1, 1)
        assert result == (index, 2 * index, -index)
        assert not smoother.jitter_detected


def test_missing_point_and_nonincreasing_time_reset_history():
    smoother = ConditionalJitterSmoother()
    smoother.update(1, (0, 0, 0), 1, 1)
    assert smoother.update(2, None, 1, 1) is None
    assert smoother.update(3, (2, 2, 2), 1, 1) == (2, 2, 2)
    assert smoother.update(3, (4, 4, 4), 1, 1) == (4, 4, 4)
    assert smoother.update(1, (6, 6, 6), 1, 1) == (6, 6, 6)


@pytest.mark.parametrize("window", [0, 1, 2, -1, 1.5, True])
def test_invalid_averaging_window(window):
    with pytest.raises(ValueError):
        ConditionalJitterSmoother(window_size=window)


def test_small_rapid_reversal_is_averaged_only_on_detection():
    smoother = ConditionalJitterSmoother()
    assert smoother.update(0, (0, 0, 0), 1, 1) == (0, 0, 0)
    assert smoother.update(1 / 30, (0.02, 0, 0), 1, 1) == (0.02, 0, 0)
    result = smoother.update(2 / 30, (0, 0, 0), 1, 1)
    assert smoother.jitter_detected
    assert result == pytest.approx((0.02 / 3, 0, 0))
    assert smoother.update(3 / 30, (-0.02, 0, 0), 1, 1) == (-0.02, 0, 0)
    assert not smoother.jitter_detected


@pytest.mark.parametrize("step,interval", [(0.2, 1 / 30), (0.02, 0.2)])
def test_large_or_slow_reversals_are_not_smoothed(step, interval):
    smoother = ConditionalJitterSmoother()
    smoother.update(0, (0, 0, 0), 1, 1)
    smoother.update(interval, (step, 0, 0), 1, 1)
    assert smoother.update(2 * interval, (0, 0, 0), 1, 1) == (0, 0, 0)
    assert not smoother.jitter_detected


def test_coordinate_spaces_use_independent_step_limits():
    image = ConditionalJitterSmoother(max_step=0.03)
    torso = ConditionalJitterSmoother(max_step=0.10)
    for index, x in enumerate((0, 0.05, 0)):
        image.update(index / 30, (x, 0, 0), 1, 1)
        torso.update(index / 30, (x, 0, 0), 1, 1)
    assert not image.jitter_detected
    assert torso.jitter_detected


def test_missing_pose_csv_preserves_schema_and_blank_coordinates():
    stream = io.StringIO()
    write_no_pose_rows(csv.writer(stream), 5, 100, "NO_POSE")
    rows = list(csv.reader(io.StringIO(stream.getvalue())))
    assert len(rows) == 33
    assert all(len(row) == 25 and row[3] == "0" and row[6:] == [""] * 19 for row in rows)
