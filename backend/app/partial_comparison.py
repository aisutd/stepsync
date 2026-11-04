"""Recover locally evidenced movement spans without relaxing global thresholds."""

import numpy as np

from .comparison_diagnostics import mapped, pair_evidence


def motion_correlation(reference, practice, pairs, config, mirrored):
    correlations = []
    for name, weight in config.weights.items():
        if weight <= 0 or not name.endswith("_angle"):
            continue
        other = mapped(name, mirrored)
        values = [(reference[i].values[name], practice[j].values[other]) for i, j in pairs
                  if name in reference[i].values and other in practice[j].values]
        if len(values) < 8:
            continue
        a, b = np.array(values).T
        if np.std(a) >= 8:
            correlations.append(float(np.corrcoef(a, b)[0, 1]) if np.std(b) >= 3 else 0.0)
    return float(np.median(correlations)) if correlations else None


def _brackets(anchors, time):
    times = [a["practiceTime"] for a in anchors]
    index = int(np.searchsorted(times, time))
    if index < len(times) and abs(times[index] - time) < 1e-5:
        return [anchors[index]]
    if index == 0 or index == len(times):
        return []
    return [anchors[index - 1], anchors[index]]


def local_support(reference, practice, path, diagnostics, config, mirrored, alternative=None,
                  mirror_ambiguous=False):
    """Only spans with measured, bracketing anchors and local motion evidence."""
    anchors = diagnostics.get("anchorDiagnostics", [])
    if not anchors:
        return [], [], {}
    runs, run, reasons = [], [], {}
    typical = float(np.median(np.diff([s.time for s in practice])))
    for i, j in path:
        evidence = pair_evidence(reference[i], practice[j], config, mirrored)
        bracket = _brackets(anchors, practice[j].time)
        why = list(evidence["reasons"])
        if not bracket or any(not a["accepted"] for a in bracket):
            why.append("unsupported_bracketing_anchors")
        elif any(a["alignmentCost"] > config.max_alignment_cost for a in bracket):
            why.append("local_alignment_cost_too_high")
        if why:
            reasons[j] = why
            if run:
                runs.append(run)
                run = []
            continue
        if run and (j != run[-1][1] + 1 or practice[j].time - practice[run[-1][1]].time > typical * 2.1):
            runs.append(run)
            run = []
        run.append((i, j))
    if run:
        runs.append(run)
    accepted, segments = [], []
    for run in runs:
        start, end = practice[run[0][1]].time, practice[run[-1][1]].time
        why = []
        if end - start < config.min_partial_seconds:
            why.append("supported_span_too_short")
        correlation = motion_correlation(reference, practice, run, config, mirrored)
        if correlation is None:
            why.append("insufficient_local_motion_evidence")
        elif correlation < 0.2:
            why.append("local_motion_order_mismatch")
        measured = [a["alignmentCost"] for a in anchors if start <= a["practiceTime"] <= end and a["accepted"]]
        mean_cost = float(np.mean(measured)) if measured else None
        margin = None
        if mirror_ambiguous:
            common = []
            for a in anchors:
                if not start <= a["practiceTime"] <= end or not a["accepted"]:
                    continue
                others = _brackets(alternative.get("anchorDiagnostics", []), a["practiceTime"]) if alternative else []
                if others and all(o["accepted"] for o in others):
                    common.append(float(np.mean([o["alignmentCost"] for o in others])) - a["alignmentCost"])
            margin = float(np.mean(common)) if common else None
            if len(common) < max(3, len(measured) * config.min_coverage) or margin is None or margin < 0.015:
                why.append("local_mirror_mapping_ambiguous")
        supported = not why
        segments.append({"start": start, "end": end,
            "referenceStart": reference[run[0][0]].time, "referenceEnd": reference[run[-1][0]].time,
            "status": "supported" if supported else "unassessed", "reasons": why,
            "mirrored": mirrored,
            "mirrorDecision": "locally_supported" if supported and mirror_ambiguous else "undetermined" if mirror_ambiguous else "global_or_explicit_mapping",
            "frameCount": len(run), "motionCorrelation": round(correlation, 4) if correlation is not None else None,
            "meanAlignmentCost": round(mean_cost, 4) if mean_cost is not None else None,
            "mirrorCostMargin": round(margin, 4) if margin is not None else None})
        if supported:
            accepted.extend(run)
        else:
            for _, j in run:
                reasons[j] = why
    return accepted, segments, reasons
