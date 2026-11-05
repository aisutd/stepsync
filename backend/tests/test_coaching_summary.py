import hashlib
import json

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.coaching import gemini_generate
from app.coaching_evidence import build_context
from app.coaching_summary import make_summary
from test_coaching import coaching


def summary_plan(context, question, history):
    matched = next(f for f in context["facts"] if f["status"] == "matched")
    different = next(f for f in context["facts"] if f["status"] == "different")
    return {"mode": "summary", "strengths": [matched["id"]],
            "points": [{"evidenceId": different["id"], "drill": "isolate_joint"}],
            "practiceTip": {"evidenceId": different["id"], "drill": "slow_repeat"}}


def test_concise_summary_preserves_measurements_and_uses_only_cited_facts(coaching):
    _, folder, summary, _ = coaching
    before = hashlib.sha256((folder / "comparison.json").read_bytes()).hexdigest()
    client = TestClient(create_app(coaching_generator=summary_plan))
    url = f"/analyses/{summary['sessionId']}/coaching"
    response = client.post(url, json={})
    assert response.status_code == 200, response.text
    data = response.json()
    view = data["summary"]
    assert "next practice" in view["impression"]
    assert len(view["strengths"]) == len(view["improvements"]) == 1
    assert "left elbow" in view["strengths"][0]
    assert "left knee" in view["improvements"][0]
    assert "slowly" in view["practiceTip"]
    assert "only compare parts" in view["note"]
    assert "degrees" not in json.dumps(view)
    facts = data["messages"][0]["citations"]
    assert all(f["start"] in (1, 1.25) for f in facts)
    assert "7s" not in json.dumps(view)
    assert client.get(url).json()["summary"] == view
    assert client.post(url, json={}).json() == data
    assert hashlib.sha256((folder / "comparison.json").read_bytes()).hexdigest() == before


@pytest.mark.parametrize("change", [
    {"strengths": ["event:knee"]},
    {"points": [{"evidenceId": "frame:4:left_elbow", "drill": "pause_match"}]},
    {"practiceTip": {"evidenceId": "invented", "drill": "slow_repeat"}},
    {"impression": "Perfect whole-video dancing!"},
])
def test_summary_invented_or_misclassified_findings_fail_closed(coaching, change):
    _, folder, summary, _ = coaching
    def generator(context, question, history):
        return {**summary_plan(context, question, history), **change}
    client = TestClient(create_app(coaching_generator=generator))
    assert client.post(f"/analyses/{summary['sessionId']}/coaching", json={}).status_code == 502
    assert not (folder / "coaching.json").exists()


def test_legacy_cached_coaching_gets_summary_without_provider_or_history_rewrite(coaching):
    client, folder, summary, calls = coaching
    url = f"/analyses/{summary['sessionId']}/coaching"
    assert client.post(url, json={}).status_code == 200
    before = (folder / "coaching.json").read_bytes()
    view = client.get(url).json()["summary"]
    assert view["improvements"]
    assert view["strengths"] == []
    assert len(calls) == 1
    assert (folder / "coaching.json").read_bytes() == before


def test_ambiguous_side_convention_does_not_call_gemini_or_praise_movement(coaching):
    client, folder, summary, calls = coaching
    summary["alignment"]["mirrorSelection"] = {"ambiguous": True, "requestedMode": "auto"}
    (folder / "summary.json").write_text(json.dumps(summary))
    response = client.post(f"/analyses/{summary['sessionId']}/coaching", json={})
    assert response.status_code == 200
    view = response.json()["summary"]
    assert "couldn't compare enough" in view["impression"]
    assert not view["strengths"] and not view["improvements"] and view["practiceTip"] is None
    assert calls == []


def test_uncertainty_notes_do_not_invent_camera_findings(coaching):
    _, _, summary, _ = coaching
    view = make_summary(summary)
    assert "camera" not in (view["note"] or "").lower()
    view = make_summary({**summary, "status": "uncertain_viewpoint", "scoreAvailable": False})
    assert "camera views" in view["note"]
    assert not view["strengths"] and not view["improvements"]


def test_summary_tip_can_reuse_a_validated_selected_improvement(coaching):
    _, _, summary, _ = coaching
    def generator(context, question, history):
        plan = summary_plan(context, question, history)
        del plan["practiceTip"]
        return plan
    client = TestClient(create_app(coaching_generator=generator))
    response = client.post(f"/analyses/{summary['sessionId']}/coaching", json={})
    assert response.status_code == 200
    assert "comfortable range" in response.json()["summary"]["practiceTip"]


def test_provider_payload_excludes_raw_frames_and_files(coaching, monkeypatch):
    from unittest.mock import Mock
    from google import genai
    _, folder, summary, _ = coaching
    context = build_context(folder, summary)
    context["frames"] = [{"image": "PRIVATE-RAW-FRAME"}]
    context["video"] = "PRIVATE-RAW-VIDEO"
    context["diagnostics"] = {"path": "PRIVATE-FILE-PATH"}
    instance = Mock()
    instance.__enter__ = Mock(return_value=instance)
    instance.__exit__ = Mock(return_value=False)
    instance.models.generate_content.return_value.text = json.dumps(summary_plan(context, "", []))
    monkeypatch.setattr(genai, "Client", Mock(return_value=instance))
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    gemini_generate(context, "Initial summary", [])
    payload = instance.models.generate_content.call_args.kwargs["contents"]
    assert "PRIVATE-" not in payload
    assert "frames" not in json.loads(payload)["evidence"]
    assert json.loads(payload)["evidence"]["facts"]
