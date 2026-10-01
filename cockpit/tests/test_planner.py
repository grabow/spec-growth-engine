"""Pure helpers of the planner (no network / no API key needed)."""
import json
from types import SimpleNamespace

import pytest

from agent import planner
from tests.test_assist import _client_answering, _refusing, _Resp


def test_clean_deps_removes_parent_and_self_and_dups():
    out = planner._clean_deps(["util", "api", "api.hello", "util"], "api.hello", "api")
    assert out == ["util"]  # parent (api) and self removed, dedup


def test_clean_deps_handles_none():
    assert planner._clean_deps(None, "x", "y") == []


def test_clean_code_only_for_code_owning_kinds():
    assert planner._clean_code(["*.py"], "component") == ["*.py"]
    assert planner._clean_code(["*.py"], "code") == []      # not a node kind
    assert planner._clean_code(["*.py"], "container") == []
    assert planner._clean_code(["*.py"], "system") == []


def test_clean_code_keeps_globs_drops_nonstrings_and_dups():
    out = planner._clean_code(["src/**/*.py", "", 123, "src/**/*.py", "a.py"], "component")
    assert out == ["src/**/*.py", "a.py"]  # '**' allowed; non-strings + dups removed


def test_spec_tool_design_exposes_approach_and_verification():
    # the Draft button can only emit fields the tool schema declares
    design_props = (
        planner.SPEC_TOOL["function"]["parameters"]["properties"]["design"]["properties"]
    )
    assert set(design_props) == {"approach", "verification"}
    assert design_props["verification"]["type"] == "array"
    assert design_props["verification"]["items"]["type"] == "string"


def _fake_client(arguments: dict):
    """A stand-in OpenAI client returning one emit_spec tool call."""
    call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(arguments)))
    msg = SimpleNamespace(tool_calls=[call])
    resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    create = lambda **kw: resp  # noqa: E731
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_revise_preserves_status_and_identity(monkeypatch):
    current = (
        "---\nid: cli.x\nparent: cli\nkind: component\n"
        "contract:\n  provides:\n  - foo()\n"
        "code:\n- cli/x/**\nstatus: implemented\n---\n\nbody\n"
    )
    monkeypatch.setattr(planner, "_client", lambda *_: _fake_client({
        "contract": {"provides": ["foo()", "bar()"]},
        "design": {"approach": "a", "verification": ["unit test for foo"]},
        "depends_on": [], "code": ["cli/x/**"], "body": "new body",
    }))
    out = planner.revise_spec(current, "add bar()")
    assert "status: implemented" in out          # PRESERVED, not reset to specd
    assert "id: cli.x" in out and "kind: component" in out
    assert "bar()" in out                         # the change applied
    assert "cli/x/**" in out                      # untouched field carried through


def test_revise_keeps_status_specd_when_absent(monkeypatch):
    current = "---\nid: a\nparent: null\nkind: system\n---\n\nb\n"
    monkeypatch.setattr(planner, "_client", lambda *_: _fake_client({"contract": {}}))
    out = planner.revise_spec(current, "tweak")
    assert "status: specd" in out                 # default when the source had none


# ---- the real model's failure modes (GLM-5.2), reproduced with a stub client ----
#
# The reasoning counts against max_tokens and varies per call: a draft measured
# 3137 completion tokens against the old fixed 1500, and a cut-off answer came
# back without arguments -- TypeError/JSONDecodeError in a Tk callback instead of
# guidance. So no call sets a limit, and a cut-off is reported, with the reason.

_SPEC_ARGS = json.dumps({"contract": {"provides": ["refund(id)"]}, "code": ["api/r/*.py"]})
_CURRENT = "---\nid: api.r\nparent: api\nkind: component\nstatus: implemented\n---\n\nr\n"


def _draft():
    return planner.draft_spec("refund a payment", "api.r", "api", "component")


def _revise():
    return planner.revise_spec(_CURRENT, "add refund(id)")


def _every_model_call():
    """(name, call) for each function that asks the model something."""
    from agent import reviewer, semantic
    cap = {"node": "api.r", "role": "refunds", "provides": ["refund(id)"]}
    return [
        ("draft_spec", _draft),
        ("revise_spec", _revise),
        ("review_draft", lambda: reviewer.review_draft("intent", "spec")),
        ("brief_hard_change", lambda: reviewer.brief_hard_change("report", "old", "new")),
        ("reranker", lambda: semantic.make_reranker()("refund", [cap])),
        ("judge", lambda: semantic.make_judge()([("api.r", "api.s", cap, cap)])),
    ]


@pytest.mark.parametrize("name", [name for name, _ in _every_model_call()])
def test_no_model_call_sets_a_token_limit(monkeypatch, name):
    from agent import reviewer, semantic
    requests = []
    # one answer that satisfies every tool: each call reads only its own fields
    answer = json.dumps({
        "contract": {"provides": ["refund(id)"]}, "verdict": "approve", "confidence": 0.9,
        "findings": [], "recommendation": "accept", "summary": "s", "risks": [],
        "alternatives": [], "scores": [], "verdicts": []})
    stub = lambda *_: _client_answering(_Resp(answer, "tool_calls"), requests=requests)  # noqa: E731
    for module in (planner, reviewer, semantic):
        monkeypatch.setattr(module, "_client", stub)
    dict(_every_model_call())[name]()
    [request] = requests
    assert "max_tokens" not in request


@pytest.mark.parametrize("call", [_draft, _revise])
def test_a_cut_off_spec_is_unavailable_with_the_reason(monkeypatch, call):
    requests = []
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp('{"contract": {"provi', "length"), requests=requests))
    with pytest.raises(RuntimeError, match="cut off at the model's output limit"):
        call()
    assert len(requests) == 1   # reported, not asked again


@pytest.mark.parametrize("call", [_draft, _revise])
def test_an_answer_without_a_spec_is_unavailable_with_the_reason(monkeypatch, call):
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(_Resp(None, "stop")))
    with pytest.raises(RuntimeError, match="without a spec"):
        call()


@pytest.mark.parametrize("call", [_draft, _revise])
def test_a_provider_error_is_unavailable_with_the_providers_reason(monkeypatch, call):
    """app.Cockpit.draft/revise catch RuntimeError only: a bare openai.APIError
    ended as a traceback in the Tk callback."""
    monkeypatch.setattr(planner, "_client", _refusing)
    with pytest.raises(RuntimeError, match="provider refused: .*User not found"):
        call()
