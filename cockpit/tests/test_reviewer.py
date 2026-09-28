"""H' draft reviewer (advisory): parses the LLM verdict; degrades without a key."""
import json
from types import SimpleNamespace

import pytest

from agent import reviewer
from tests.test_assist import _client_answering, _refusing, _Resp


def _fake_client(arguments: dict):
    call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(arguments)))
    msg = SimpleNamespace(tool_calls=[call])
    resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: resp)))


def test_review_parses_verdict_and_findings(monkeypatch):
    monkeypatch.setattr(reviewer, "_client", lambda *_: _fake_client({
        "verdict": "revise",
        "confidence": 0.7,
        "findings": [
            {"severity": "blocker", "area": "placement",
             "message": "CLI option belongs on the component that owns the entry point."},
            {"severity": "suggestion", "area": "acceptance", "message": "Make criterion 2 testable."},
            {"message": ""},  # dropped (no message)
        ],
    }))
    out = reviewer.review_draft("add a --foo flag", "---\nid: x\n---\n", architecture="arch")
    assert out["verdict"] == "revise" and out["confidence"] == 0.7
    assert len(out["findings"]) == 2                      # empty-message finding dropped
    assert out["findings"][0]["area"] == "placement"


def test_review_returns_none_without_api_key(monkeypatch):
    def no_key(*_):
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    monkeypatch.setattr(reviewer, "_client", no_key)
    assert reviewer.review_draft("intent", "spec") is None   # degrades, never raises


def test_review_returns_none_on_empty_tool_call(monkeypatch):
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])
    monkeypatch.setattr(reviewer, "_client", lambda *_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: resp))))
    assert reviewer.review_draft("intent", "spec") is None


# ---- the real model's failure modes (GLM-5.2), reproduced with a stub client ----


def test_a_cut_off_review_is_unavailable_with_the_reason(monkeypatch):
    """With a fixed 900 tokens the reasoning could eat the whole budget:
    review_draft came back None, D1 showed nothing and D2 never ran, silently."""
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp('{"verdict": "appr', "length")))
    with pytest.raises(RuntimeError, match="cut off at the model's output limit"):
        reviewer.review_draft("intent", "spec")


def test_review_turns_a_provider_error_into_unavailable(monkeypatch):
    monkeypatch.setattr(reviewer, "_client", _refusing)
    with pytest.raises(RuntimeError, match="provider refused: .*User not found"):
        reviewer.review_draft("intent", "spec")
