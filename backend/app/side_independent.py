"""Coaching-only bilateral ranges on alignment supported under BOTH mappings.

This does not select a side convention, score a dance, or rescue rejected
left/right measurements. Sorting two observed angles is invariant to swapping
their sides; both endpoints are retained so opposing errors cannot average out.
"""

import math

from .partial_comparison import local_support, motion_correlation

METHOD = "bilateral_ranges_common_alignment_v1"
MAX_FACTS = 24


def side_independent_evidence(reference, practice, candidates, config):
    result = {"method": METHOD, "facts": [], "supportedSegments": [],
              "thresholds": {"minimumConfidence": config.min_confidence,
                             "angleTolerance": config.angle_tolerance,
                             "minimumSpanSeconds": config.min_partial_seconds},
              "scope": "Bilateral ranges only; not individual sides, timing, or a movement score."}
    maps, supported_spans = {}, {}
    for path, _, diagnostics, mirrored in candidates:
        pairs, spans, _ = local_support(reference, practice, path, diagnostics, config, mirrored)
        maps[mirrored] = {j: i for i, j in pairs}
        supported_spans[mirrored] = [span for span in spans if span["status"] == "supported"]
    if not all(mode in maps for mode in (False, True)):
        return result
    common = [(i, j) for j, i in sorted(maps[False].items()) if maps[True].get(j) == i]
    runs, previous_spans = [], None
    for pair in common:
        time = practice[pair[1]].time
        spans = tuple(next(index for index, span in enumerate(supported_spans[mode])
                           if span["start"] <= time <= span["end"]) for mode in (False, True))
        if not runs or pair[1] != runs[-1][-1][1] + 1 or spans != previous_spans:
            runs.append([])
        runs[-1].append(pair)
        previous_spans = spans
    families = [(name, "right_" + name[5:]) for name, weight in config.weights.items()
                if name.startswith("left_") and name.endswith("_angle") and weight > 0
                and config.weights.get("right_" + name[5:], 0) > 0]
    for run in runs:
        start, end = (practice[run[index][1]].time for index in (0, -1))
        if end - start < config.min_partial_seconds:
            continue
        correlations = [motion_correlation(reference, practice, run, config, mode) for mode in (False, True)]
        if any(value is None or not math.isfinite(value) or value < .2 for value in correlations):
            continue
        result["supportedSegments"].append({"start": start, "end": end})
        # Bound the coaching payload. These are observed moments, not invented
        # events or an interpolation of landmark/joint measurements.
        for index in sorted({0, len(run) // 2, len(run) - 1}):
            i, j = run[index]
            a, b = reference[i], practice[j]
            for left, right in families:
                if any(name not in s.values or not math.isfinite(s.values[name])
                       or not config.min_confidence <= s.confidence.get(name, 0) <= 1
                       for s in (a, b) for name in (left, right)):
                    continue
                expected = sorted((a.values[left], a.values[right]))
                observed = sorted((b.values[left], b.values[right]))
                differences = [abs(x - y) for x, y in zip(expected, observed)]
                status = "different" if max(differences) >= config.angle_tolerance else "matched"
                family = left.removeprefix("left_").removesuffix("_angle")
                label = f"{family} angle range across both {'legs' if family in ('hip', 'knee') else 'arms'}"
                fact = {"id": f"bilateral:{j}:{family}", "kind": "bilateral_angle_range",
                        "scope": "side_independent", "status": status, "label": label,
                        "start": b.time, "end": b.time, "referenceTime": a.time,
                        "confidence": min(s.confidence[name] for s in (a, b) for name in (left, right)),
                        "measurements": {"expectedRange": expected, "observedRange": observed,
                                         "endpointDifferences": differences, "units": "degrees"},
                        "fact": f"At {b.time:.3f}s, the sorted {family} angles across both limbs were "
                                f"{observed[0]:.1f}–{observed[1]:.1f} degrees; the common aligned reference "
                                f"range was {expected[0]:.1f}–{expected[1]:.1f} degrees. This range was {status}. "
                                "This does not identify individual sides or assess adjacent movement."}
                if len(result["facts"]) < MAX_FACTS:
                    result["facts"].append(fact)
    return result


def validated_facts(evidence):
    """Fail closed on incomplete/legacy evidence before exposing it to coaching."""
    if not isinstance(evidence, dict) or evidence.get("method") != METHOD:
        return []
    thresholds = evidence.get("thresholds", {})
    confidence = thresholds.get("minimumConfidence")
    tolerance = thresholds.get("angleTolerance")
    duration = thresholds.get("minimumSpanSeconds")
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
           for v in (confidence, tolerance, duration)):
        return []
    valid = []
    for fact in evidence.get("facts", [])[:MAX_FACTS]:
        try:
            if fact["scope"] != "side_independent" or fact["kind"] != "bilateral_angle_range":
                continue
            if "left" in fact["label"].lower() or "right" in fact["label"].lower():
                continue
            if not confidence <= fact["confidence"] <= 1:
                continue
            if not math.isfinite(fact["start"]) or fact["start"] != fact["end"]:
                continue
            if not any(span["start"] <= fact["start"] <= span["end"]
                       and span["end"] - span["start"] >= duration
                       for span in evidence["supportedSegments"]):
                continue
            measurements = fact["measurements"]
            expected, observed = measurements["expectedRange"], measurements["observedRange"]
            if len(expected) != 2 or len(observed) != 2 or any(not math.isfinite(v) for v in [*expected, *observed]):
                continue
            different = max(abs(a - b) for a, b in zip(expected, observed)) >= tolerance
            if fact["status"] != ("different" if different else "matched"):
                continue
            valid.append(fact)
        except (KeyError, TypeError, ValueError):
            continue
    return valid
