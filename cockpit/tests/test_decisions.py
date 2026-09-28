"""Decision requests (engine/decisions.py).

Run 02: the agent needed a GUI toolkit decision (ARCHITECTURE.md) and a wider
container contract (svc), could edit neither, and had nobody to ask. The toolkit
choice was recorded nowhere, and the design was bent to the wording of a contract
it could not change.
"""
import json

from engine import decisions, index, parser, validate


def _graph(requests, status="implemented"):
    return {
        "svc": {"id": "svc", "parent": None, "kind": "container",
                "contract": {"purpose": "x"}, "code": [], "status": "specd"},
        "svc.tkwin": {"id": "svc.tkwin", "parent": "svc", "kind": "component",
                      "contract": {"purpose": "y"}, "code": [], "status": status,
                      "decision_requests": requests},
    }


ADR = {"target": "ARCHITECTURE.md",
       "proposal": "ADR: the GUI uses tkinter from the standard library.",
       "reason": "Increment 2 asks for a GUI; stdlib-only leaves tkinter."}


def _hard(nodes):
    return [m for s, m in decisions.issues(nodes) if s == "HARD"]


def _warn(nodes):
    return [m for s, m in decisions.issues(nodes) if s == "WARN"]


# ---- a valid request is visible and grants nothing ---------------------------

def test_a_valid_request_is_reported_awaiting_h():
    nodes = _graph([ADR])
    assert _hard(nodes) == []
    assert any("DECISION REQUESTED by svc.tkwin for ARCHITECTURE.md, awaiting H" in m
               and "tkinter" in m for m in _warn(nodes))


def test_a_request_may_target_a_node_above_the_asker():
    nodes = _graph([{"target": "svc", "proposal": "provides: + a GUI via `svc gui`",
                     "reason": "the container now provides more than a CLI"}])
    assert _hard(nodes) == []
    assert decisions.pending(nodes) == [("svc.tkwin", "svc", "provides: + a GUI via `svc gui`")]


def test_several_requests_on_one_node_are_all_pending():
    """A node needing two decisions must not be pushed back into prose for the second."""
    other = {"target": "svc", "proposal": "p", "reason": "r"}
    assert len(decisions.pending(_graph([ADR, other]))) == 2


def test_a_single_mapping_is_accepted_as_one_request():
    assert len(decisions.pending(_graph(ADR))) == 1


def test_the_header_names_each_pending_request():
    assert decisions.summary(_graph([ADR])) == "1 requested (svc.tkwin -> ARCHITECTURE.md)"
    assert decisions.summary(_graph([])) == "none"


# ---- shape ------------------------------------------------------------------

def test_a_request_must_say_what_of_whom_and_why():
    for missing in ("target", "proposal", "reason"):
        req = dict(ADR)
        req[missing] = ""
        assert any(f"has no {missing}" in m for m in _hard(_graph([req]))), missing
        assert decisions.pending(_graph([req])) == []


def test_an_unknown_target_is_hard():
    req = dict(ADR, target="svc.nonexistent")
    assert any("neither ARCHITECTURE.md nor a node" in m for m in _hard(_graph([req])))


def test_a_node_cannot_request_a_decision_from_itself():
    req = dict(ADR, target="svc.tkwin")
    assert any("targets its own node" in m for m in _hard(_graph([req])))


def test_malformed_values_are_reported_not_ignored():
    assert any("malformed decision_requests" in m for m in _hard(_graph("please decide")))
    assert any("is not a mapping" in m for m in _hard(_graph(["please decide"])))


# ---- a node waiting on a decision is not done --------------------------------

def test_verified_is_blocked_while_a_decision_is_pending():
    assert _hard(_graph([ADR])) == []                       # implemented: fine
    assert any("pending decision request on svc.tkwin" in m
               for m in _hard(_graph([ADR], status="verified")))


def test_a_node_waiting_on_a_decision_does_not_count_as_done():
    assert decisions.not_done(_graph([ADR])) == {"svc.tkwin"}
    assert decisions.not_done(_graph([])) == set()


def test_the_index_lists_pending_decisions_and_keeps_them_out_of_done(tmp_path):
    (tmp_path / "SPEC.md").write_text(
        "---\nid: svc\nparent: null\nkind: container\ncontract: {purpose: x}\n"
        "code: []\nstatus: verified\n---\n# svc\n", encoding="utf-8")
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "SPEC.md").write_text(
        "---\nid: svc.tkwin\nparent: svc\nkind: component\ncontract: {purpose: y}\n"
        "code: []\nstatus: verified\n"
        "decision_requests:\n  - target: ARCHITECTURE.md\n    proposal: use tkinter\n"
        "    reason: a GUI is wished for\n---\n# t\n", encoding="utf-8")
    idx = index.build_index(parser.load_nodes(tmp_path), str(tmp_path))
    json.dumps(idx)
    assert idx["progress"]["pending_decisions"] == [
        {"node": "svc.tkwin", "target": "ARCHITECTURE.md", "proposal": "use tkinter"}]
    assert "svc.tkwin" not in idx["progress"]["verified"]


def test_validate_shows_the_decisions_line_on_every_run(tmp_path):
    (tmp_path / "SPEC.md").write_text(
        "---\nid: svc\nparent: null\nkind: system\ncode: []\nstatus: specd\n---\n# s\n",
        encoding="utf-8")
    assert "decisions: none" in validate.run(parser.load_nodes(tmp_path), str(tmp_path))


# ---- revise keeps the question -----------------------------------------------

def test_revise_keeps_pending_decision_requests(monkeypatch):
    import frontmatter
    from agent import planner
    from tests.test_planner import _fake_client
    current = ("---\nid: svc.tkwin\nparent: svc\nkind: component\n"
               "contract: {purpose: x}\ncode: []\n"
               "decision_requests:\n  - {target: ARCHITECTURE.md, proposal: use tkinter,"
               " reason: gui}\nstatus: implemented\n---\n# t\n")
    monkeypatch.setattr(planner, "_client", lambda *_: _fake_client({"contract": {"purpose": "y"}}))
    meta = frontmatter.loads(planner.revise_spec(current, "reword")).metadata
    assert meta["decision_requests"][0]["proposal"] == "use tkinter"
