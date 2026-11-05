"""Small, confidence-aware comparison layer over Lucy's feature calculations.

Scores describe observed movement only. Coverage and alignment confidence are
separate; none of the scores is a calibrated probability or dance grade.
"""

from dataclasses import dataclass, field
import math

import numpy as np

from features import compute_features
from features.angles import FEATURES
from .temporal import align
from .comparison_diagnostics import pair_evidence, source_summary, summarize_pairs, frame_records, assessment_segments
from .partial_comparison import local_support, motion_correlation
from .side_selection import select_mapping
from .side_independent import side_independent_evidence


@dataclass(frozen=True)
class ComparisonConfig:
    # Editable per choreography; keys are Lucy's feature names.
    weights: dict[str, float] = field(default_factory=lambda: {
        **{f.name: (3.0 if "knee" in f.name or "hip" in f.name else 2.0)
           for f in FEATURES},
        "left_wrist_speed": 0.3, "right_wrist_speed": 0.3,
        "left_ankle_speed": 0.6, "right_ankle_speed": 0.6,
        **{f.name.replace("_angle", "_velocity"): 0.25 for f in FEATURES},
    })
    sample_hz: float = 10.0
    max_samples: int = 600
    band_fraction: float = 0.25
    min_confidence: float = 0.65
    min_coverage: float = 0.5
    min_seconds: float = 0.5
    angle_tolerance: float = 15.0
    angle_scale: float = 90.0
    velocity_scale: float = 180.0
    speed_scale: float = 2.0  # torso lengths / second
    segment_seconds: float = 0.3
    timing_tolerance: float = 0.25
    mirror_mode: str = "auto"  # auto, same, mirrored
    alignment_angle_scale: float = 45.0
    max_local_tempo_ratio: int = 2
    gap_cost: float = 0.1
    clock_penalty: float = 0.1
    stretch_penalty: float = 0.04
    max_alignment_cost: float = 0.4
    viewpoint_agreement: float = 0.85
    max_observation_gap_seconds: float = 0.15
    min_partial_seconds: float = 1.0
    mirror_window_seconds: float = 1.0
    mirror_margin_degrees: float = 5.0
    mirror_min_windows: int = 3

    def __post_init__(self):
        known = {f.name for f in FEATURES}
        known |= {f.name.replace("_angle", "_velocity") for f in FEATURES}
        known |= {f"{side}_{joint}_speed" for side in ("left", "right")
                  for joint in ("wrist", "ankle")}
        if not self.weights or set(self.weights) - known:
            raise ValueError("Use known angle, velocity, or speed feature weights.")
        if any(not math.isfinite(w) or w < 0 for w in self.weights.values()):
            raise ValueError("Weights must be finite and nonnegative.")
        if not any(w > 0 and k.endswith("_angle") for k, w in self.weights.items()):
            raise ValueError("At least one angle must have positive weight for alignment.")
        for name in ("sample_hz", "min_seconds", "angle_tolerance", "angle_scale",
                     "velocity_scale", "speed_scale", "segment_seconds", "timing_tolerance",
                     "alignment_angle_scale", "max_observation_gap_seconds", "gap_cost",
                     "clock_penalty", "stretch_penalty", "min_partial_seconds", "mirror_window_seconds", "mirror_margin_degrees"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite.")
        for name in ("min_confidence", "min_coverage", "band_fraction", "viewpoint_agreement", "max_alignment_cost"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0, 1].")
        if self.max_samples < 3 or self.mirror_mode not in {"auto", "same", "mirrored"}:
            raise ValueError("Invalid sample limit or mirror mode.")
        if not isinstance(self.max_local_tempo_ratio, int) or not 1 <= self.max_local_tempo_ratio <= 4:
            raise ValueError("Local tempo ratio must be an integer from 1 to 4.")
        if not isinstance(self.mirror_min_windows, int) or self.mirror_min_windows < 2:
            raise ValueError("Mirror selection requires at least two independent windows.")


@dataclass
class Sample:
    time: float
    values: dict
    confidence: dict
    # Shoulder axis in camera coordinates; useful only as a conservative gate.
    axis: tuple | None = None
    frame_index: int | None = None
    rejections: dict = field(default_factory=dict)


def _torso(frame):
    names = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
    points = [frame.landmarks.get(n) for n in names]
    if any(p is None or not p.reliable or p.world is None for p in points):
        return None, None
    shoulder = (np.array(points[0].world) + points[1].world) / 2
    hip = (np.array(points[2].world) + points[3].world) / 2
    length = float(np.linalg.norm(shoulder - hip))
    axis = np.array(points[1].world) - points[0].world
    norm = np.linalg.norm(axis)
    return (length if length > 1e-6 else None,
            tuple(axis / norm) if norm > 1e-6 else None)


def samples_from_frames(frames, config, *, sample=True):
    """Keep Lucy's math unchanged; attach confidence and normalize speed units."""
    if not frames:
        return []
    times = [f.timestamp_ms / 1000 for f in frames]
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Pose timestamps must increase strictly.")
    doc = compute_features("comparison", frames)
    definitions = {f["name"]: f["joints"] for f in doc["feature_definitions"]}
    by_frame = {f.frame_index: Sample(t, {}, {}, frame_index=f.frame_index) for f, t in zip(frames, times)}
    frame_map = {f.frame_index: f for f in frames}
    indices = {f.frame_index: i for i, f in enumerate(frames)}
    from features.velocity import FRAME_GAP

    for row in doc["rows"]:
        name, index = row["feature"], row["frame_index"]
        if name not in config.weights:
            continue
        sample_row = by_frame[index]
        if row["status"] != "ok":
            sample_row.rejections[name] = [row.get("missing_reason") or "feature_unavailable"]
            continue
        frame = frame_map[index]
        involved = [frame]
        if not name.endswith("_angle"):
            pos = indices[index]
            if pos < FRAME_GAP:
                continue
            involved = frames[pos - FRAME_GAP:pos + 1]
            # Never derive velocity through an occlusion or a large timestamp gap.
            if any((b.timestamp_ms - a.timestamp_ms) > 250 for a, b in zip(involved, involved[1:])):
                continue
        joints = definitions[name]
        if name.endswith("_speed"):
            joints = joints + ["left_hip", "right_hip", "left_shoulder", "right_shoulder"]
        landmarks = [f.landmarks.get(j) for f in involved for j in joints]
        if any(p is None or not p.reliable or p.world is None for p in landmarks):
            sample_row.rejections[name] = ["unreliable_or_missing_landmark:" + joint
                for joint in joints if any(f.landmarks.get(joint) is None
                    or not f.landmarks[joint].reliable or f.landmarks[joint].world is None for f in involved)]
            continue
        confidence = min(p.confidence for p in landmarks)
        value = row["value"]
        if confidence < config.min_confidence or not math.isfinite(value):
            sample_row.rejections[name] = ["below_comparison_confidence" if confidence < config.min_confidence else "nonfinite_feature"]
            continue
        if name.endswith("_speed"):
            scale, _ = _torso(frame)
            if scale is None:
                continue
            value /= scale
        by_frame[index].values[name] = value
        by_frame[index].confidence[name] = confidence
    for f in frames:
        by_frame[f.frame_index].axis = _torso(f)[1]
    if not sample:
        return list(by_frame.values())
    # Source samples, never interpolation across missing measurements.
    interval = max(1 / config.sample_hz, (times[-1] - times[0]) / (config.max_samples - 1))
    selected, previous = [], -math.inf
    for sample in by_frame.values():
        bucket = math.floor((sample.time - times[0]) / interval + 1e-7)
        if bucket > previous:
            selected.append(sample)
            previous = bucket
    # Preserve the last source timestamp for duration/timing calculations.
    last = by_frame[frames[-1].frame_index]
    if selected[-1].time != last.time:
        if len(selected) >= config.max_samples:
            selected[-1] = last
        else:
            selected.append(last)
    return selected[:config.max_samples]


def _mapped(name, mirrored):
    if not mirrored:
        return name
    if name.startswith("left_"):
        return "right_" + name[5:]
    return "left_" + name[6:] if name.startswith("right_") else name


def _coverage(samples, config):
    total = sum(config.weights.values())
    return round(sum(sum(config.weights.get(k, 0) for k in s.values) / total for s in samples)
                 / max(len(samples), 1), 4)


def _reliable_samples(samples, config):
    """Do not let direct feature callers bypass the CSV adapter's quality mask."""
    cleaned = []
    for s in samples:
        values = {k: v for k, v in s.values.items()
                  if k in config.weights and math.isfinite(v)
                  and math.isfinite(s.confidence.get(k, 0))
                  and config.min_confidence <= s.confidence.get(k, 0) <= 1
                  and (not k.endswith("_angle") or 0 <= v <= 180)}
        axis = np.asarray(s.axis, dtype=float) if s.axis is not None else None
        if axis is not None:
            norm = np.linalg.norm(axis)
            axis = tuple(axis / norm) if axis.shape == (3,) and np.isfinite(axis).all() and norm > 0 else None
        rejections = {k: list(v) for k, v in s.rejections.items()}
        for k in config.weights:
            if k not in values and k not in rejections:
                rejections[k] = ["feature_unavailable" if k not in s.values else
                                 "below_comparison_confidence" if s.confidence.get(k, 0) < config.min_confidence else "invalid_feature_or_confidence"]
        cleaned.append(Sample(s.time, values, {k: s.confidence[k] for k in values}, axis, s.frame_index, rejections))
    return cleaned


def compare(reference, practice, config=None):
    """Return frontend-compatible feedback plus structured measurement evidence."""
    config = config or ComparisonConfig()
    reference, practice = (_reliable_samples(s, config) for s in (reference, practice))
    result = {"overallScore": 0.0, "movementScore": None, "reason": None,
              "frameComparisons": [], "steps": [], "status": "insufficient_data",
              "comparisonSegments": [], "scoreScope": "none", "globalScoreAvailable": False,
              "diagnostics": {"reference": source_summary(reference, config),
                              "practice": source_summary(practice, config),
                              "thresholds": {"measurementConfidence": config.min_confidence,
                                  "minimumSharedAngleWeightFraction": config.min_coverage,
                                  "supportedAnchorFraction": config.min_coverage,
                                  "viewpointAgreement": config.viewpoint_agreement,
                                  "maximumAlignmentCost": config.max_alignment_cost,
                                  "minimumPartialSeconds": config.min_partial_seconds}},
              "scoreAvailable": False, "confidence": 0.0,
              "coverage": {"reference": _coverage(reference, config),
                           "practice": _coverage(practice, config), "compared": 0.0, "assessed": 0.0},
              "alignment": {}, "warnings": [
                  "Scores are heuristic movement similarity, not calibrated dance grades.",
                  "Use the same routine with similar camera views; 3D pose estimates can be inaccurate."]}
    selected_path, selected_mirrored = [], False
    def abstain(message, status="insufficient_data"):
        result["status"] = status
        result["reason"] = message
        result["warnings"].append(message)
        result["frameComparisons"] = frame_records(reference, practice, config, selected_mirrored,
            pairs=selected_path, reason=message,
            frame_reasons=result["diagnostics"].get("frameRejections", {}))
        result["comparisonSegments"] = assessment_segments(result["frameComparisons"])
        return result
    if min(len(reference), len(practice)) < 3:
        return abstain("Too few pose samples to compare.")
    for samples in (reference, practice):
        if any(not math.isfinite(s.time) for s in samples) or any(b.time <= a.time for a, b in zip(samples, samples[1:])):
            return abstain("Source pose timestamps must be finite and strictly increasing.")
    rd = reference[-1].time - reference[0].time
    pd = practice[-1].time - practice[0].time
    if min(rd, pd) < config.min_seconds or not 0.5 <= pd / rd <= 2:
        return abstain("Clips are too short or their duration ratio exceeds the supported 0.5–2 range.")
    source_low = min(result["coverage"]["reference"], result["coverage"]["practice"]) < config.min_coverage
    if not any(s.values for s in reference) or not any(s.values for s in practice):
        return abstain("Insufficient reliable pose coverage; record your whole body clearly.")
    modes = [False, True] if config.mirror_mode == "auto" else [config.mirror_mode == "mirrored"]
    candidates = [(*align(reference, practice, config, mode), mode) for mode in modes]
    # Compare objectives on the same normalized duration, including neutral gaps;
    # conditional means on different sets of accepted anchors are not comparable.
    path, alignment_cost, diagnostics, mirrored = min(candidates,
        key=lambda x: x[2].get("objectiveCost", math.inf))
    selection_evidence = None
    selected_mapping = None
    if config.mirror_mode == "auto":
        selected_mapping, selection_evidence = select_mapping(reference, practice, candidates, config)
        if selected_mapping is not None:
            path, alignment_cost, diagnostics, mirrored = next(c for c in candidates if c[3] == selected_mapping)
    selected_path, selected_mirrored = path, mirrored
    alternative = next((c[2] for c in candidates if c[3] != mirrored), None)
    candidate_summaries = [{"mirrored": c[3], "meanCost": c[1] if math.isfinite(c[1]) else None,
        "objectiveCost": c[2].get("objectiveCost"), "supportedAnchorFraction": c[2].get("supportedAnchorFraction"),
        "anchorRejections": c[2].get("anchorRejections")} for c in candidates]
    objective_margin = (abs(candidates[0][2].get("objectiveCost", 0) - candidates[1][2].get("objectiveCost", 0))
                        if len(candidates) == 2 else None)
    ambiguous_mirror = config.mirror_mode == "auto" and selected_mapping is None
    result["alignment"] = {"method": "slope_constrained_dtw", **diagnostics,
        "mirrored": mirrored, "durationRatio": round(pd / rd, 4),
        "meanCost": round(alignment_cost, 4) if math.isfinite(alignment_cost) else None,
        "weights": config.weights, "bandFraction": config.band_fraction,
        "mirrorSelection": {"requestedMode": config.mirror_mode, "ambiguous": ambiguous_mirror,
            "decision": "undetermined" if ambiguous_mirror else "user_specified" if config.mirror_mode != "auto" else "selected",
            "objectiveMargin": round(objective_margin, 6) if objective_margin is not None else None,
            "selectedMapping": ("mirrored" if mirrored else "same") if not ambiguous_mirror else None,
            "reason": ("Reliable left/right movement evidence is insufficient or inconsistent across the choreography. Manual side selection is optional."
                       if ambiguous_mirror else "Consistent asymmetric movement evidence supports the selected side mapping."
                       if config.mirror_mode == "auto" else "Side mapping supplied by the user."),
            "selectionEvidence": selection_evidence,
            "candidates": candidate_summaries}}
    if ambiguous_mirror:
        result["sideIndependentEvidence"] = side_independent_evidence(reference, practice, candidates, config)
    if not path:
        return abstain("No time map satisfies the configured timing constraints.", "uncertain_alignment")
    pair_records = [pair_evidence(reference[i], practice[j], config, mirrored) for i, j in path]
    result["diagnostics"]["pairedObservations"] = summarize_pairs(pair_records)
    valid = [p for p, evidence in zip(path, pair_records) if evidence["accepted"]]
    compared = len(valid) / len(practice)
    result["coverage"]["compared"] = round(compared, 4)
    global_reasons = []
    if source_low:
        global_reasons.append("insufficient reliable source coverage")
    if diagnostics.get("supportedAnchorFraction", 0) < config.min_coverage:
        global_reasons.append("too few supported anchors")
    if ambiguous_mirror:
        global_reasons.append("ambiguous global mirror mapping")
    if alignment_cost > config.max_alignment_cost:
        global_reasons.append("excessive alignment cost")
    if compared < config.min_coverage:
        global_reasons.append("too few comparable practice frames")
    correlation = motion_correlation(reference, practice, valid, config, mirrored)
    result["alignment"]["motionCorrelation"] = round(correlation, 4) if correlation is not None else None
    if correlation is not None and correlation < 0.2:
        return abstain("Observed movement order does not support a reliable choreography alignment.",
                       "uncertain_alignment")
    local_pairs, segments, frame_reasons = local_support(reference, practice, path, diagnostics,
        config, mirrored, alternative=alternative, mirror_ambiguous=ambiguous_mirror)
    result["diagnostics"]["localSegments"] = segments
    result["diagnostics"]["frameRejections"] = {str(j): why for j, why in frame_reasons.items()}
    bracket_valid = [(i, j) for i, j in valid if not any(
        r in {"unsupported_bracketing_anchors", "local_alignment_cost_too_high"}
        for r in frame_reasons.get(j, []))]
    if len(bracket_valid) / len(practice) < config.min_coverage:
        global_reasons.append("too few locally supported practice frames")
    partial = bool(global_reasons)
    if partial:
        valid = local_pairs
        result["comparisonSegments"] = [s for s in segments if s["status"] == "supported"]
        if not valid:
            result["diagnostics"]["globalRejectionReasons"] = global_reasons
            view_failure = (not math.isfinite(alignment_cost))
            return abstain("Global comparison withheld: " + "; ".join(global_reasons)
                           + ". No independently supported movement span met the local evidence checks.",
                           "uncertain_viewpoint" if view_failure else "uncertain_alignment")
        result["reason"] = "Only independently supported movement spans are scored; the whole-video comparison is unavailable."
        result["warnings"].append(result["reason"])
    else:
        # A globally usable map can still contain unsupported local intervals.
        valid = bracket_valid
        if not valid:
            return abstain("No practice frames have reliable local alignment support.", "uncertain_alignment")
    if mirrored:
        result["warnings"].append("Best match swaps left/right and reflects camera-space axes; labels name the practice side.")
    assessed_fraction = len(valid) / len(practice)
    result["coverage"]["assessed"] = round(assessed_fraction, 4)
    result["diagnostics"]["globalRejectionReasons"] = global_reasons
    numerator = denominator = 0.0
    confidences, events = [], {}
    practice_times = np.array([s.time for s in practice])
    # Integrate over observed time, not the camera's number of frames.
    widths = np.diff(practice_times)
    typical_step = float(np.median(widths))
    widths = np.minimum(widths, typical_step * 2)
    durations = (np.r_[widths[0], widths] + np.r_[widths, widths[-1]]) / 2
    knots = result["alignment"]["timeMap"]
    kt = [k["practice"] for k in knots]
    kr = [k["reference"] for k in knots]
    for i, j in valid:
        a, b = reference[i], practice[j]
        lo, hi = max(practice[0].time, b.time - 0.25), min(practice[-1].time, b.time + 0.25)
        mapped_lo, mapped_hi = np.interp([lo, hi], kt, kr)
        tempo_ratio = (hi - lo) / max(mapped_hi - mapped_lo, 1e-6)
        for name, weight in config.weights.items():
            other = _mapped(name, mirrored)
            if weight <= 0 or name not in a.values or other not in b.values:
                continue
            confidence = min(a.confidence[name], b.confidence[other])
            expected, observed = a.values[name], b.values[other]
            if name.endswith("_angle"):
                scale = config.angle_scale
            else:
                # Remove supported local execution-speed differences using the
                # time-map slope, keeping timing separate from movement residuals.
                observed *= tempo_ratio
                scale = config.velocity_scale if name.endswith("_velocity") else config.speed_scale
            delta = abs(expected - observed)
            effective = weight * confidence * durations[j]
            numerator += effective * min(delta / scale, 1)
            denominator += effective
            confidences.append(confidence)
            if name.endswith("_angle") and delta >= config.angle_tolerance:
                events.setdefault(other, []).append((j, i, expected, observed, confidence))
    if denominator == 0:
        return abstain("No reliable measurements overlap.")
    result.update(status="partial" if partial else "completed", scoreAvailable=True,
                  scoreScope="supported_segments" if partial else "aligned_observations", globalScoreAvailable=not partial,
                  overallScore=round(100 * (1 - numerator / denominator), 2),
                  confidence=round(float(np.mean(confidences)) * assessed_fraction * (1 - alignment_cost), 4))
    result["movementScore"] = result["overallScore"]
    result["frameComparisons"] = frame_records(reference, practice, config, mirrored, pairs=path,
        accepted=valid, reason="unsupported_local_alignment" if partial else "unreliable_paired_pose",
        alignment_confidence=1 - alignment_cost, frame_reasons=frame_reasons)
    if not partial:
        result["comparisonSegments"] = assessment_segments(result["frameComparisons"])
    else:
        result["comparisonSegments"] += [s for s in assessment_segments(result["frameComparisons"]) if s["status"] == "unassessed"]
        result["comparisonSegments"].sort(key=lambda s: s["start"])
    if partial:
        for segment in result["comparisonSegments"]:
            if segment["status"] != "supported":
                continue
            indices = {j for _, j in valid if segment["start"] <= practice[j].time <= segment["end"]}
            errors = []
            for i, j in valid:
                if j not in indices:
                    continue
                for name, weight in config.weights.items():
                    other = _mapped(name, mirrored)
                    if name.endswith("_angle") and weight > 0 and name in reference[i].values and other in practice[j].values:
                        w = weight * min(reference[i].confidence[name], practice[j].confidence[other]) * durations[j]
                        errors.append((w, min(abs(reference[i].values[name] - practice[j].values[other]) / config.angle_scale, 1)))
            segment["angleScore"] = round(100 * (1 - sum(w * e for w, e in errors) / sum(w for w, _ in errors)), 2)
    for name, rows in events.items():
        runs, run = [], []
        for row in rows:
            # Gaps in pose data or below-threshold differences split feedback.
            if run and (row[0] != run[-1][0] + 1 or
                        (row[2] - row[3]) * (run[-1][2] - run[-1][3]) < 0 or
                        practice[row[0]].time - practice[run[-1][0]].time > max(2.1 / config.sample_hz, 2.1 * typical_step)):
                runs.append(run)
                run = []
            run.append(row)
        if run:
            runs.append(run)
        for run in runs:
            start, end = practice[run[0][0]].time, practice[run[-1][0]].time
            if end - start + 1e-8 < config.segment_seconds:
                continue
            expected = float(np.mean([r[2] for r in run]))
            observed = float(np.mean([r[3] for r in run]))
            delta = abs(expected - observed)
            body = name.removesuffix("_angle").replace("_", " ")
            evidence = {"kind": "position", "bodyPart": body,
                        "referenceBodyPart": _mapped(name, mirrored).removesuffix("_angle").replace("_", " "),
                        "referenceStart": reference[run[0][1]].time,
                        "referenceEnd": reference[run[-1][1]].time,
                        "expected": round(expected, 2), "observed": round(observed, 2),
                        "difference": round(delta, 2), "units": "degrees",
                        "severity": "major" if delta >= 30 else "moderate",
                        "confidence": round(min(r[4] for r in run) * (1 - alignment_cost), 4)}
            result["steps"].append({"id": str(len(result["steps"]) + 1), "label": body.title(),
                "start": start, "end": end, "score": round(100 * (1 - min(delta / config.angle_scale, 1)), 2),
                "feedback": f"Your {body} averaged {observed:.0f}°; the matched reference averaged {expected:.0f}°. "
                            f"Try {'straightening/opening' if expected > observed else 'bending/closing'} this joint toward the reference position.",
                "evidence": evidence})
    # Motion variation is needed to support timing claims. No audio/beat inference.
    motion = max((np.std([s.values[k] for s in reference if k in s.values])
                  for k in config.weights if k.endswith("_angle")
                  and sum(k in s.values for s in reference) >= 3), default=0)
    if not partial and motion >= 10 and alignment_cost < 0.15:
        offsets = [practice[j].time - practice[0].time - (reference[i].time - reference[0].time)
                   for i, j in valid]
        offset = float(np.median(offsets))
        result["alignment"]["medianTimingOffsetSeconds"] = round(offset, 3)
        if abs(pd / rd - 1) > 0.1 or abs(offset) > config.timing_tolerance:
            result["steps"].append({"id": str(len(result["steps"]) + 1), "label": "Movement timing",
                "start": practice[valid[0][1]].time, "end": practice[valid[-1][1]].time,
                "score": round(max(0, 100 * (1 - abs(pd / rd - 1))), 2),
                "feedback": f"Matched movements take {pd / rd:.2f} times the reference duration. "
                            "Practice matching the reference pace.",
                "evidence": {"kind": "timing", "durationRatio": round(pd / rd, 4),
                             "medianOffsetSeconds": round(offset, 3),
                             "confidence": result["confidence"], "severity": "moderate"}})
        # Residual timing after removing global clip speed reveals early/late
        # movement segments even when overall durations are equal.
        runs, run = [], []
        for i, j in valid:
            local_offset = (practice[j].time - practice[0].time
                            - (reference[i].time - reference[0].time) * pd / rd)
            if abs(local_offset) < config.timing_tolerance:
                if run:
                    runs.append(run)
                    run = []
                continue
            if run and (j != run[-1][1] + 1 or local_offset * run[-1][2] < 0):
                runs.append(run)
                run = []
            run.append((i, j, local_offset))
        if run:
            runs.append(run)
        for run in runs:
            start, end = practice[run[0][1]].time, practice[run[-1][1]].time
            if end - start < config.segment_seconds:
                continue
            local_offset = float(np.median([r[2] for r in run]))
            result["steps"].append({"id": str(len(result["steps"]) + 1), "label": "Local movement timing",
                "start": start, "end": end, "score": round(100 * max(0, 1 - abs(local_offset)), 2),
                "feedback": f"These movements occur about {abs(local_offset):.2f} seconds "
                            f"{'later' if local_offset > 0 else 'earlier'} than the matched reference pace.",
                "evidence": {"kind": "timing", "timingType": "local_offset",
                    "referenceStart": reference[run[0][0]].time, "referenceEnd": reference[run[-1][0]].time,
                    "offsetSeconds": round(local_offset, 3), "units": "seconds",
                    "severity": "major" if abs(local_offset) >= 0.5 else "moderate",
                    "confidence": result["confidence"]}})
    else:
        result["warnings"].append("Timing feedback withheld: motion or alignment evidence is insufficient.")
    result["steps"].sort(key=lambda step: (step["start"], step["label"]))
    return result
