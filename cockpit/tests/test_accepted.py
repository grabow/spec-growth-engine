"""The accepted state (engine/accepted.py): what a headless change set is
measured against. graph_root: app > api > api.hello (depends_on util), util."""
import json

import pytest

import cli
from engine import accepted, index as index_mod, lifecycle, parser, validate
from tests.conftest import write_spec


def _nodes(root):
    return parser.load_nodes(root)


def _track(root):
    accepted.accept_all(_nodes(root), root, by="setup")


def _edit(root, rel, old, new):
    spec = root / rel / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def _log(root):
    path = root / ".sge" / "autonomy.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---- untracked: nothing changes ----------------------------------------------

def test_untracked_is_the_old_behaviour(graph_root):
    _edit(graph_root, "util", "log()", "write(line)")
    nodes = _nodes(graph_root)
    assert not accepted.tracked(graph_root)
    assert accepted.pending(nodes, graph_root) == []
    assert accepted.clear(nodes, graph_root) == []
    assert "accepted: not tracked" in validate.run(nodes, str(graph_root))
    assert not (graph_root / ".sge" / "accepted.json").exists()


def test_single_nodes_cannot_start_tracking(graph_root):
    with pytest.raises(ValueError, match="--all"):
        accepted.accept(_nodes(graph_root), graph_root, ["util"], by="h")


# ---- tracked: what is pending, and what it holds back ------------------------

def test_an_accepted_graph_has_no_changes(graph_root):
    _track(graph_root)
    assert accepted.changes(_nodes(graph_root), graph_root) == []


def test_a_yaml_date_does_not_read_as_a_change(graph_root):
    """A granted waiver's expiry parses to a date and is stored as a string."""
    write_spec(graph_root / "util", id="util", parent="app", kind="component",
               contract={"provides": ["log()"]}, code=["util/*.py"],
               waiver={"state": "granted", "kind": "known-gap", "owner": "h",
                       "expires": "2099-01-01", "reason": "r"})
    text = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    (graph_root / "util" / "SPEC.md").write_text(text.replace("'2099-01-01'", "2099-01-01"),
                                                encoding="utf-8")
    _track(graph_root)
    assert accepted.changes(_nodes(graph_root), graph_root) == []


def test_breaking_a_consumed_contract_is_pending_and_holds_the_consumer(graph_root):
    _track(graph_root)
    _edit(graph_root, "util", "log()", "write(line)")
    nodes = _nodes(graph_root)
    [change] = accepted.pending(nodes, graph_root)
    assert change["node"] == "util" and change["consumers"] == ["api.hello"]
    assert accepted.not_done(nodes, graph_root) == {"util", "api.hello"}


def test_pending_does_not_block_but_verified_does(graph_root):
    _track(graph_root)
    _edit(graph_root, "util", "log()", "write(line)")
    report = validate.run(_nodes(graph_root), str(graph_root))
    assert "HARD CHANGE PENDING on util" in report and "gate: pass" in report
    assert "accepted: 4 node(s); HARD pending: 1 (util)" in report

    lifecycle.record_evidence(graph_root, ["api.hello"], "pass", "pytest")
    _edit(graph_root, "api/hello", "status: specd", "status: verified")
    nodes = _nodes(graph_root)
    nodes["api.hello"]["status"] = "verified"   # in case the fixture wrote none
    report = validate.run(nodes, str(graph_root))
    assert "HARD change on or affecting api.hello is not accepted" in report
    assert "gate: BLOCK" in report


def test_progress_does_not_count_held_nodes(graph_root):
    _track(graph_root)
    _edit(graph_root, "util", "log()", "write(line)")
    progress = index_mod.build_index(_nodes(graph_root), graph_root)["progress"]
    assert progress["pending_hard"] == ["api.hello", "util"]


def test_the_consumers_are_the_accepted_ones(graph_root):
    """A consumer that stopped depending on the node -- and had that accepted --
    no longer makes the removal HARD."""
    _track(graph_root)
    _edit(graph_root, "api/hello", "depends_on:\n- util", "depends_on: []")
    _edit(graph_root, "util", "log()", "write(line)")
    nodes = _nodes(graph_root)
    assert nodes["api.hello"]["depends_on"] == []
    cleared = accepted.clear(nodes, graph_root)   # fixed point: api.hello, then util
    assert [n for n, _ in cleared] == ["api.hello", "util"]
    assert accepted.pending(nodes, graph_root) == []


@pytest.mark.parametrize("edit,gate", [
    (("api", "http", "grpc"), "HARD"),                  # a container's contract
    (("util", "kind: component", "kind: container"), "HARD"),
])
def test_given_structure_stays_pending(graph_root, edit, gate):
    _track(graph_root)
    _edit(graph_root, *edit)
    [change] = accepted.pending(_nodes(graph_root), graph_root)
    assert change["gate"] == gate


def test_architecture_is_tracked_and_holds_the_root(graph_root):
    _track(graph_root)
    arch = graph_root / "ARCHITECTURE.md"
    arch.write_text(arch.read_text(encoding="utf-8") + "- Also: no network.\n",
                    encoding="utf-8")
    nodes = _nodes(graph_root)
    [change] = accepted.pending(nodes, graph_root)
    assert change["node"] == "ARCHITECTURE.md"
    assert accepted.not_done(nodes, graph_root) == {"app"}


def test_deleting_a_consumed_node_is_pending(graph_root):
    _track(graph_root)
    (graph_root / "util" / "SPEC.md").unlink()
    [change] = accepted.pending(_nodes(graph_root), graph_root)
    assert change["node"] == "util" and change["deleted"]


# ---- who clears what ---------------------------------------------------------

def test_e_clears_soft_and_leaves_hard(graph_root):
    _track(graph_root)
    _edit(graph_root, "util", "log()", "write(line)")                 # HARD
    write_spec(graph_root / "api" / "store", id="api.store", parent="api",
               kind="component", contract={"provides": ["keep()"]}, code=[])  # SOFT
    nodes = _nodes(graph_root)
    assert accepted.clear(nodes, graph_root) == [("api.store", "SOFT")]
    assert [c["node"] for c in accepted.pending(nodes, graph_root)] == ["util"]
    [entry] = [e for e in _log(graph_root) if e.get("action") == "cleared"]
    assert entry == {**entry, "actor": "E", "node": "api.store", "gate": "SOFT"}


def test_a_new_node_waits_for_its_unaccepted_parent(graph_root):
    _track(graph_root)
    write_spec(graph_root / "web", id="web", parent="app", kind="container",
               contract={"provides": ["ui"]}, code=[])
    write_spec(graph_root / "web" / "page", id="web.page", parent="web",
               kind="component", contract={"provides": ["render()"]}, code=[])
    nodes = _nodes(graph_root)
    assert accepted.clear(nodes, graph_root) == []
    accepted.accept(nodes, graph_root, ["web"], by="h")
    assert accepted.clear(nodes, graph_root) == [("web.page", "SOFT")]


def test_h_accepts_a_hard_change(graph_root):
    _track(graph_root)
    _edit(graph_root, "util", "log()", "write(line)")
    nodes = _nodes(graph_root)
    assert accepted.accept(nodes, graph_root, ["util"], by="hartwig") == [("util", "HARD")]
    assert accepted.pending(nodes, graph_root) == []
    entry = _log(graph_root)[-1]
    assert (entry["actor"], entry["by"], entry["gate"]) == ("H", "hartwig", "HARD")


def test_accept_all_is_one_log_entry(graph_root):
    _track(graph_root)
    [entry] = _log(graph_root)
    assert entry["action"] == "accepted-all" and entry["nodes"] == 4


def test_an_unreadable_state_is_a_hard_error_not_a_silent_pass(graph_root):
    _track(graph_root)
    (graph_root / ".sge" / "accepted.json").write_text("{not json", encoding="utf-8")
    report = validate.run(_nodes(graph_root), str(graph_root))
    assert "accepted state unreadable" in report and "gate: BLOCK" in report


# ---- the CLI -----------------------------------------------------------------

def test_gate_passes_with_a_pending_hard_change_and_clears_soft(graph_root, capsys):
    cli.main(["accept", str(graph_root), "--all", "--by", "setup"])
    _edit(graph_root, "util", "log()", "write(line)")
    write_spec(graph_root / "api" / "store", id="api.store", parent="api",
               kind="component", contract={"provides": ["keep()"]}, code=[])
    capsys.readouterr()
    assert cli.main(["gate", str(graph_root)]) == 0
    out = capsys.readouterr().out
    assert "E cleared 1 change(s) at SOFT or below: api.store (SOFT)" in out
    assert "HARD pending, awaiting H: util" in out


def test_a_blocked_gate_clears_nothing(ts_root, capsys):
    cli.main(["accept", str(ts_root), "--all"])
    write_spec(ts_root / "extra", id="extra", parent="app", kind="component",
               contract={"provides": ["x()"]}, code=[])
    assert cli.main(["gate", str(ts_root)]) == 1   # ts_root drifts
    assert "extra" not in json.loads(
        (ts_root / ".sge" / "accepted.json").read_text(encoding="utf-8"))["nodes"]


def test_pending_and_accept_commands(graph_root, capsys):
    cli.main(["accept", str(graph_root), "--all"])
    _edit(graph_root, "util", "log()", "write(line)")
    capsys.readouterr()
    assert cli.main(["pending", str(graph_root)]) == 0
    out = capsys.readouterr().out
    assert "change set util: HARD (breaking)" in out and "api.hello" in out
    assert cli.main(["accept", str(graph_root)]) == 2            # names nothing
    assert cli.main(["accept", str(graph_root), "ghost"]) == 2   # no such node
    assert cli.main(["accept", str(graph_root), "util", "--by", "h"]) == 0
    capsys.readouterr()
    cli.main(["pending", str(graph_root)])
    assert "nothing awaits your decision" in capsys.readouterr().out
