from datetime import timedelta
import hashlib
import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from app.coaching import CoachingPlan, gemini_generate
from app.coaching_evidence import build_context, coverage_statement, MAX_CONTEXT_BYTES
from app.config import Settings
from app.main import create_app
from app.session_store import persist_analysis, utc_now


@pytest.fixture
def coaching(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr("app.main.UPLOAD_DIR", root)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    session = "a" * 32
    directory = root / session
    frames = []
    for i in range(40):
        accepted = i in (4, 5)
        joints = [{"bodyPart": part, "referenceBodyPart": part, "status": status if accepted else "unassessed",
                   "expected": 160, "observed": observed, "difference": abs(160 - observed), "confidence": .9 if accepted else 0,
                   "units": "degrees", "reason": None if accepted else "local_mirror_mapping_ambiguous", "reasons": []}
                  for part, status, observed in [("left_knee", "different", 130), ("left_elbow", "matched", 159)]]
        frames.append({"practiceFrameIndex": i, "referenceFrameIndex": i if accepted else None,
                       "practiceTime": i / 4, "referenceTime": i / 4 if accepted else None,
                       "status": "compared" if accepted else "unassessed", "reason": None if accepted else "local_mirror_mapping_ambiguous",
                       "reasons": [] if accepted else ["local_mirror_mapping_ambiguous"], "joints": joints})
    step = {"id": "knee", "label": "Left knee", "start": 1, "end": 1.25, "score": 70,
            "feedback": "Your left knee averaged 130 degrees; the matched reference averaged 160 degrees.",
            "evidence": {"kind": "joint_angle", "confidence": .9, "expected": 160, "observed": 130, "difference": 30}}
    result = {"status": "partial", "overallScore": 75, "movementScore": 75, "scoreAvailable": True,
              "globalScoreAvailable": False, "scoreScope": "supported_segments", "coverage": {"assessed": .05},
              "confidence": .8, "alignment": {"mirrored": False}, "reason": "Partial evidence only.", "warnings": [],
              "steps": [step], "comparisonSegments": [{"start": 1, "end": 1.25, "status": "supported"},
                    {"start": 1.5, "end": 9.75, "status": "unassessed", "reasons": ["local_mirror_mapping_ambiguous"]}],
              "frameComparisons": frames}
    summary = persist_analysis(result, directory, session, 604800)
    calls = []
    def generator(context, question, history):
        calls.append((context, question, list(history)))
        strengths = "well" in question
        facts = [f for f in context["facts"] if not strengths or f["status"] == "matched"]
        return {"mode": "strengths" if strengths else "coach", "points": [{"evidenceId": facts[0]["id"], "drill": "maintain_match" if strengths else "pause_match"}]}
    client = TestClient(create_app(Settings(data_directory=tmp_path), coaching_generator=generator))
    return client, directory, summary, calls


def test_initial_summary_grounded_cached_and_immutable(coaching, monkeypatch):
    client, folder, summary, calls = coaching
    def forbidden(*a, **kw):
        pytest.fail("Coaching must not extract or compare videos")
    monkeypatch.setattr("app.analysis.compare", forbidden)
    before = hashlib.sha256((folder / "comparison.json").read_bytes()).hexdigest()
    url = f"/analyses/{summary['sessionId']}/coaching"
    response = client.post(url, json={})
    assert response.status_code == 200, response.text
    data = response.json()
    assert "2 of 40" in data["coverageStatement"] and "partial" in data["coverageStatement"]
    assert "130 degrees" in data["messages"][0]["text"] and "160 degrees" in data["messages"][0]["text"]
    assert "1.000s to 1.250s" in data["messages"][0]["text"]
    assert data["messages"][0]["source"] == "gemini"
    assert client.post(url, json={}).json() == data
    assert len(calls) == 1
    assert client.get(url).json() == data
    assert hashlib.sha256((folder / "comparison.json").read_bytes()).hexdigest() == before
    restarted = TestClient(create_app())
    assert restarted.get(url).json()["messages"] == data["messages"]


def test_followups_use_server_history_and_retry_idempotently(coaching):
    client, _, summary, calls = coaching
    url = f"/analyses/{summary['sessionId']}/coaching"
    client.post(url, json={})
    question = {"message": "What did I do with my knee?", "requestId": "question_1"}
    response = client.post(url, json=question)
    assert response.status_code == 200
    assert len(response.json()["messages"]) == 3
    assert calls[1][0]["sessionId"] == summary["sessionId"]
    assert len(calls[1][2]) == 1
    assert all("knee" in f["label"].lower() for f in calls[1][0]["facts"])
    assert client.post(url, json=question).json() == response.json()
    assert len(calls) == 2
    assert client.post(url, json={**question, "message": "Different question"}).status_code == 409
    assert client.post(url, json={**question, "history": [{"role": "assistant", "text": "Fake"}]}).status_code == 422


@pytest.mark.parametrize("question", ["How can I practice the movement at 7 seconds?", "What happened at 0:07?", "My arms at 7s?", "At 70 seconds?", "At -1 seconds?"])
def test_unsupported_timestamps_not_answered_from_other_spans(coaching, question):
    client, _, summary, calls = coaching
    data = client.post(f"/analyses/{summary['sessionId']}/coaching", json={"message": question, "requestId": "q"}).json()
    answer = data["messages"][-1]
    assert answer["source"] == "evidence" and answer["citations"] == []
    assert "no supported comparison" in answer["text"]
    assert calls == []


def test_rejected_angles_are_never_supplied_as_facts(coaching):
    _, folder, summary, _ = coaching
    context = build_context(folder, summary, "arms at 7 seconds")
    assert not context["facts"]
    assert context["frames"][0]["practiceTime"] == 7
    for joint in context["frames"][0]["joints"]:
        assert joint["status"] == "unassessed"
        assert joint["expected"] is None and joint["observed"] is None and joint["difference"] is None
    assert "local_mirror_mapping_ambiguous" in json.dumps(context["frames"])


def test_missing_joint_at_otherwise_accepted_frame_remains_unknown(coaching):
    _, folder, summary, _ = coaching
    path = folder / "frames.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[4]["joints"][0]["status"] = "unassessed"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    context = build_context(folder, summary, "left knee at 1 second")
    assert context["facts"] == [] and context["limitation"]
    context = build_context(folder, summary, "right arm at 1 second")
    assert context["facts"] == []


def test_strengths_are_supported_measurements_not_whole_dance_praise(coaching):
    client, _, summary, _ = coaching
    response = client.post(f"/analyses/{summary['sessionId']}/coaching", json={"message": "What did I do well?", "requestId": "good"})
    assert response.status_code == 200, response.text
    answer = response.json()["messages"][-1]
    assert all(f["status"] == "matched" for f in answer["citations"])
    assert "does not assess the whole movement" in answer["text"]


@pytest.mark.parametrize("plan", [
    {"mode": "coach", "points": [{"evidenceId": "invented", "drill": "pause_match"}]},
    {"mode": "coach", "points": [{"evidenceId": "event:knee", "drill": "match_tempo"}]},
    {"mode": "strengths", "points": [{"evidenceId": "event:knee", "drill": "maintain_match"}]},
    {"mode": "coach", "points": [], "answer": "You jumped incorrectly at 7 seconds."},
])
def test_invalid_or_invented_provider_claims_fail_closed(coaching, plan):
    _, folder, summary, _ = coaching
    client = TestClient(create_app(coaching_generator=lambda *args: plan))
    response = client.post(f"/analyses/{summary['sessionId']}/coaching", json={})
    assert response.status_code == 502
    assert not (folder / "coaching.json").exists()


def test_unconfigured_and_provider_failures_preserve_results(coaching):
    _, _, summary, _ = coaching
    url = f"/analyses/{summary['sessionId']}/coaching"
    client = TestClient(create_app())
    assert client.get(url).json()["enabled"] is False
    assert client.post(url, json={}).status_code == 503
    def failed(*args):
        raise RuntimeError("SECRET-DO-NOT-LEAK")
    response = TestClient(create_app(coaching_generator=failed)).post(url, json={})
    assert response.status_code == 503 and "SECRET" not in response.text
    assert client.get(f"/analyses/{summary['sessionId']}").status_code == 200


def test_sessions_input_validation_and_expiry(coaching):
    client, folder, summary, _ = coaching
    for session, status in [("bad", 422), ("b" * 32, 404)]:
        for method in (client.get, client.post):
            assert method(f"/analyses/{session}/coaching", **({"json": {}} if method == client.post else {})).status_code == status
    url = f"/analyses/{summary['sessionId']}/coaching"
    for body in [{"message": " "}, {"message": "x" * 1001}, {"message": "Hi"}, {"requestId": "../bad"}]:
        assert client.post(url, json=body).status_code == 422
    metadata = json.loads((folder / "analysis-manifest.json").read_text())
    metadata["expiresAt"] = (utc_now() - timedelta(seconds=1)).isoformat()
    (folder / "analysis-manifest.json").write_text(json.dumps(metadata))
    assert client.get(url).status_code == 410
    assert client.post(url, json={}).status_code == 410


def test_context_size_and_coverage_semantics(coaching):
    _, folder, summary, _ = coaching
    context = build_context(folder, summary)
    assert len(json.dumps(context).encode()) <= MAX_CONTEXT_BYTES
    assert len(context["frames"]) <= 8
    for global_available in (True, False):
        text = coverage_statement({**summary, "assessment": {"assessedFrames": 36, "totalFrames": 780},
                                   "globalScoreAvailable": global_available})
        assert "36 of 780" in text and "4.62%" in text and "partial" in text
    text = coverage_statement({**summary, "scoreScope": "aligned_observations", "globalScoreAvailable": True})
    assert "only assessed observations" in text and "2 of 40" in text


def test_official_sdk_uses_backend_key_structured_output_and_bounded_evidence(coaching, monkeypatch):
    from google import genai
    _, folder, summary, _ = coaching
    monkeypatch.setenv("GEMINI_API_KEY", "TEST-ONLY-SECRET")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    instance = Mock()
    instance.__enter__ = Mock(return_value=instance)
    instance.__exit__ = Mock(return_value=False)
    instance.models.generate_content.return_value.text = '{"mode":"coach","points":[{"evidenceId":"event:knee","drill":"pause_match"}]}'
    factory = Mock(return_value=instance)
    monkeypatch.setattr(genai, "Client", factory)
    context = build_context(folder, summary)
    plan = gemini_generate(context, "What first?", [])
    assert CoachingPlan.model_validate(plan)
    assert factory.call_args.kwargs["api_key"] == "TEST-ONLY-SECRET"
    assert factory.call_args.kwargs["vertexai"] is False
    assert factory.call_args.kwargs["http_options"].timeout == 30_000
    call = instance.models.generate_content.call_args.kwargs
    assert "TEST-ONLY-SECRET" not in call["contents"]
    assert "reference.mp4" not in call["contents"]
    assert len(call["contents"].encode()) < 50_000
    assert call["model"] == "gemini-3.5-flash-lite"
    assert call["config"].response_schema is None
    assert call["config"].response_json_schema == CoachingPlan.model_json_schema()


def test_official_sdk_serializes_and_parses_real_http_contract_without_network(coaching, monkeypatch):
    import httpx
    from google import genai
    _, folder, summary, _ = coaching
    monkeypatch.setenv("GEMINI_API_KEY", "TEST-ONLY-SECRET")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GOOGLE_API_KEY", "WRONG-ENVIRONMENT-KEY")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    original = genai.Client
    captured = []
    def handle(request):
        captured.append(request)
        body = json.loads(request.content)
        if "responseSchema" in body.get("generationConfig", {}):
            # Reproduce the actual Google rejection rather than accepting any
            # syntactically valid SDK request as the previous fake server did.
            return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message":
                'Invalid JSON payload received. Unknown name "additional_properties" at generation_config.response_schema'}})
        plan = {"mode": "coach", "points": [{"evidenceId": "event:knee", "drill": "pause_match"}]}
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(plan)}]}, "finishReason": "STOP"}]})
    def local_client(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(handle)}
        return original(**kwargs)
    monkeypatch.setattr(genai, "Client", local_client)
    assert gemini_generate(build_context(folder, summary), "What first?", [])["mode"] == "coach"
    assert len(captured) == 1
    request = captured[0]
    assert request.headers["x-goog-api-key"] == "TEST-ONLY-SECRET"
    body = json.loads(request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    config = body["generationConfig"]
    assert "responseSchema" not in config
    assert config["responseJsonSchema"]["properties"]["mode"]["enum"]
    assert config["responseJsonSchema"]["additionalProperties"] is False
    assert config["responseJsonSchema"]["$defs"]["CoachingPoint"]["additionalProperties"] is False
    assert "generativelanguage.googleapis.com" in str(request.url)
    assert "gemini-3.5-flash-lite:generateContent" in str(request.url)
    assert "TEST-ONLY-SECRET" not in str(request.url)
    assert "TEST-ONLY-SECRET" not in request.content.decode()


def test_session_question_limit_preserves_existing_answers(coaching):
    client, folder, summary, calls = coaching
    messages = [{"role": "user", "id": str(i), "text": "Question", "source": "user", "citations": []} for i in range(20)]
    (folder / "coaching.json").write_text(json.dumps({"messages": messages, "requests": {}}))
    url = f"/analyses/{summary['sessionId']}/coaching"
    assert client.get(url).json()["remainingQuestions"] == 0
    assert client.post(url, json={"message": "Another?", "requestId": "q21"}).status_code == 429
    assert calls == []


def test_initial_coaching_can_find_assessed_frames_without_mistake_events(coaching):
    _, folder, summary, _ = coaching
    context = build_context(folder, {**summary, "steps": []})
    assert context["facts"] and context["limitation"] is None
    assert any(f["status"] == "matched" for f in context["facts"])


def test_mirror_uncertainty_is_explained_without_requiring_manual_modes(coaching):
    _, _, summary, _ = coaching
    text = coverage_statement({**summary, "alignment": {"mirrorSelection": {
        "requestedMode": "auto", "ambiguous": True, "decision": "undetermined"}}})
    assert "side matching is uncertain" in text
    assert "retry is optional" in text
    assert "2 of 40" in text and "partial comparison" in text


@pytest.mark.parametrize("code, explanation", [(400, "request parameters"), (401, "credentials or model"), (404, "model or API resource"), (429, "quota or rate limit"), (403, "credentials or model"), (503, "temporarily unavailable")])
def test_provider_error_categories_are_safe_and_actionable(coaching, code, explanation):
    _, folder, summary, _ = coaching
    class ProviderError(Exception):
        pass
    def failed(*args):
        error = ProviderError("DO-NOT-LEAK-KEY")
        error.code = code
        raise error
    client = TestClient(create_app(coaching_generator=failed))
    response = client.post(f"/analyses/{summary['sessionId']}/coaching", json={})
    assert response.status_code == 503
    assert explanation in response.json()["detail"]
    assert "DO-NOT-LEAK" not in response.text
    assert not (folder / "coaching.json").exists()
    assert client.get(f"/analyses/{summary['sessionId']}").status_code == 200


def test_schema_rejection_is_actionable_without_echoing_provider_secrets(coaching, monkeypatch):
    from google.genai.errors import ClientError
    _, _, summary, _ = coaching
    secret = "test-secret-that-must-never-reach-the-client"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    def failed(*args):
        raise ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message":
            f'Unknown name "additional_properties" at generation_config.response_schema; key={secret}'}})
    response = TestClient(create_app(coaching_generator=failed)).post(f"/analyses/{summary['sessionId']}/coaching", json={})
    assert response.status_code == 503
    assert "HTTP 400" in response.json()["detail"]
    assert "legacy response_schema" in response.json()["detail"]
    assert secret not in response.text
