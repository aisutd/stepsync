"""Short presentation of validated coaching evidence; never visual inference."""


def needs_side_choice(summary):
    selection = (summary.get("alignment") or {}).get("mirrorSelection") or {}
    return selection.get("ambiguous") is True or selection.get("decision") == "undetermined"


def summary_overview(summary):
    if needs_side_choice(summary):
        if summary.get("evidenceScope") == "side_independent" and summary.get("facts"):
            return "Here's a simple practice plan based on a few moments I could compare."
        return "I couldn't compare enough of the movement to give useful feedback yet."
    if not summary.get("scoreAvailable"):
        return "I couldn't compare enough of the movement to give useful feedback yet."
    if summary.get("scoreScope") == "supported_segments":
        return "Let's focus your next practice on a few useful moments."
    return "Here's what to keep and what to practice next."


def uncertainty_note(summary):
    if needs_side_choice(summary):
        if summary.get("evidenceScope") == "side_independent" and summary.get("facts"):
            return "This feedback covers only these moments; I couldn't tell which side you intended to follow."
        return "Try filming the same short section with your whole body in view and a similar camera angle."
    if summary.get("status") == "uncertain_viewpoint":
        return "I couldn't get a clear comparison from these camera views. Try recording from a similar angle."
    counts = summary.get("assessment") or {}
    if counts.get("unassessedFrames", 0) > 0 or summary.get("scoreScope") == "supported_segments":
        return "I could only compare parts of the routine, so this isn't a judgment of the whole dance."
    if not summary.get("scoreAvailable"):
        return "Try filming the same short section with your whole body in view."
    return None


def moment(fact):
    start, end = fact["start"], fact["end"]
    start, end = round(start), round(end)
    unit = "second" if start == 1 else "seconds"
    return f"around {start} {unit}" if start == end else f"between about {start} and {end} seconds"


def plain_focus(fact):
    """Translate an existing measurement label, without adding visual findings."""
    if fact["kind"] == "bilateral_angle_range":
        family = fact["label"].split()[0].lower()
        return {"knee": "the range of your knee bends", "elbow": "the range of your elbow bends",
                "hip": "the amount of bend at your hips", "shoulder": "the range of your arm angles"}.get(
                    family, "the measured movement range")
    return "your " + fact["label"].lower().replace("_", " ").removesuffix(" angle") + " position"


def checkpoint(fact):
    if fact["kind"] == "bilateral_angle_range":
        focus = plain_focus(fact)
        return (f"{focus[0].upper() + focus[1:]} was close to the reference {moment(fact)}."
                if fact["status"] == "matched" else
                f"Focus on matching {focus} to the reference {moment(fact)}.")
    if fact["kind"] == "timing":
        return f"Practice matching the reference pace {moment(fact)}."
    if fact["status"] == "matched":
        focus = plain_focus(fact)
        return f"{focus[0].upper() + focus[1:]} was close to the reference {moment(fact)}."
    return f"Focus on matching {plain_focus(fact)} to the reference {moment(fact)}."


def practice_tip(fact, drill):
    focus = plain_focus(fact)
    where = moment(fact)
    if fact["kind"] == "bilateral_angle_range":
        return f"Pause both videos {where}, compare {focus}, then repeat that short section slowly and comfortably."
    return {
        "pause_match": f"Pause both videos {where}, compare {focus}, then try it slowly.",
        "slow_repeat": f"Repeat the short section {where} slowly, focusing on {focus}, then build back up to pace.",
        "isolate_joint": f"Try {focus} {where} in a comfortable range, then add the surrounding movement. Don't force it.",
        "match_tempo": f"Loop the section {where} with the reference and practice its pace.",
        "maintain_match": f"Use {focus} {where} as a checkpoint when repeating the section.",
    }[drill]


def make_summary(context, strengths=(), improvements=(), tip=None):
    allowed = (context.get("scoreAvailable") is True and not needs_side_choice(context)) or (
        context.get("evidenceScope") == "side_independent" and bool(context.get("facts")))
    return {"presentationVersion": 2, "impression": summary_overview(context),
            "strengths": [checkpoint(f) for f in strengths][:2] if allowed else [],
            "improvements": [checkpoint(f) for f in improvements][:2] if allowed else [],
            "practiceTip": practice_tip(*tip) if tip and allowed else None,
            "note": uncertainty_note(context)}


def limitation_summary(text, context):
    """Keep a validated provider limitation visible instead of a positive intro."""
    return {"presentationVersion": 2, "impression": text, "strengths": [],
            "improvements": [], "practiceTip": None, "note": uncertainty_note(context)}


def legacy_summary(message, summary):
    """Present cached coaching without another provider call or rewriting history."""
    facts = [f for f in message.get("citations", []) if f.get("status") in ("matched", "different")
             and all(k in f for k in ("kind", "label", "start", "end"))]
    strengths = [f for f in facts if f["status"] == "matched"]
    improvements = [f for f in facts if f["status"] == "different"]
    fact = next(iter(improvements or strengths), None)
    drill = "match_tempo" if fact and fact["kind"] == "timing" else "pause_match"
    return make_summary(summary, strengths, improvements, (fact, drill) if fact else None)
