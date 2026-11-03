"""Choose one global side convention from shared asymmetric movement evidence.

DTW costs deliberately tolerate dancer-specific offsets. They rank time maps,
but cannot by themselves establish left/right correspondence. Neither assessed
frame counts nor final movement scores participate in this selector.
"""

import math
import numpy as np

from .comparison_diagnostics import pair_evidence
from .partial_comparison import motion_correlation, _brackets


def select_mapping(reference, practice, candidates, config):
    by_mode = {c[3]: c for c in candidates}
    audits = []
    for path, cost, diagnostics, mirrored in candidates:
        valid = [(i, j) for i, j in path if pair_evidence(reference[i], practice[j], config, mirrored)["accepted"]]
        correlation = motion_correlation(reference, practice, valid, config, mirrored)
        viable = (bool(valid) and math.isfinite(cost) and cost <= config.max_alignment_cost
                  and diagnostics.get("supportedAnchorFraction", 0) >= config.min_coverage
                  and correlation is not None and correlation >= .2)
        audits.append({"mirrored": mirrored, "eligible": viable, "motionCorrelation": correlation,
                       "supportedAnchorFraction": diagnostics.get("supportedAnchorFraction", 0),
                       "meanAlignmentCost": cost if math.isfinite(cost) else None,
                       "pairedCoverage": len(valid) / len(practice)})
    maps = {mode: {j: i for i, j in candidate[0]} for mode, candidate in by_mode.items()}
    windows, contrasts, seen = {}, {False: {}, True: {}}, set()
    families = [(name, "right_" + name[5:], min(weight, config.weights.get("right_" + name[5:], 0)))
                for name, weight in config.weights.items() if name.startswith("left_") and name.endswith("_angle") and weight > 0]
    common_frames = 0
    duration_scale = max(reference[-1].time - reference[0].time,
                         practice[-1].time - practice[0].time) / (practice[-1].time - practice[0].time)
    for j in sorted(set(maps[False]) & set(maps[True])):
        time = practice[j].time - practice[0].time
        bucket = int(time * config.sample_hz + 1e-7)
        if bucket in seen:
            continue  # Correlated high-FPS duplicates are not additional votes.
        seen.add(bucket)
        refs = {mode: reference[maps[mode][j]] for mode in (False, True)}
        p = practice[j]
        if not all(pair_evidence(refs[mode], p, config, mode)["accepted"] for mode in (False, True)):
            continue
        brackets = [_brackets(by_mode[mode][2].get("anchorDiagnostics", []), p.time) for mode in (False, True)]
        if any(not bracket or any(not a["accepted"] or a["alignmentCost"] is None
                                  or a["alignmentCost"] > config.max_alignment_cost for a in bracket)
               for bracket in brackets):
            continue
        common_frames += 1
        # Global execution speed must not remove independent choreography
        # windows merely because the practice recording finishes faster.
        window = int(time * duration_scale / config.mirror_window_seconds)
        for left, right, weight in families:
            if weight <= 0 or any(left not in s.values or right not in s.values for s in (*refs.values(), p)):
                continue
            confidence = min(s.confidence[k] for s in (*refs.values(), p) for k in (left, right))
            pc = p.values[left] - p.values[right]
            rc = {mode: r.values[left] - r.values[right] for mode, r in refs.items()}
            for mode in (False, True):
                contrasts[mode].setdefault(left, []).append((rc[mode], -pc if mode else pc))
            # Near-symmetric measurements cannot establish a side convention.
            if min(abs(pc), *(abs(v) for v in rc.values())) < config.angle_tolerance / 2:
                continue
            losses = {mode: min(abs(rc[mode] - (-pc if mode else pc)) / 2, config.angle_scale) for mode in (False, True)}
            row = windows.setdefault(window, {"start": p.time, "end": p.time, "weight": 0., "margin": 0., "families": set(), "observations": 0})
            row["end"] = p.time
            row["weight"] += weight * confidence
            row["margin"] += weight * confidence * (losses[True] - losses[False])
            row["families"].add(left)
            row["observations"] += 1
    correlations = {}
    dynamic_families = {False: set(), True: set()}
    for mode, groups in contrasts.items():
        values = []
        for family, pairs in groups.items():
            if len(pairs) < 8:
                continue
            a, b = np.array(pairs).T
            if np.std(a) >= 3 and np.std(b) >= 3:
                values.append(float(np.corrcoef(a, b)[0, 1]))
                dynamic_families[mode].add(family)
        correlations[mode] = float(np.median(values)) if values else None
    evidence = []
    for window, row in sorted(windows.items()):
        if row["weight"] and row["end"] - row["start"] >= config.min_seconds / 2:
            evidence.append({"window": window, "start": row["start"], "end": row["end"],
                             "marginDegrees": row["margin"] / row["weight"],
                             "families": sorted(row["families"]), "observations": row["observations"]})
    margins = [w["marginDegrees"] for w in evidence]
    median = float(np.median(margins)) if margins else 0.
    winner = median < 0
    sign = -1 if winner else 1
    consistency = sum(sign * v >= config.mirror_margin_degrees for v in margins) / max(len(margins), 1)
    families_seen = {f for w in evidence for f in w["families"]} & dynamic_families[winner]
    reasons = []
    if len(evidence) < config.mirror_min_windows or len(families_seen) < 2:
        reasons.append("insufficient_independent_asymmetric_movement_windows")
    if abs(median) < config.mirror_margin_degrees or consistency < .75:
        reasons.append("side_preferences_too_close_or_inconsistent")
    if not next(a["eligible"] for a in audits if a["mirrored"] == winner):
        reasons.append("preferred_mapping_has_insufficient_temporal_or_pose_support")
    wc, lc = correlations[winner], correlations[not winner]
    if wc is None or lc is None or wc < .35 or wc - lc < .2:
        reasons.append("insufficient_discriminative_left_right_motion_agreement")
    return (None if reasons else winner), {"method": "shared_asymmetric_movement_windows", "reasons": reasons,
        "commonReliableSamples": common_frames, "informativeWindows": len(evidence),
        "windowConsistency": round(consistency, 4), "medianSameAdvantageDegrees": round(median, 4),
        "bilateralMotionCorrelation": {"same": correlations[False], "mirrored": correlations[True]},
        "thresholds": {"minimumWindows": config.mirror_min_windows, "windowSeconds": config.mirror_window_seconds,
                       "windowClock": "duration_normalized_choreography",
                       "minimumMarginDegrees": config.mirror_margin_degrees, "minimumWindowConsistency": .75,
                       "minimumBilateralCorrelation": .35, "minimumCorrelationAdvantage": .2},
        "candidateEvidence": audits, "windows": evidence}
