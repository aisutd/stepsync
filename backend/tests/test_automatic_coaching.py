import copy
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.comparison import ComparisonConfig, compare
from app.coaching_evidence import build_context
from app.main import create_app
from app.session_store import persist_analysis
from app.side_independent import validated_facts
from test_side_selection import dance


def bilateral_pair(error=25):
    reference, practice = dance(), dance()
    for rows in (reference, practice):
        for row in rows:
            for key in list(row.values):
                if key.startswith("right_") and "left_" + key[6:] in row.values:
                    row.values[key] = row.values["left_" + key[6:]]
    for row in practice:
        for key in ("left_knee_angle", "right_knee_angle"):
            row.values[key] -= error
    return reference, practice


def save_result(tmp_path, monkeypatch, result, generator):
    root = tmp_path / "uploads"
    monkeypatch.setattr("app.main.UPLOAD_DIR", root)
    session_id = uuid.uuid4().hex
    folder = root / session_id
    summary = persist_analysis({"sessionId": session_id, **result}, folder, session_id, 604800)
    return TestClient(create_app(coaching_generator=generator)), folder, summary


def plan(context):
    matches = [f for f in context["facts"] if f["status"] == "matched"]
    differences = [f for f in context["facts"] if f["status"] == "different"]
    tip = next(iter(differences or matches))
    return {"mode": "summary", "strengths": [f["id"] for f in matches[:1]],
            "points": [{"evidenceId": f["id"], "drill": "slow_repeat"} for f in differences[:1]],
            "practiceTip": {"evidenceId": tip["id"], "drill": "slow_repeat"}}


@pytest.mark.parametrize("mirrored", [False, True])
def test_confident_automatic_mapping_coaches_without_confirmation(tmp_path, monkeypatch, mirrored):
    result = compare(dance(), dance(mirrored=mirrored, error=20))
    assert result["alignment"]["mirrorSelection"]["selectedMapping"] == ("mirrored" if mirrored else "same")
    calls = []
    def generator(context, question, history):
        calls.append(context)
        return plan(context)
    client, folder, summary = save_result(tmp_path, monkeypatch, result, generator)
    response = client.post(f"/analyses/{folder.name}/coaching", json={})
    assert response.status_code == 200, response.text
    assert calls and response.json()["summary"]["practiceTip"]
    assert client.get(summary["links"]["summary"]).json() == summary


def test_ambiguous_mapping_automatically_coaches_only_common_bilateral_ranges(tmp_path, monkeypatch):
    result = compare(*bilateral_pair())
    assert result["alignment"]["mirrorSelection"]["ambiguous"]
    assert result["alignment"]["mirrorSelection"]["selectedMapping"] is None
    assert result["movementScore"] is None and not result["globalScoreAvailable"]
    facts = validated_facts(result["sideIndependentEvidence"])
    assert facts and {f["status"] for f in facts} == {"matched", "different"}
    calls = []
    def generator(context, question, history):
        calls.append(context)
        assert history == []
        assert context["evidenceScope"] == "side_independent"
        assert context["frames"] == [] and context["movementScore"] is None
        assert all(f["kind"] == "bilateral_angle_range" for f in context["facts"])
        assert all(not f["label"].startswith(("left", "right")) for f in context["facts"])
        return plan(context)
    client, folder, summary = save_result(tmp_path, monkeypatch, result, generator)
    before = (folder / "comparison.json").read_bytes()
    url = f"/analyses/{folder.name}/coaching"
    response = client.post(url, json={})
    assert response.status_code == 200, response.text
    view = response.json()["summary"]
    assert view["strengths"] and view["improvements"] and view["practiceTip"]
    assert "few moments" in view["impression"]
    assert "which side you intended" in view["note"]
    assert response.json()["initialReady"]
    assert client.post(url, json={}).json() == response.json()
    assert len(calls) == 1
    # A side-specific question must not be answered using a bilateral aggregate.
    answer = client.post(url, json={"message": "What did my left knee do?", "requestId": "left"}).json()["messages"][-1]
    assert answer["source"] == "evidence" and not answer["citations"]
    assert len(calls) == 1
    assert (folder / "comparison.json").read_bytes() == before
    assert client.get(summary["links"]["summary"]).json()["sideIndependentEvidence"] == result["sideIndependentEvidence"]


@pytest.mark.parametrize("problem", ["static", "missing", "low_confidence", "viewpoint"])
def test_genuinely_insufficient_evidence_gets_helpful_limit_without_provider(tmp_path, monkeypatch, problem):
    reference, practice = bilateral_pair()
    for rows in (reference, practice):
        for row in rows:
            if problem == "static":
                row.values = dict(rows[0].values)
            elif problem == "missing":
                row.values, row.confidence = {}, {}
            elif problem == "low_confidence":
                row.confidence = {key: .1 for key in row.confidence}
            elif problem == "viewpoint" and rows is practice:
                row.axis = (0, 0, 1)
    result = compare(reference, practice)
    assert not validated_facts(result.get("sideIndependentEvidence"))
    def forbidden(*args):
        pytest.fail("No meaningful evidence: do not ask Gemini to invent feedback")
    client, folder, _ = save_result(tmp_path, monkeypatch, result, forbidden)
    response = client.post(f"/analyses/{folder.name}/coaching", json={})
    assert response.status_code == 200, response.text
    view = response.json()["summary"]
    assert not view["strengths"] and not view["improvements"] and view["practiceTip"] is None
    assert "enough" in view["impression"]
    assert "confirm" not in view["impression"].lower()
    assert response.json()["messages"][-1]["source"] == "evidence"


def test_side_independent_range_keeps_both_endpoints_and_never_averages_errors_away():
    reference, practice = bilateral_pair(error=0)
    for row in practice:
        row.values["left_knee_angle"] -= 20
        row.values["right_knee_angle"] += 20
    result = compare(reference, practice)
    facts = validated_facts(result.get("sideIndependentEvidence"))
    knees = [f for f in facts if "knee" in f["label"]]
    assert knees and all(f["status"] == "different" for f in knees)


def test_candidate_time_maps_must_agree_on_observed_reference_sample(monkeypatch):
    import app.comparison as module
    original = module.align
    def disagree(reference, practice, config, mirrored):
        path, cost, diagnostics = original(reference, practice, config, mirrored)
        if mirrored:
            path = [(min(i + 1, len(reference) - 1), j) for i, j in path]
        return path, cost, diagnostics
    monkeypatch.setattr(module, "align", disagree)
    result = compare(*bilateral_pair(error=0))
    assert result["alignment"]["mirrorSelection"]["ambiguous"]
    assert not validated_facts(result.get("sideIndependentEvidence"))


def test_bad_or_missing_independent_evidence_never_reuses_candidate_side_facts(tmp_path, monkeypatch):
    result = compare(*bilateral_pair())
    def forbidden(*args):
        pytest.fail("Malformed evidence must fail closed")
    _, folder, summary = save_result(tmp_path, monkeypatch, result, forbidden)
    for change in ("missing", "confidence", "status", "unsupported_time", "side_label"):
        candidate = copy.deepcopy(summary)
        if change == "missing":
            candidate.pop("sideIndependentEvidence")
        else:
            evidence = candidate["sideIndependentEvidence"]
            evidence["facts"] = evidence["facts"][:1]
            fact = evidence["facts"][0]
            if change == "confidence": fact["confidence"] = .1
            elif change == "status": fact["status"] = "fabricated"
            elif change == "unsupported_time": fact["start"] = fact["end"] = 500
            else: fact["label"] = "left knee"
        context = build_context(folder, candidate)
        assert not context["facts"] and context["limitation"]


def test_old_blocking_cache_is_refreshed_once_without_deleting_saved_history(tmp_path, monkeypatch):
    calls = []
    def generator(context, question, history):
        calls.append(context)
        assert history == []
        return plan(context)
    client, folder, _ = save_result(tmp_path, monkeypatch, compare(*bilateral_pair()), generator)
    old = {"id": "old", "role": "assistant", "source": "evidence", "text": "Confirm sides first.", "citations": []}
    (folder / "coaching.json").write_text(json.dumps({"messages": [old], "requests": {"initial": None}}))
    url = f"/analyses/{folder.name}/coaching"
    initial = client.get(url).json()
    assert not initial["initialReady"] and not initial["messages"]
    first = client.post(url, json={})
    assert first.status_code == 200
    assert first.json()["initialReady"] and first.json()["summary"]["practiceTip"]
    assert client.post(url, json={}).json() == first.json()
    assert len(calls) == 1
    assert json.loads((folder / "coaching.json").read_text())["messages"][0] == old
