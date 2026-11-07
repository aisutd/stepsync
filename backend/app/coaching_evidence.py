"""Small, auditable coaching context built from immutable engine results.

Never treat an available angle as assessed unless both its frame and joint were
accepted. Scan JSONL on the server; no full diagnostic blob goes to Gemini.
"""

import json
import math
import re

from .session_store import _artifact
from .coaching_summary import needs_side_choice
from .side_independent import validated_facts

MAX_EVENTS = 8
MAX_FRAMES = 8
MAX_CONTEXT_BYTES = 40_000


def requested_time(message):
    clock = re.search(r"\b(\d{1,2}):(\d{2}(?:\.\d+)?)\b", message)
    if clock:
        return int(clock[1]) * 60 + float(clock[2])
    seconds = re.search(r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b", message, re.I)
    if seconds:
        return float(seconds[1])
    at = re.search(r"\bat\s+(-?\d+(?:\.\d+)?)\b", message, re.I)
    return float(at[1]) if at else None


def body_filter(message):
    groups = {"arm": ("shoulder", "elbow", "wrist"), "leg": ("hip", "knee", "ankle"),
              "torso": ("hip", "shoulder")}
    found = {part for part in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")
             if re.search(r"\b" + part + r"s?\b", message, re.I)}
    for word, parts in groups.items():
        if re.search(r"\b" + word + r"s?\b", message, re.I):
            found.update(parts)
    return found


def supported(summary, start, end):
    return (summary.get("scoreAvailable") is True
            and summary.get("assessment", {}).get("assessedFrames", 0) > 0
            and any(s.get("status") == "supported" and s["start"] <= start <= end <= s["end"]
                    for s in summary.get("comparisonSegments", [])))


def coverage_statement(summary):
    counts = summary.get("assessment") or {}
    total, assessed = counts.get("totalFrames", 0), counts.get("assessedFrames", 0)
    scope = ("This is a partial comparison, limited to supported segments."
             if summary.get("scoreScope") == "supported_segments" else
             "Analysis-wide eligibility passed; the score still covers only assessed observations."
             if summary.get("globalScoreAvailable") else "No reliable movement score is available.")
    selection = summary.get("alignment", {}).get("mirrorSelection", {})
    mirror_note = (" Automatic left/right side matching is uncertain. Unsupported sections remain unassessed. "
                   "A manual same/mirrored retry is optional."
                   if selection.get("ambiguous") is True or selection.get("decision") == "undetermined" else "")
    return (f"{assessed} of {total} practice frames ({100 * assessed / total if total else 0:.2f}%) were assessed. "
            f"{scope} Unassessed movements are not judged.{mirror_note}")


def build_context(directory, summary, message="", previous_ids=()):
    if needs_side_choice(summary):
        return side_independent_context(summary, message)
    target = requested_time(message)
    parts = body_filter(message)
    side = next((s for s in ("left", "right") if re.search(r"\b" + s + r"\b", message, re.I)), None)
    matches = lambda label: ((not parts or any(p in label.lower() for p in parts))
                             and (side is None or side in label.lower()))
    events = [s for s in summary.get("steps", []) if matches(s["label"])
              and supported(summary, s["start"], s["end"])
              and s.get("evidence", {}).get("status") != "unassessed"
              and (target is None or s["start"] <= target <= s["end"])]
    events.sort(key=lambda s: (s["score"], s["start"]))
    available_events = len(events)
    events = events[:MAX_EVENTS]
    # Even spacing plus event midpoints provides sparse context; timestamp
    # questions retrieve nearest native frames regardless of their status.
    rows_needed = summary.get("assessment", {}).get("totalFrames", 0)
    indices = {round(i * max(0, rows_needed - 1) / 3) for i in range(4)}
    times = [target] if target is not None else [(s["start"] + s["end"]) / 2 for s in events[:4]]
    nearest = [None] * len(times)
    sampled = []
    sampled_spans = set()
    with _artifact(directory, "frames.jsonl").open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            row = json.loads(line)
            span = next((i for i, s in enumerate(summary.get("comparisonSegments", []))
                         if s.get("status") == "supported" and s["start"] <= row["practiceTime"] <= s["end"]), None)
            first_supported = row.get("status") == "compared" and span is not None and span not in sampled_spans and len(sampled_spans) < 4
            if first_supported:
                sampled_spans.add(span)
            if target is None and (first_supported or index in indices or any(f"frame:{row.get('practiceFrameIndex')}:" in eid for eid in previous_ids)):
                if len(sampled) < MAX_FRAMES:
                    sampled.append(row)
            for i, time in enumerate(times):
                if nearest[i] is None or abs(row["practiceTime"] - time) < abs(nearest[i]["practiceTime"] - time):
                    nearest[i] = row
    selected = {r["practiceTime"]: r for r in [*nearest, *sampled] if r is not None}
    selected = list(selected.values())[:MAX_FRAMES]
    facts, frames = [], []
    for event in events:
        evidence = event.get("evidence", {})
        facts.append({"id": f"event:{event['id']}", "kind": evidence.get("kind", "joint_angle"),
                      "status": "different", "label": event["label"], "start": event["start"], "end": event["end"],
                      "fact": f"From {event['start']:.3f}s to {event['end']:.3f}s: {event['feedback']}",
                      "score": event["score"], "measurements": evidence})
    for row in selected:
        accepted = row.get("status") == "compared" and supported(summary, row["practiceTime"], row["practiceTime"])
        frame = {k: row.get(k) for k in ("practiceFrameIndex", "practiceTime", "referenceFrameIndex", "referenceTime", "status", "reason", "reasons")}
        frame["joints"] = []
        for joint in row.get("joints", []):
            if not matches(joint["bodyPart"]):
                continue
            valid = accepted and joint["status"] in ("matched", "different") and all(
                isinstance(joint.get(k), (int, float)) and math.isfinite(joint[k])
                for k in ("expected", "observed", "difference"))
            item = {k: joint.get(k) for k in ("bodyPart", "referenceBodyPart", "status", "confidence", "reason", "reasons", "units")}
            item.update({k: joint.get(k) if valid else None for k in ("expected", "observed", "difference")})
            if not valid:
                item["status"] = "unassessed"
            frame["joints"].append(item)
            if valid:
                label = joint["bodyPart"].replace("_", " ")
                ref_label = joint.get("referenceBodyPart", joint["bodyPart"]).replace("_", " ")
                facts.append({"id": f"frame:{row['practiceFrameIndex']}:{joint['bodyPart']}",
                              "kind": "joint_angle", "status": joint["status"], "label": label,
                              "start": row["practiceTime"], "end": row["practiceTime"], "measurements": item,
                              "fact": f"At {row['practiceTime']:.3f}s, your {label} measured {joint['observed']:.1f} degrees; "
                                      f"the aligned reference {ref_label} measured {joint['expected']:.1f} degrees "
                                      f"(difference {joint['difference']:.1f} degrees). "
                                      + ("The engine marked this measurement as matched. " if joint["status"] == "matched" else "The engine marked this measurement as different. ")
                                      + "This observation does not assess the whole movement."})
        frames.append(frame)
    # A precise unsupported-time question must not be answered from another span.
    limitation = None
    if target is not None:
        near = nearest[0]
        observed_near = near is not None and any(f["id"].startswith(f"frame:{near['practiceFrameIndex']}:") for f in facts)
        if near is None or abs(near["practiceTime"] - target) > .1 or not supported(summary, target, target) or not observed_near:
            facts = []
            limitation = f"There is no supported comparison at {target:.3f}s. No correctness judgment can be made there."
    if not facts:
        limitation = limitation or "The saved comparison does not provide supported measurements for this question. I cannot judge that movement from this evidence."
    context = {"sessionId": summary["sessionId"], "coverageStatement": coverage_statement(summary),
               **{k: summary.get(k) for k in ("status", "scoreScope", "globalScoreAvailable", "movementScore", "assessment", "coverage", "confidence", "alignment", "reason", "warnings")},
               "segments": [{k: s.get(k) for k in ("start", "end", "status", "reasons")} for s in summary.get("comparisonSegments", [])[:32]],
               "segmentCount": len(summary.get("comparisonSegments", [])),
               "selection": {"requestedTime": target, "bodyParts": sorted(parts), "sampledFrames": len(frames),
                             "availableEvents": available_events, "includedEvents": len(events),
                             "note": "Sparse evidence selection, not a complete transcript of the dance."},
               "facts": facts, "frames": frames, "limitation": limitation}
    # Defend the request budget even for unusually verbose persisted events.
    if len(json.dumps(context).encode()) > MAX_CONTEXT_BYTES:
        context["frames"] = []
        context["facts"] = facts[:8]
    context["selection"]["includedFrames"] = len(context["frames"])
    context["selection"]["omittedFacts"] = len(facts) - len(context["facts"])
    if len(json.dumps(context).encode()) > MAX_CONTEXT_BYTES:
        raise ValueError("Coaching evidence exceeds the bounded request budget.")
    return context


def side_independent_context(summary, message):
    """An ambiguous convention NEVER borrows the chosen candidate's side facts."""
    target, parts = requested_time(message), body_filter(message)
    asks_side = re.search(r"\b(left|right)\b", message, re.I)
    facts = [fact for fact in validated_facts(summary.get("sideIndependentEvidence"))
             if not asks_side and (not parts or any(part in fact["label"] for part in parts))
             and (target is None or abs(fact["start"] - target) <= .1)]
    limitation = None if facts else (
        "Individual movement sides could not be identified reliably. I cannot give left/right corrections."
        if asks_side else "There isn't enough reliably aligned, side-independent evidence for useful movement feedback. "
        "Try two clips of the same section with your full body visible and a similar camera view.")
    return {"sessionId": summary["sessionId"], "coverageStatement":
            "Only bilateral angle ranges on an alignment supported under both mappings are available. "
            "Individual sides and overall similarity are not assessed by this evidence.",
            "status": summary.get("status"), "scoreAvailable": False, "movementScore": None,
            "scoreScope": "none", "globalScoreAvailable": False, "evidenceScope": "side_independent",
            "alignment": {"mirrorSelection": summary.get("alignment", {}).get("mirrorSelection", {})},
            "selection": {"requestedTime": target, "bodyParts": sorted(parts),
                          "note": "Only bilateral ranges on a common, locally validated alignment. No individual-side or timing claims."},
            "facts": facts, "frames": [], "limitation": limitation}
