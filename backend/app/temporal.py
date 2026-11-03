"""Time-normalized, slope-constrained DTW, independent of video identities.

Alignment uses median-centered angles to tolerate persistent execution offsets;
scoring must still use the original angles. No feature values are interpolated.
"""

import math
from dataclasses import replace

import numpy as np
from .comparison_diagnostics import pair_evidence, summarize_pairs


def _grid(samples, count, max_gap):
    times = np.array([s.time for s in samples])
    targets = np.linspace(times[0], times[-1], count)
    right = np.clip(np.searchsorted(times, targets), 0, len(times) - 1)
    left = np.maximum(right - 1, 0)
    indices = np.where(abs(times[left] - targets) < abs(times[right] - targets), left, right)
    tolerance = max(max_gap, float(np.median(np.diff(times))) / 2 + 1e-6)
    return [samples[i] if abs(times[i] - target) <= tolerance else
            replace(samples[i], time=float(target), values={}, confidence={}, axis=None, frame_index=None,
                    rejections={k: ["source_timestamp_gap"] for k in samples[i].values})
            for i, target in zip(indices, targets)]


def _matrices(reference, practice, config, mirrored):
    count = len(reference)
    numerator = np.zeros((count, count))
    denominator = np.zeros_like(numerator)
    available_weight = np.zeros_like(numerator)
    total = 0
    for name, weight in config.weights.items():
        if weight <= 0 or not name.endswith("_angle"):
            continue
        other = name
        if mirrored:
            other = ("right_" + name[5:]) if name.startswith("left_") else ("left_" + name[6:])
        a = np.array([s.values.get(name, np.nan) for s in reference])
        b = np.array([s.values.get(other, np.nan) for s in practice])
        ca = np.array([s.confidence.get(name, 0) for s in reference])
        cb = np.array([s.confidence.get(other, 0) for s in practice])
        reliable = (np.isfinite(a[:, None]) & np.isfinite(b[None, :])
                    & (ca[:, None] >= config.min_confidence) & (cb[None, :] >= config.min_confidence))
        overlap = np.diag(reliable)
        # Estimate the dancer offset using the SAME normalized instants. Separate
        # medians would be biased when one clip loses poses during a high/low phase.
        offset = float(np.median((a - b)[overlap])) if overlap.any() else 0
        raw = abs(a[:, None] - b[None, :]) / config.angle_scale
        shape = abs(a[:, None] - b[None, :] - offset) / config.alignment_angle_scale
        # Bounded influence: an incorrect limb cannot dominate every other limb.
        loss = 0.8 * np.minimum(shape, 1) + 0.2 * np.minimum(raw, 1)
        effective = np.where(reliable, weight * np.minimum(ca[:, None], cb[None, :]), 0)
        numerator += np.where(reliable, loss, 0) * effective
        denominator += effective
        available_weight += np.where(reliable, weight, 0)
        total += weight
    axes_a = np.array([s.axis if s.axis is not None else (np.nan,) * 3 for s in reference])
    axes_b = np.array([s.axis if s.axis is not None else (np.nan,) * 3 for s in practice])
    if mirrored:
        axes_b[:, 0] *= -1
    norms = np.linalg.norm(axes_a, axis=1)[:, None] * np.linalg.norm(axes_b, axis=1)[None, :]
    view = np.abs(axes_a @ axes_b.T) / np.maximum(norms, 1e-12)
    supported = ((available_weight >= total * config.min_coverage)
                 & (denominator >= available_weight * config.min_confidence)
                 & (view >= config.viewpoint_agreement))
    local = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)
    return local, supported


def align(reference, practice, config, mirrored):
    # Both clips use the same normalized-time grid: FPS and global execution
    # speed no longer alter the meaning of a slope constraint.
    duration = max(reference[-1].time - reference[0].time, practice[-1].time - practice[0].time)
    count = max(3, min(config.max_samples, math.ceil(duration * config.sample_hz) + 1))
    a, b = (_grid(samples, count, config.max_observation_gap_seconds) for samples in (reference, practice))
    local, supported = _matrices(a, b, config, mirrored)
    phase = abs(np.arange(count)[:, None] - np.arange(count)[None, :]) / (count - 1)
    # Occlusions supply no matching evidence. A weak clock prior bridges them
    # without turning the gap's length into a large pose-mismatch penalty.
    neutral_gap_cost = max(config.gap_cost, float(np.median(local[supported]))) if supported.any() else config.gap_cost
    loss = np.where(supported, local, neutral_gap_cost) + config.clock_penalty * phase
    costs = np.full((count, count), np.inf)
    parent = {}
    costs[0, 0] = loss[0, 0]
    radius = max(2, math.ceil(config.band_fraction * (count - 1)))
    steps = [(1, 1)] + [(1, k) for k in range(2, config.max_local_tempo_ratio + 1)] + [
        (k, 1) for k in range(2, config.max_local_tempo_ratio + 1)]
    for i in range(count):
        for j in range(max(0, i - radius), min(count, i + radius + 1)):
            if i == j == 0:
                continue
            for di, dj in steps:
                pi, pj = i - di, j - dj
                if pi < 0 or pj < 0 or not math.isfinite(costs[pi, pj]):
                    continue
                cells = ([(i, y) for y in range(pj + 1, j + 1)] if di == 1 else
                         [(x, j) for x in range(pi + 1, i + 1)])
                if any(abs(x - y) > radius for x, y in cells):
                    continue
                # Weight by traversed time rather than number of repeated cells.
                length = (di + dj) / 2
                candidate = costs[pi, pj] + length * (
                    sum(loss[x, y] for x, y in cells) / len(cells)
                    + config.stretch_penalty * abs(di - dj))
                if candidate < costs[i, j]:
                    costs[i, j] = candidate
                    parent[i, j] = (pi, pj)
    cell = (count - 1, count - 1)
    if cell not in parent:
        return [], math.inf, {"reason": "No path satisfies the configured timing constraints."}
    knots = [cell]
    while cell != (0, 0):
        cell = parent[cell]
        knots.append(cell)
    knots.reverse()
    # Timing interpolation only; downstream values always come from real frames.
    knot_reference = np.array([reference[0].time + i / (count - 1) *
                               (reference[-1].time - reference[0].time) for i, _ in knots])
    knot_practice = np.array([practice[0].time + j / (count - 1) *
                              (practice[-1].time - practice[0].time) for _, j in knots])
    targets = np.interp([s.time for s in practice], knot_practice, knot_reference)
    rt = np.array([s.time for s in reference])
    right = np.clip(np.searchsorted(rt, targets), 0, len(rt) - 1)
    left = np.maximum(right - 1, 0)
    indices = np.where(abs(rt[left] - targets) < abs(rt[right] - targets), left, right)
    # A decoder/frame gap cannot be turned into invented reference observations.
    tolerance = max(config.max_observation_gap_seconds, float(np.median(np.diff(rt))) / 2 + 1e-6)
    pairs = [(int(i), j) for j, i in enumerate(indices)
             if abs(rt[i] - targets[j]) <= tolerance]
    measured = [local[i, j] for i, j in knots if supported[i, j]]
    score = float(np.mean(measured)) if measured else math.inf
    records = []
    for (i, j), r, p in zip(knots, knot_reference, knot_practice):
        evidence = pair_evidence(a[i], b[j], config, mirrored)
        records.append({**evidence, "referenceTime": round(float(r), 6), "practiceTime": round(float(p), 6),
                        "alignmentCost": round(float(local[i, j]), 6) if supported[i, j] else None})
    return pairs, score, {"gridSamples": count, "supportedAnchorFraction": round(len(measured) / len(knots), 4),
                          "neutralGapCost": round(neutral_gap_cost, 6),
                          "objectiveCost": round(float(costs[-1, -1] / (count - 1)), 6),
                          "anchorDiagnostics": records, "anchorRejections": summarize_pairs(records),
                          "viewpointCheck": "shoulder_axis_cosine_heuristic_not_camera_calibration",
                          "maxLocalTempoRatio": config.max_local_tempo_ratio,
                          "timeMap": [{"reference": round(float(r), 6), "practice": round(float(p), 6)}
                                      for r, p in zip(knot_reference, knot_practice)]}
