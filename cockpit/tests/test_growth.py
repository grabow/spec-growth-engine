"""Growth: the intent author decides it (ORCHESTRATOR.md, "How the graph grows");
the growth record keeps its steps (engine/intents.py); the planner gets what it
needs to carry out each step well -- the registry for a draft (reuse), the Spine
and the consumers for a revise (additive where possible). P, H' and C are stubs.
graph_root: app > api > api.hello (depends_on util), util."""
import json

import pytest

import app
import cli
from agent import codex_cli, planner
from engine import accepted, assist, intents
from tests.test_assist import _client_answering, _Resp


@pytest.fixture(autouse=True)
def _no_real_env(monkeypatch):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    monkeypatch.delenv("SGE_ACTOR", raising=False)


_DRAFT = ("---\nid: api.store\nparent: api\nkind: component\n"
          "contract:\n  provides: [\"keep(item)\"]\ncode: []\nstatus: specd\n---\n\n# Store\n")


# ---- 1. the growth record -------------------------------------------------------

def test_every_cli_growth_step_is_recorded_with_its_author(graph_root, monkeypatch):
    monkeypatch.setattr(planner, "draft_spec", lambda *_a, **_k: _DRAFT)
    monkeypatch.setattr(planner, "revise_spec",
                        lambda cur, change, **_k: cur.replace("keep(item)", "keep(item)\n  - drop(item)"))
    cli.main(["draft", str(graph_root), "api.store", "--parent", "api",
              "--intent", "keep items for later"])
    monkeypatch.setenv("SGE_ACTOR", "I")                       # as a codex agent sets it
    cli.main(["revise", str(graph_root), "api.store", "--change", "items can be dropped"])
    steps = intents.history(graph_root, "api.store")
    assert [(s["action"], s["author"], s["intent"]) for s in steps] == [
        ("drafted", "H", "keep items for later"),
        ("revised", "I", "items can be dropped")]
    assert steps[0]["gate"] == "SOFT" and steps[0]["by"]


def test_the_intents_command_shows_the_record(graph_root, monkeypatch, capsys):
    monkeypatch.setattr(planner, "draft_spec", lambda *_a, **_k: _DRAFT)
    cli.main(["draft", str(graph_root), "api.store", "--parent", "api", "--intent", "keep"])
    capsys.readouterr()
    cli.main(["intents", str(graph_root), "api.store"])
    assert "drafted by H" in capsys.readouterr().out
    cli.main(["intents", str(graph_root)])
    assert "api.store:" in capsys.readouterr().out


def test_an_agent_marks_what_it_writes(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("SGE_INTENT_MODEL", "m")
    _argv, env = codex_cli.command("intent")
    assert env["SGE_ACTOR"] == "I"


def test_h_prime_sees_how_the_node_was_grown(graph_root):
    """Intent fidelity is judged against the growth, not only the last request."""
    intents.record(graph_root, "util", "drafted", "a logger every component can use",
                   by="p", gate="SOFT")
    accepted.accept_all(__import__("engine.parser", fromlist=["x"]).load_nodes(graph_root),
                        graph_root, by="setup")
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("log()", "write(line)"),
                    encoding="utf-8")
    seen = []
    from engine import parser
    assist.prepare(parser.load_nodes(graph_root), graph_root,
                   lambda report, old, cur: seen.append(report) or None)
    assert "INTENT HISTORY of this node" in seen[0]
    assert "a logger every component can use" in seen[0]


def test_the_cockpit_records_only_what_it_saves(graph_root, monkeypatch):
    from tests.test_autonomy import _SaveCockpit
    monkeypatch.setattr(app.messagebox, "askyesno", lambda *a, **k: True)
    spec = graph_root / "util" / "SPEC.md"
    cockpit = _SaveCockpit(graph_root, "util", spec.read_text(encoding="utf-8")
                           .replace("log()", "log()\n  - flush()"))
    cockpit._last_intent = ("util", "revised", "add flush")
    cockpit.save_spec()
    [step] = intents.history(graph_root, "util")
    assert (step["intent"], step["author"]) == ("add flush", "H")
    cockpit.save_spec()                          # nothing new was drafted since
    assert len(intents.history(graph_root, "util")) == 1


# ---- 2. revise: the Spine, the consumers, additive first -------------------------

_SPEC_ANSWER = json.dumps({"contract": {"provides": ["log()"]}, "design": {},
                           "depends_on": [], "code": ["util/*.py"], "body": "b"})


def _prompt_of(monkeypatch, call):
    requests = []
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(_SPEC_ANSWER, "tool_calls"), requests=requests))
    call()
    return requests[0]["messages"][0]["content"]


def test_revise_tells_p_the_spine_the_consumers_and_to_grow_additively(monkeypatch):
    current = "---\nid: util\nparent: app\nkind: component\ncontract: {provides: [log()]}\n---\n"
    prompt = _prompt_of(monkeypatch, lambda: planner.revise_spec(
        current, "add flush", spine={"app": {"purpose": "demo"}}, consumers=["api.hello"]))
    assert "ANCESTOR CONTRACTS" in prompt and "'purpose': 'demo'" in prompt
    assert "CONSUMERS" in prompt and "api.hello" in prompt
    assert "prefer an ADDITIVE change" in prompt
    assert "a NEW `provides` entry of its own" in prompt      # run on GLM: it reworded instead


def test_cli_revise_passes_the_spine_and_the_consumers(graph_root, monkeypatch):
    seen = {}
    monkeypatch.setattr(planner, "revise_spec",
                        lambda cur, change, **kw: seen.update(kw) or cur)
    cli.main(["revise", str(graph_root), "util", "--change", "x"])
    assert seen["consumers"] == ["api.hello"]
    assert set(seen["spine"]) == {"app"}            # the ancestors, not the node itself


# ---- 3. draft: the registry, for reuse ------------------------------------------

def test_draft_shows_p_what_already_exists(monkeypatch):
    prompt = _prompt_of(monkeypatch, lambda: planner.draft_spec(
        "log things", "api.logger", "api", "component", {},
        capabilities=[{"node": "util", "provides": ["log()"]}]))
    assert "EXISTING CAPABILITIES" in prompt and "- util: ['log()']" in prompt


def test_cli_draft_passes_the_registry(graph_root, monkeypatch):
    seen = {}
    monkeypatch.setattr(planner, "draft_spec",
                        lambda *a, **kw: seen.update(kw) or _DRAFT)
    cli.main(["draft", str(graph_root), "api.store", "--parent", "api", "--intent", "x"])
    assert "util" in {c["node"] for c in seen["capabilities"]}


def test_revise_does_not_drop_what_p_left_out(monkeypatch):
    """Seen with GLM on a real revise: `purpose` vanished, unasked."""
    answer = json.dumps({"contract": {"provides": ["log()", "flush()"]}, "design": {},
                         "depends_on": [], "code": ["util/*.py"], "body": "b"})
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls")))
    current = ("---\nid: util\nparent: app\nkind: component\n"
               "contract: {purpose: 'a logger', provides: [log()], invariants: [never raises]}\n"
               "---\n")
    out = planner.revise_spec(current, "add flush")
    contract = __import__("yaml").safe_load(out.split("---")[1])["contract"]
    assert contract["provides"] == ["log()", "flush()"]          # the change is taken
    assert contract["purpose"] == "a logger"                      # the omission is not
    assert contract["invariants"] == ["never raises"]


# ---- 4. revise keeps what the request did not touch (run 05) ---------------------

_CURRENT = ("---\nid: svc.cli\nparent: svc\nkind: component\nprotected: true\n"
            "contract: {purpose: 'the command', provides: ['main() -> int']}\n"
            "design: {approach: 'argparse', verification: ['runs headless']}\n"
            "depends_on: [svc.session]\n"
            "code: ['svc/src/svc/cli/**', 'svc/tests/test_cli*.py']\n"
            "status: implemented\n---\n\n# CLI\n")


def _revised(monkeypatch, **answer) -> dict:
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(json.dumps({"contract": {"provides": ["main() -> int"]}, "body": "b",
                          **answer}), "tool_calls")))
    out = planner.revise_spec(_CURRENT, "say the note format in the summary")
    return __import__("yaml").safe_load(out.split("---")[1])


def test_a_revise_never_takes_the_protected_marker_off(monkeypatch):
    """Run 05 died of this: P dropped `protected: true` from svc.cli, the change
    set called it "protection removed", and the intent author -- which may not
    edit a spec by hand -- could not get P to put it back. It ended BLOCKED."""
    assert _revised(monkeypatch)["protected"] is True


def test_a_revise_does_not_empty_the_code_globs(monkeypatch):
    """Also run 05: `code: []` came back for a node that owns code, and five
    files were orphans the next time the gate ran."""
    assert _revised(monkeypatch, code=[])["code"] == [
        "svc/src/svc/cli/**", "svc/tests/test_cli*.py"]


def test_a_revise_keeps_the_design_and_the_dependencies_it_was_not_asked_about(monkeypatch):
    front = _revised(monkeypatch)
    assert front["design"] == {"approach": "argparse", "verification": ["runs headless"]}
    assert front["depends_on"] == ["svc.session"]


def test_a_dependency_can_still_be_removed_on_purpose(monkeypatch):
    """The other half: an EXPLICIT empty depends_on is a decision, not an omission."""
    assert _revised(monkeypatch, depends_on=[])["depends_on"] == []


# ---- 5. asking for what is above the node (run 08) ------------------------------
#
# The greenfield run ended BLOCKED on this: the manual tells the intent author to
# raise a decision request through `revise`, the author may not write YAML itself,
# and the planner's tool had no field for one -- so the request went nowhere. It
# built the whole notebook on an undecided persistence rule and said so.

_REQUEST = {"target": "ARCHITECTURE.md",
            "proposal": "Notes are stored as one newline-delimited JSON file.",
            "reason": "TASK.md needs persistence and no invariant decides it."}


def _answer(**extra) -> str:
    return json.dumps({"contract": {"provides": ["log()"]}, "design": {}, "depends_on": [],
                       "code": ["util/*.py"], "body": "b", **extra})


def _drafted(monkeypatch, targets=None, **answer) -> dict:
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(_answer(**answer), "tool_calls")))
    out = planner.draft_spec("log things", "util", "app", "component", {}, targets=targets)
    return __import__("yaml").safe_load(out.split("---")[1])


def test_the_planner_can_write_a_decision_request(monkeypatch):
    front = _drafted(monkeypatch, decision_requests=[_REQUEST])
    assert front["decision_requests"] == [_REQUEST]


def test_a_request_with_a_target_nobody_knows_never_reaches_the_file(monkeypatch):
    """engine/decisions makes an unknown target a HARD error, and only H deletes a
    request -- an invented target would wall the graph in."""
    invented = {**_REQUEST, "target": "TASK.md"}
    front = _drafted(monkeypatch, targets={"app", "util", "ARCHITECTURE.md"},
                     decision_requests=[invented, _REQUEST])
    assert front["decision_requests"] == [_REQUEST]


@pytest.mark.parametrize("bad", [
    {"target": "ARCHITECTURE.md", "proposal": "p"},          # no reason
    {"target": "", "proposal": "p", "reason": "r"},          # no target
    "a decision request, as prose",                           # not an entry at all
])
def test_an_unusable_request_is_dropped(monkeypatch, bad):
    front = _drafted(monkeypatch, decision_requests=[bad])
    assert "decision_requests" not in front


def test_a_revise_may_raise_one_and_must_never_drop_one(monkeypatch):
    """A pending request is H's to resolve: H changes the target and deletes it."""
    waiting = {"target": "app", "proposal": "the container provides a store",
               "reason": "svc.cli needs it"}
    current = ("---\nid: util\nparent: app\nkind: component\n"
               "contract: {provides: [log()]}\n"
               f"decision_requests:\n  - {json.dumps(waiting)}\n---\n")
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(_answer(decision_requests=[_REQUEST]), "tool_calls")))
    out = planner.revise_spec(current, "add flush")
    front = __import__("yaml").safe_load(out.split("---")[1])
    assert front["decision_requests"] == [waiting, _REQUEST]   # kept first, added second


def test_a_revise_that_says_nothing_keeps_the_request(monkeypatch):
    current = ("---\nid: util\nparent: app\nkind: component\n"
               "contract: {provides: [log()]}\n"
               f"decision_requests:\n  - {json.dumps(_REQUEST)}\n---\n")
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(_answer(), "tool_calls")))
    out = planner.revise_spec(current, "tidy the prose")
    assert __import__("yaml").safe_load(out.split("---")[1])["decision_requests"] == [_REQUEST]


def test_the_cli_tells_the_planner_which_targets_exist(graph_root, monkeypatch):
    seen = {}
    monkeypatch.setattr(planner, "revise_spec",
                        lambda cur, change, **kw: seen.update(kw) or cur)
    cli.main(["revise", str(graph_root), "util", "--change", "x"])
    assert "ARCHITECTURE.md" in seen["targets"] and "api.hello" in seen["targets"]


def test_the_manual_promise_holds_end_to_end(graph_root, monkeypatch):
    """What run 08 tried: ask through `revise`, and find it in the file afterwards."""
    spec = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(_answer(decision_requests=[_REQUEST]), "tool_calls")))
    cli.main(["revise", str(graph_root), "util", "--change",
              "add a decision request to ARCHITECTURE.md: where notes live"])
    front = __import__("frontmatter").load(graph_root / "util" / "SPEC.md").metadata
    assert front["decision_requests"] == [_REQUEST]
    assert spec != (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
