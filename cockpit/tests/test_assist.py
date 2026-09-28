"""Assisted HARD (AUTONOMY.md 5c, engine/assist.py): H' prepares a pending HARD
change, H decides, the log records the brief H had. H' is always a stub here -- `prepare`
must never reach a model from the test suite.
graph_root: app > api > api.hello (depends_on util), util."""
import json

import pytest

import cli
from agent import reviewer
from engine import accepted, assist, inbox, parser, validate
from tests.conftest import write_spec


def _nodes(root):
    return parser.load_nodes(root)


def _pending_break(root):
    """Track the graph, then do what an agent does: drop util's log()."""
    accepted.accept_all(_nodes(root), root, by="setup")
    spec = root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("log()", "write(line)"),
                    encoding="utf-8")


def _h_prime(recommendation="reject", confidence=0.9, seen=None):
    def brief(report, old, cur):
        if seen is not None:
            seen.append((report, old, cur))
        return {"recommendation": recommendation, "confidence": confidence,
                "summary": "Removes log(), which api.hello calls.",
                "risks": ["api.hello breaks"], "alternatives": ["add write() next to log()"],
                "model": "stub"}
    return brief


def _log(root):
    path = root / ".sge" / "autonomy.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---- prepare -----------------------------------------------------------------

def test_prepare_gives_h_prime_the_facts_and_both_sides(graph_root):
    _pending_break(graph_root)
    seen = []
    [(nid, brief)] = assist.prepare(_nodes(graph_root), graph_root, _h_prime(seen=seen))
    assert nid == "util" and brief["recommendation"] == "reject"
    report, old, cur = seen[0]
    assert "consumed by api.hello" in report          # the engine's facts
    assert "log()" in old and "write(line)" in cur     # accepted vs current


def test_a_fresh_brief_is_not_prepared_twice(graph_root):
    _pending_break(graph_root)
    assist.prepare(_nodes(graph_root), graph_root, _h_prime())
    assert assist.prepare(_nodes(graph_root), graph_root,
                          lambda *_: pytest.fail("prepared again")) == []


def test_a_brief_goes_stale_when_the_node_changes_again(graph_root):
    _pending_break(graph_root)
    assist.prepare(_nodes(graph_root), graph_root, _h_prime())
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("write(line)", "emit(line)"),
                    encoding="utf-8")
    [change] = accepted.pending(_nodes(graph_root), graph_root)
    assert assist.brief_for(graph_root, change) is None
    assert assist.is_stale(graph_root, change)
    assert "STALE" in assist.format_brief(None, stale=True)


@pytest.mark.parametrize("answer", [None, {}, {"recommendation": "maybe"}])
def test_an_unusable_answer_is_no_brief(graph_root, answer):
    _pending_break(graph_root)
    [(_, brief)] = assist.prepare(_nodes(graph_root), graph_root, lambda *_: answer)
    assert brief is None
    [change] = accepted.pending(_nodes(graph_root), graph_root)
    assert assist.brief_for(graph_root, change) is None


# ---- decide ------------------------------------------------------------------

def test_accepting_records_the_brief_h_had(graph_root):
    _pending_break(graph_root)
    assist.prepare(_nodes(graph_root), graph_root, _h_prime("reject", 0.9))
    [d] = assist.decide(_nodes(graph_root), graph_root, ["util"], decision="accept", by="h")
    assert d["action"] == "accepted" and d["brief"]["recommendation"] == "reject"
    entry = _log(graph_root)[-1]
    assert (entry["action"], entry["brief"]["recommendation"]) == ("accepted", "reject")
    assert "agreed" not in entry   # a fact, not a score
    assert accepted.pending(_nodes(graph_root), graph_root) == []


def test_a_decision_without_a_brief_records_none(graph_root):
    _pending_break(graph_root)
    [d] = assist.decide(_nodes(graph_root), graph_root, ["util"], decision="accept", by="h")
    assert d == {"node": "util", "brief": None, "action": "accepted"}


def test_a_stale_list_does_not_decide(graph_root):
    _pending_break(graph_root)
    with pytest.raises(ValueError, match="changed on disk"):
        assist.decide(_nodes(graph_root), graph_root, ["util"], decision="accept",
                      by="h", expected={"util": "not-what-is-there"})


# ---- reject: H's "no" reaches the agent through the gate ---------------------

def test_a_rejection_blocks_the_gate_with_the_reason(graph_root):
    _pending_break(graph_root)
    assist.decide(_nodes(graph_root), graph_root, ["util"], decision="reject", by="h",
                  reason="keep log(); add write() next to it")
    report = validate.run(_nodes(graph_root), str(graph_root))
    assert "HARD CHANGE REJECTED on util by h" in report
    assert "keep log(); add write() next to it" in report
    assert "gate: BLOCK" in report


def test_a_rejection_needs_a_reason_and_a_pending_change(graph_root):
    _pending_break(graph_root)
    with pytest.raises(ValueError, match="reason"):
        assist.decide(_nodes(graph_root), graph_root, ["util"], decision="reject", by="h")
    with pytest.raises(ValueError, match="no pending HARD change"):
        assist.decide(_nodes(graph_root), graph_root, ["api"], decision="reject",
                      by="h", reason="r")


def test_restoring_the_accepted_spec_lifts_the_rejection(graph_root):
    _pending_break(graph_root)
    assist.decide(_nodes(graph_root), graph_root, ["util"], decision="reject", by="h",
                  reason="no")
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("write(line)", "log()"),
                    encoding="utf-8")
    assert "gate: pass" in validate.run(_nodes(graph_root), str(graph_root))


def test_a_different_change_is_pending_again_not_rejected(graph_root):
    """The rejection is bound to the change it rejected, not to the node."""
    _pending_break(graph_root)
    assist.decide(_nodes(graph_root), graph_root, ["util"], decision="reject", by="h",
                  reason="no")
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("write(line)", "emit(line)"),
                    encoding="utf-8")
    [change] = accepted.pending(_nodes(graph_root), graph_root)
    assert change["rejected"] is None
    assert "gate: pass" in validate.run(_nodes(graph_root), str(graph_root))


def test_a_rejected_change_leaves_h_s_inbox(graph_root):
    _pending_break(graph_root)
    assert [r["type"] for r in inbox.pending(_nodes(graph_root), graph_root)] == ["HARD"]
    assist.decide(_nodes(graph_root), graph_root, ["util"], decision="reject", by="h",
                  reason="no")
    assert inbox.pending(_nodes(graph_root), graph_root) == []


def test_the_inbox_carries_the_brief(graph_root):
    _pending_break(graph_root)
    assist.prepare(_nodes(graph_root), graph_root, _h_prime("accept", 0.7))
    [item] = inbox.pending(_nodes(graph_root), graph_root)
    assert item["brief"]["recommendation"] == "accept" and not item["stale"]
    assert inbox.awaiting(_nodes(graph_root), graph_root) == {"util"}


# ---- no statistics: nothing keeps score ------------------------------------

def test_there_is_no_track_record(graph_root):
    """The delegation is H's act, not a measured grant -- the scoring is gone."""
    assert not hasattr(assist, "record") and not hasattr(assist, "format_record")


def test_every_brief_is_logged(graph_root):
    _pending_break(graph_root)
    assist.prepare(_nodes(graph_root), graph_root, _h_prime("reject", 0.9))
    [entry] = [e for e in _log(graph_root) if e["action"] == "briefed"]
    assert (entry["actor"], entry["node"], entry["recommendation"]) == ("H'", "util", "reject")


def test_a_successor_brief_sees_the_earlier_one(graph_root):
    """Against re-rolling: a cosmetic edit must not buy a fresh opinion blind."""
    _pending_break(graph_root)
    assist.prepare(_nodes(graph_root), graph_root, _h_prime("reject", 0.9))
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("write(line)", "emit(line)"),
                    encoding="utf-8")
    seen = []
    assist.prepare(_nodes(graph_root), graph_root, _h_prime(seen=seen))
    report = seen[0][0]
    assert "EARLIER BRIEF on this node" in report and "recommended reject" in report


# ---- the CLI -----------------------------------------------------------------

def test_cli_prepare_pending_reject(graph_root, monkeypatch, capsys):
    _pending_break(graph_root)
    monkeypatch.setattr(reviewer, "brief_hard_change",
                        lambda report, old, cur, **_: _h_prime("reject", 0.9)(report, old, cur))
    assert cli.main(["prepare", str(graph_root)]) == 0
    assert "prepared util: H' recommends REJECT (0.90)" in capsys.readouterr().out
    cli.main(["pending", str(graph_root)])
    out = capsys.readouterr().out
    assert "H' recommends: REJECT (confidence 0.90)" in out
    assert "add write() next to log()" in out
    assert cli.main(["reject", str(graph_root), "util", "--reason", "keep log()",
                     "--by", "h"]) == 0
    assert "rejected util as h -- H' had recommended reject" in capsys.readouterr().out
    cli.main(["pending", str(graph_root)])
    out = capsys.readouterr().out
    assert "REJECTED by h" in out and "restore it" in out and "- log()" in out
    assert cli.main(["gate", str(graph_root)]) == 1


def test_cli_prepare_reports_an_unusable_brief(graph_root, monkeypatch, capsys):
    _pending_break(graph_root)
    monkeypatch.setattr(reviewer, "brief_hard_change", lambda *a, **k: None)
    assert cli.main(["prepare", str(graph_root)]) == 2
    assert "no usable brief for util" in capsys.readouterr().err


def test_cli_prepare_says_why_h_prime_is_unavailable(graph_root, monkeypatch, capsys):
    """Found with a real run: the provider's 401 came out as a traceback."""
    _pending_break(graph_root)

    def refused(*_a, **_k):
        raise RuntimeError("the provider refused: Error code: 401 - User not found.")
    monkeypatch.setattr(reviewer, "brief_hard_change", refused)
    assert cli.main(["prepare", str(graph_root)]) == 2
    assert "H' unavailable: the provider refused: Error code: 401" in capsys.readouterr().err


def test_reviewer_turns_a_provider_error_into_unavailable(monkeypatch):
    monkeypatch.setattr(reviewer, "_client", _refusing)
    with pytest.raises(RuntimeError, match="provider refused"):
        reviewer.brief_hard_change("report", "old", "new")


# ---- the real model's failure modes, reproduced with a stub client -----------

class _Resp:
    """A chat completion as the openai client returns it, minimally."""
    def __init__(self, arguments, finish_reason):
        call = type("Call", (), {"function": type("F", (), {"arguments": arguments})()})()
        msg = type("Msg", (), {"tool_calls": [call] if arguments is not None else None})()
        self.choices = [type("Choice", (), {"message": msg, "finish_reason": finish_reason})()]


def _refusing(*_):
    """A client whose provider refuses, as OpenRouter does for a bad key (401)."""
    import httpx
    import openai

    class Refusing:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    request = httpx.Request("POST", "https://example.invalid")
                    raise openai.AuthenticationError(
                        "User not found.", response=httpx.Response(401, request=request),
                        body=None)
    return Refusing


def _client_answering(*responses, requests=None):
    """A client giving `responses` in order; each request's kwargs go to `requests`."""
    answers = iter(responses)

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    if requests is not None:
                        requests.append(kw)
                    return next(answers)
    return Client


_FULL = json.dumps({"recommendation": "accept", "confidence": 0.8, "summary": "s",
                    "risks": [], "alternatives": []})


def test_a_brief_is_asked_for_without_a_token_limit(monkeypatch):
    """GLM-5.2's reasoning counts against max_tokens and varies per call: a fixed
    900 lost the whole budget to it (902 reasoning tokens, no brief)."""
    requests = []
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(_FULL, "tool_calls"), requests=requests))
    assert reviewer.brief_hard_change("report", "old", "new")["recommendation"] == "accept"
    [request] = requests
    assert "max_tokens" not in request


def test_a_cut_off_brief_is_unavailable_with_the_reason(monkeypatch):
    """Cut off even at the model's own maximum: H' unavailable, said why --
    not a silent None, and not asked again."""
    requests = []
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp('{"recommendation": "acc', "length"), requests=requests))
    with pytest.raises(RuntimeError, match="cut off at the model's output limit"):
        reviewer.brief_hard_change("report", "old", "new")
    assert len(requests) == 1


def test_a_complete_answer_without_a_brief_is_none(monkeypatch):
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(_Resp(None, "stop")))
    assert reviewer.brief_hard_change("report", "old", "new") is None


def test_tool_args_degrades_on_truncated_json():
    from agent.llm import _tool_args
    assert _tool_args(_Resp('{"verdict": "appr', "length")) == {}
    assert _tool_args(_Resp("[1, 2]", "stop")) == {}


@pytest.mark.parametrize("sent,items", [
    (["a", "b"], ["a", "b"]),
    ('["Add a second operation", "Parameterize it"]',       # seen from GLM-5.2
     ["Add a second operation", "Parameterize it"]),
    ("- first\n- second", ["first", "second"]),
    ("just one", ["just one"]),
    (None, []),
])
def test_list_fields_arrive_as_lists_whatever_the_model_sent(sent, items):
    brief = assist._clean({"recommendation": "reject", "confidence": 0.9, "risks": sent,
                           "alternatives": sent})
    assert brief["risks"] == items and brief["alternatives"] == items


def test_cli_prepare_says_when_nothing_is_pending(graph_root, capsys):
    """Run 03 ended with nothing pending, and prepare claimed every pending
    change had a fresh brief."""
    accepted.accept_all(_nodes(graph_root), graph_root, by="setup")
    assert cli.main(["prepare", str(graph_root)]) == 0
    assert "nothing to prepare: no HARD change is pending." in capsys.readouterr().out
