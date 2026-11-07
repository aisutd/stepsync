import copy
import json

import pytest

from app.coaching_summary import make_summary, moment
from test_automatic_coaching import bilateral_pair, save_result, plan
from app.comparison import compare


@pytest.mark.parametrize("family", ["knee", "hip", "elbow", "shoulder"])
def test_friendly_bilateral_wording_preserves_facts_and_limits_warning_to_final_note(family):
    matched = {"id": "bilateral:567:" + family, "kind": "bilateral_angle_range", "status": "matched",
               "label": family + " angle range across both legs", "start": 18.9, "end": 18.9,
               "measurements": {"expectedRange": [100, 130], "observedRange": [101, 129]}}
    different = {**matched, "id": "bilateral:600:" + family, "status": "different", "start": 20.0, "end": 20.0}
    context = {"alignment": {"mirrorSelection": {"ambiguous": True}}, "scoreAvailable": False,
               "evidenceScope": "side_independent", "facts": [matched, different]}
    before = copy.deepcopy(context)
    view = make_summary(context, [matched], [different], (different, "slow_repeat"))
    sentences = [view["impression"], *view["strengths"], *view["improvements"], view["practiceTip"]]
    assert "around 19 seconds" in view["strengths"][0]
    assert "around 20 seconds" in view["improvements"][0]
    assert "slowly" in view["practiceTip"]
    assert all(word not in " ".join(sentences).lower() for word in (
        "bilateral", "individual sides", "unknown", "alignment", "assessed", "left", "right",
        "perfect", "whole body matched", "bend more", "raise", "lower"))
    assert "which side you intended" in view["note"]
    assert context == before


@pytest.mark.parametrize("start,end,expected", [
    (18.9, 18.9, "around 19 seconds"), (1.0, 1.25, "around 1 second"),
    (3.2, 4.4, "between about 3 and 4 seconds"),
])
def test_timestamps_are_approximate_display_only(start, end, expected):
    fact = {"start": start, "end": end}
    assert moment(fact) == expected
    assert fact == {"start": start, "end": end}


def test_no_evidence_means_no_findings_tip_or_timestamp():
    view = make_summary({"scoreAvailable": False, "evidenceScope": "side_independent", "facts": [],
                         "alignment": {"mirrorSelection": {"ambiguous": True}}})
    assert not view["strengths"] and not view["improvements"] and view["practiceTip"] is None
    assert "couldn't compare enough" in view["impression"]
    assert not any(character.isdigit() for key in ("impression", "note") for character in view[key])
    assert "whole body in view" in view["note"]


def test_cached_wording_is_polished_without_provider_call_or_history_changes(tmp_path, monkeypatch):
    calls = []
    def generator(context, question, history):
        calls.append(context)
        return plan(context)
    client, folder, _ = save_result(tmp_path, monkeypatch, compare(*bilateral_pair()), generator)
    url = f"/analyses/{folder.name}/coaching"
    original = client.post(url, json={}).json()
    state = json.loads((folder / "coaching.json").read_text())
    state["messages"][0]["summary"] = {"impression": "Some bilateral movement ranges could be compared.",
        "strengths": ["Your knee angle range across both legs matched; individual sides remain unknown."],
        "improvements": [], "practiceTip": None, "note": "Side matching remains uncertain."}
    (folder / "coaching.json").write_text(json.dumps(state))
    before = (folder / "coaching.json").read_bytes()
    response = client.get(url).json()
    assert response["summary"]["presentationVersion"] == 2
    assert "bilateral" not in response["summary"]["impression"]
    assert "individual sides remain unknown" not in json.dumps(response["summary"])
    assert response["messages"][0]["citations"] == original["messages"][0]["citations"]
    assert response["messages"][0]["source"] == "gemini"
    assert len(calls) == 1
    assert (folder / "coaching.json").read_bytes() == before
