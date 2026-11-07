"""Explain measurement masks, paired evidence, and unavailable comparisons."""

from collections import Counter
import math

import numpy as np


def mapped(name, mirrored):
    if mirrored and name.startswith("left_"):
        return "right_" + name[5:]
    if mirrored and name.startswith("right_"):
        return "left_" + name[6:]
    return name


def view_evidence(a, b, config, mirrored):
    if a.axis is None or b.axis is None:
        return {"accepted": False, "agreement": None, "reason": "torso_axis_unavailable",
                "mode": "horizontal_reflection" if mirrored else "same"}
    axis = np.array(b.axis, dtype=float)
    # A mirror hypothesis must transform camera-space geometry as well as swap
    # angle names. Absolute cosine already handles reversing shoulder ordering.
    if mirrored:
        axis[0] *= -1
    norm = np.linalg.norm(a.axis) * np.linalg.norm(axis)
    agreement = abs(float(np.dot(a.axis, axis))) / max(float(norm), 1e-12)
    accepted = math.isfinite(agreement) and agreement >= config.viewpoint_agreement
    return {"accepted": accepted, "agreement": round(agreement, 6),
            "reason": None if accepted else "viewpoint_axis_mismatch",
            "mode": "horizontal_reflection" if mirrored else "same"}


def pair_evidence(a, b, config, mirrored):
    view = view_evidence(a, b, config, mirrored)
    joints, available_weight, confidence_weight, total = {}, 0.0, 0.0, 0.0
    for name, weight in config.weights.items():
        if weight <= 0 or not name.endswith("_angle"):
            continue
        other = mapped(name, mirrored)
        reasons = []
        if name not in a.values:
            reasons += ["reference:" + r for r in a.rejections.get(name, ["feature_unavailable"])]
        elif not config.min_confidence <= a.confidence.get(name, 0) <= 1:
            reasons.append("reference:below_comparison_confidence")
        if other not in b.values:
            reasons += ["practice:" + r for r in b.rejections.get(other, ["feature_unavailable"])]
        elif not config.min_confidence <= b.confidence.get(other, 0) <= 1:
            reasons.append("practice:below_comparison_confidence")
        available = not reasons
        confidence = min(a.confidence[name], b.confidence[other]) if available else 0.0
        total += weight
        if available:
            available_weight += weight
            confidence_weight += weight * confidence
        joints[name] = {"practiceFeature": other, "available": available,
                        "confidence": confidence, "reasons": reasons}
    required = total * config.min_coverage
    mean_confidence = confidence_weight / available_weight if available_weight else 0.0
    angles = available_weight >= required and mean_confidence >= config.min_confidence
    reasons = ([] if angles else ["insufficient_shared_angle_evidence"]) + ([] if view["accepted"] else [view["reason"]])
    return {"accepted": angles and view["accepted"], "angleEvidenceAccepted": angles,
            "view": view, "reasons": reasons, "joints": joints,
            "availableAngleWeight": round(available_weight, 6),
            "confidenceWeightedAngleWeight": round(confidence_weight, 6),
            "meanAngleConfidence": round(mean_confidence, 6),
            "requiredAngleWeight": round(required, 6),
            "angleWeightCoverage": round(available_weight / total, 6) if total else 0.0}


def summarize_pairs(records):
    """Reason counts can overlap; accepted/rejected totals are exclusive."""
    reasons, joints = Counter(), {}
    for record in records:
        reasons.update(record["reasons"])
        for name, joint in record["joints"].items():
            row = joints.setdefault(name, {"available": 0, "missing": 0,
                "accepted": 0, "rejected": 0, "rejectionReasons": Counter()})
            row["practiceFeature"] = joint["practiceFeature"]
            row["available" if joint["available"] else "missing"] += 1
            accepted = joint["available"] and record["accepted"]
            row["accepted" if accepted else "rejected"] += 1
            if not accepted:
                row["rejectionReasons"].update(joint["reasons"] + record["reasons"])
    return {"total": len(records), "accepted": sum(r["accepted"] for r in records),
            "rejected": sum(not r["accepted"] for r in records), "rejectionReasons": dict(reasons),
            "byJoint": {name: {**row, "rejectionReasons": dict(row["rejectionReasons"])} for name, row in joints.items()}}


def source_summary(samples, config):
    result = {}
    for name, weight in config.weights.items():
        if weight <= 0 or not name.endswith("_angle"):
            continue
        reasons = Counter(r for s in samples if name not in s.values
                          for r in s.rejections.get(name, ["feature_unavailable"]))
        accepted = sum(name in s.values for s in samples)
        result[name] = {"accepted": accepted, "rejected": len(samples) - accepted,
                        "rejectionReasons": dict(reasons)}
    return {"frames": len(samples), "torsoAxisUnavailable": sum(s.axis is None for s in samples), "byJoint": result}


def frame_records(reference, practice, config, mirrored=False, pairs=(), accepted=(),
                  reason="alignment_not_supported", alignment_confidence=0.0, frame_reasons=None):
    candidates = {j: i for i, j in pairs}
    assessed = {j: i for i, j in accepted}
    rows = []
    for j, sample in enumerate(practice):
        candidate = candidates.get(j)
        i = assessed.get(j)
        assessment_reasons = (frame_reasons or {}).get(str(j), (frame_reasons or {}).get(j, []))
        if i is None:
            assessment_reasons = list(dict.fromkeys(assessment_reasons + [reason]))
        evidence = pair_evidence(reference[candidate], sample, config, mirrored) if candidate is not None else None
        joints = []
        for name, weight in config.weights.items():
            if weight <= 0 or not name.endswith("_angle"):
                continue
            other = mapped(name, mirrored)
            expected = reference[i].values.get(name) if i is not None else None
            observed = sample.values.get(other)
            available = expected is not None and observed is not None
            difference = observed - expected if available else None
            rejection = [] if available else (evidence["joints"][name]["reasons"] if evidence else
                ["practice:" + r for r in sample.rejections.get(other, [])])
            if not available:
                rejection = list(dict.fromkeys(rejection + ((evidence["reasons"] if evidence else [])
                                                          + assessment_reasons)))
            joints.append({"bodyPart": other.removesuffix("_angle"), "referenceBodyPart": name.removesuffix("_angle"),
                "expected": expected, "observed": observed, "difference": round(abs(difference), 3) if available else None,
                "signedDifference": round(difference, 3) if available else None, "units": "degrees",
                "status": ("different" if abs(difference) >= config.angle_tolerance else "matched") if available else "unassessed",
                "reason": "; ".join(rejection) if rejection else None, "reasons": rejection,
                "confidence": round(min(reference[i].confidence[name], sample.confidence[other]) * alignment_confidence, 4)
                              if available else 0.0})
        rows.append({"practiceTime": sample.time, "practiceFrameIndex": sample.frame_index,
            "referenceTime": reference[i].time if i is not None else None,
            "referenceFrameIndex": reference[i].frame_index if i is not None else None,
            "candidateReferenceTime": reference[candidate].time if candidate is not None else None,
            "candidateReferenceFrameIndex": reference[candidate].frame_index if candidate is not None else None,
            "status": "compared" if i is not None else "unassessed",
            "reason": "; ".join(assessment_reasons) if i is None else None,
            "reasons": assessment_reasons if i is None else [],
            "alignmentEvidence": evidence, "joints": joints})
    return rows


def assessment_segments(rows):
    runs = []
    for row in rows:
        status = "supported" if row["status"] == "compared" else "unassessed"
        if not runs or runs[-1]["status"] != status:
            runs.append({"start": row["practiceTime"], "end": row["practiceTime"],
                         "status": status, "frameCount": 0, "reasons": []})
        run = runs[-1]
        run["end"] = row["practiceTime"]
        run["frameCount"] += 1
        run["reasons"] = list(dict.fromkeys(run["reasons"] + row.get("reasons", [])))
    return runs
