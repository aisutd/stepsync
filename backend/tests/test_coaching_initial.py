import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from test_coaching import coaching
from test_coaching_summary import summary_plan


@pytest.mark.parametrize("empty", [{"mode": "summary"}, {"mode": "coach", "points": []},
                                   {"mode": "strengths", "points": []}])
def test_empty_initial_plan_is_retryable_and_never_cached(coaching, empty):
    _, folder, summary, _ = coaching
    calls = []
    def generator(context, question, history):
        calls.append(context)
        return empty if len(calls) == 1 else summary_plan(context, question, history)
    client = TestClient(create_app(coaching_generator=generator))
    url = f"/analyses/{summary['sessionId']}/coaching"
    before = (folder / "comparison.json").read_bytes()
    assert client.post(url, json={}).status_code == 502
    assert not (folder / "coaching.json").exists()
    assert client.get(url).json()["initialReady"] is False
    response = client.post(url, json={})
    assert response.status_code == 200
    data = response.json()
    assert data["initialReady"] and data["summary"]["practiceTip"]
    assert len(data["messages"]) == 1
    assert len(calls) == 2
    assert client.post(url, json={}).json() == data
    assert len(calls) == 2
    assert (folder / "comparison.json").read_bytes() == before


@pytest.mark.parametrize("mode", ["limitation", "off_topic"])
def test_explicit_provider_limitations_remain_visible_and_idempotent(coaching, mode):
    _, folder, summary, _ = coaching
    calls = []
    def generator(*args):
        calls.append(args)
        return {"mode": mode, "points": []}
    client = TestClient(create_app(coaching_generator=generator))
    url = f"/analyses/{summary['sessionId']}/coaching"
    response = client.post(url, json={})
    assert response.status_code == 200
    data = response.json()
    message = data["messages"][0]
    assert message["outcome"] == mode
    assert data["initialMessageId"] == message["id"]
    assert data["summary"]["impression"] == message["text"]
    assert not data["summary"]["strengths"] and not data["summary"]["improvements"]
    assert data["summary"]["practiceTip"] is None
    assert data["initialReady"]
    assert client.get(url).json() == data
    assert client.post(url, json={}).json() == data
    assert len(calls) == 1


def test_followup_before_initial_never_becomes_the_initial_summary(coaching):
    client, _, summary, calls = coaching
    url = f"/analyses/{summary['sessionId']}/coaching"
    followup = client.post(url, json={"message": "What did I do well?", "requestId": "first"})
    assert followup.status_code == 200
    first = followup.json()
    assert first["initialReady"] is False and first["initialMessageId"] is None
    assert first["summary"] is None
    response = client.post(url, json={})
    assert response.status_code == 200
    data = response.json()
    initial = data["messages"][-1]
    assert initial["initial"] is True
    assert data["initialMessageId"] == initial["id"] != first["messages"][-1]["id"]
    assert data["summary"]["improvements"]
    assert client.get(url).json() == data
    assert client.post(url, json={}).json() == data
    assert len(calls) == 2
    later = client.post(url, json={"message": "My knee?", "requestId": "later"}).json()
    assert later["initialMessageId"] == data["initialMessageId"]
    assert later["summary"] == data["summary"]


def test_legacy_initial_without_flag_remains_cached_without_history_changes(coaching):
    client, folder, summary, calls = coaching
    url = f"/analyses/{summary['sessionId']}/coaching"
    data = client.post(url, json={}).json()
    state = json.loads((folder / "coaching.json").read_text())
    del state["messages"][0]["initial"]
    (folder / "coaching.json").write_text(json.dumps(state))
    before = (folder / "coaching.json").read_bytes()
    assert client.get(url).json()["initialMessageId"] == data["initialMessageId"]
    assert client.post(url, json={}).json()["summary"] == data["summary"]
    assert len(calls) == 1
    assert (folder / "coaching.json").read_bytes() == before


def test_old_empty_success_is_refreshed_without_deleting_history(coaching):
    client, folder, summary, calls = coaching
    old = {"id": "empty", "role": "assistant", "source": "gemini", "initial": True,
           "text": "A plan without any points", "citations": []}
    (folder / "coaching.json").write_text(json.dumps({"messages": [old], "requests": {"initial": None}}))
    url = f"/analyses/{summary['sessionId']}/coaching"
    assert client.get(url).json()["initialReady"] is False
    response = client.post(url, json={})
    assert response.status_code == 200
    data = response.json()
    assert data["initialReady"]
    assert data["initialMessageId"] != old["id"]
    assert data["summary"]["practiceTip"]
    assert data["messages"][0] == old
    assert client.post(url, json={}).json() == data
    assert len(calls) == 1
