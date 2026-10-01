"""The delegation (AUTONOMY.md §3): H' accepts a pending HARD change --
only inside the scope H delegated, only once E finds it migrated, and always
revocable by H. No statistics anywhere: it is H's act, bounded by structure.

graph_root: app > api > api.hello (depends_on util), util. The change under test
is the one an agent makes: util drops log() for write(line). H' is a stub; the
suite never reaches a model."""
import json
import os

import pytest

import cli
from engine import accepted, assist, autonomy, inbox, lifecycle, migration, parser, validate
from tests.conftest import write_spec

OLD, TESTED, LATER = "2026-01-01T00:00:00", "2026-06-01T00:00:00", "2026-09-01T00:00:00"


def _nodes(root):
    return parser.load_nodes(root)


def _age(root, stamp=OLD):
    """Every file older than the evidence we record -- so 'after' is decided by
    the stamps the test sets, not by how fast it runs."""
    import datetime as dt
    t = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").timestamp()
    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, (t, t))


def _break_util(root):
    accepted.accept_all(_nodes(root), root, by="setup")
    spec = root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("log()", "write(line)"),
                    encoding="utf-8")


def _tested(root, at=TESTED, status="pass", nodes=("util", "api.hello"), tests=True):
    lifecycle.record_evidence(
        root, list(nodes), status, "pytest",
        tests_by_node={n: {f"tests/test_{n}.py"} for n in nodes} if tests else None, at=at)


def _change(root, nid="util"):
    return next(c for c in accepted.pending(_nodes(root), root) if c["node"] == nid)


def _migrated_util(root):
    _break_util(root)
    _age(root)
    _tested(root)


def _h_prime(recommendation="accept", confidence=0.9, calls=None):
    def brief(report, old, cur):
        if calls is not None:
            calls.append(report)
        return {"recommendation": recommendation, "confidence": confidence,
                "summary": "s", "risks": [], "alternatives": [], "model": "stub"}
    return brief


def _refuse(*_):
    raise AssertionError("H' must not be asked about this change")


def _log(root):
    return [json.loads(line) for line in
            (root / ".sge" / "autonomy.jsonl").read_text(encoding="utf-8").splitlines()]


# ---- E: is it migrated? ------------------------------------------------------

def test_migrated_when_node_and_consumers_are_tested_after_the_change(graph_root):
    _migrated_util(graph_root)
    assert migration.check(_nodes(graph_root), graph_root, _change(graph_root)) == \
        {"migrated": True, "missing": []}


@pytest.mark.parametrize("setup,why", [
    (lambda r: None, "no test evidence"),
    (lambda r: _tested(r, at="2025-01-01T00:00:00"), "before the last change"),
    (lambda r: _tested(r, status="fail"), "last test run 'fail'"),
    (lambda r: _tested(r, tests=False), "exercises nothing of it"),
])
def test_not_migrated_fails_safe(graph_root, setup, why):
    _break_util(graph_root)
    _age(graph_root)
    setup(graph_root)
    result = migration.check(_nodes(graph_root), graph_root, _change(graph_root))
    assert not result["migrated"] and any(why in m for m in result["missing"])


def test_a_consumer_still_using_the_removed_name_is_not_migrated(graph_root):
    _break_util(graph_root)
    (graph_root / "api" / "hello" / "greet.py").write_text(
        "from util.log import log\nlog('hallo')\n", encoding="utf-8")
    _age(graph_root)
    _tested(graph_root)
    result = migration.check(_nodes(graph_root), graph_root, _change(graph_root))
    assert any("still mentions what was removed (log)" in m for m in result["missing"])


def test_a_reworded_operation_that_keeps_its_name_is_not_removed(graph_root):
    """Run 04: read_text(path) -> str became read_text(path) -> Text. The consumer
    has to KEEP calling read_text; that is not a failure to let go. Whether it
    calls it right is what its tests after the change prove."""
    accepted.accept_all(_nodes(graph_root), graph_root, by="setup")
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("log()", "log(message, level)"),
                    encoding="utf-8")
    (graph_root / "api" / "hello" / "greet.py").write_text(
        "from util.log import log\nlog('hallo', 1)\n", encoding="utf-8")
    _age(graph_root)
    _tested(graph_root)
    change = _change(graph_root)
    assert change["provides"]["removed"] == ["log()"]      # reworded, so "removed" ...
    assert migration.check(_nodes(graph_root), graph_root, change) == \
        {"migrated": True, "missing": []}                   # ... but log is still provided


def test_a_file_touched_after_the_run_voids_the_evidence(graph_root):
    _migrated_util(graph_root)
    _age(graph_root, LATER)   # everything changed after TESTED
    assert not migration.check(_nodes(graph_root), graph_root,
                               _change(graph_root))["migrated"]


# ---- the scope H delegates ---------------------------------------------------

def test_a_breaking_change_to_a_consumed_component_is_in_scope(graph_root):
    _break_util(graph_root)
    assert autonomy.delegable_scope(_change(graph_root))[0]


@pytest.mark.parametrize("edit,node", [
    (("util", "kind: component", "kind: component\nprotected: true"), "util"),   # 5b zone
    (("api", "http", "grpc"), "api"),                                          # a container
    (("util", "kind: component", "kind: container"), "util"),                   # structure
])
def test_zones_and_structure_stay_hs(graph_root, edit, node):
    accepted.accept_all(_nodes(graph_root), graph_root, by="setup")
    rel, old, new = edit
    spec = graph_root / rel / "SPEC.md"
    text = spec.read_text(encoding="utf-8").replace(old, new)
    if node == "util":
        text = text.replace("log()", "write(line)")
    spec.write_text(text, encoding="utf-8")
    assert not autonomy.delegable_scope(_change(graph_root, node))[0]


def test_architecture_and_deletions_stay_hs(graph_root):
    accepted.accept_all(_nodes(graph_root), graph_root, by="setup")
    (graph_root / "ARCHITECTURE.md").write_text("# changed\n", encoding="utf-8")
    (graph_root / "util" / "SPEC.md").unlink()
    for change in accepted.pending(_nodes(graph_root), graph_root):
        assert not autonomy.delegable_scope(change)[0], change["node"]


# ---- the rule ----------------------------------------------------------------

MIGRATED, NOT = {"migrated": True, "missing": []}, {"migrated": False, "missing": ["x"]}
ACCEPT = {"recommendation": "accept", "confidence": 0.9}


@pytest.mark.parametrize("brief,mig,ok", [
    (ACCEPT, MIGRATED, True),
    (ACCEPT, NOT, False),
    (None, MIGRATED, False),
    ({"recommendation": "reject", "confidence": 0.9}, MIGRATED, False),
    ({"recommendation": "accept", "confidence": 0.3}, MIGRATED, False),
])
def test_delegated_decide(graph_root, brief, mig, ok):
    _break_util(graph_root)
    assert autonomy.delegated_decide(_change(graph_root), brief, mig)[0] is ok


# ---- the delegation: H's act -------------------------------------------------

def test_the_delegation_defaults_to_off_and_only_h_sets_it(graph_root):
    assert autonomy.delegated(graph_root) is False
    autonomy.set_delegation(graph_root, True, by="hartwig")
    assert autonomy.delegated(graph_root) is True
    assert json.loads((graph_root / ".sge" / "autonomy.json").read_text(
        encoding="utf-8"))["delegation"] is True
    assert _log(graph_root)[-1] == {**_log(graph_root)[-1], "actor": "H", "by": "hartwig",
                                    "action": "delegation", "delegation": True}
    autonomy.set_delegation(graph_root, False, by="hartwig")
    assert autonomy.delegated(graph_root) is False
    with pytest.raises(ValueError):
        autonomy.set_delegation(graph_root, 3, by="h")


@pytest.mark.parametrize("text,on", [
    ("{broken", False),
    ("[3]", False),
    ('{"delegation": "yes"}', False),        # stated, never inferred
    ('{"delegation": true}', True),
    ('{"delegation": false}', False),
])
def test_what_autonomy_json_says(graph_root, text, on):
    path = graph_root / ".sge" / "autonomy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    assert autonomy.delegated(graph_root) is on


# ---- decide: the delegated step -----------------------------------------------

def test_without_the_delegation_decide_does_nothing(graph_root):
    _migrated_util(graph_root)
    with pytest.raises(ValueError, match="delegation is off"):
        assist.delegated(_nodes(graph_root), graph_root, _refuse)


def test_delegated_h_prime_accepts_a_migrated_change(graph_root):
    _migrated_util(graph_root)
    autonomy.set_delegation(graph_root, True, by="h")
    [d] = assist.delegated(_nodes(graph_root), graph_root, _h_prime())
    assert d["action"] == "accepted"
    assert accepted.pending(_nodes(graph_root), graph_root) == []
    record = accepted.load(graph_root)["nodes"]["util"]
    assert (record["actor"], record["rule"]) == ("H'", "delegated")
    assert "log()" in json.dumps(record["previous"])   # what it replaced, for H
    assert accepted.awaiting_review(graph_root) == ["util"]


def test_h_prime_is_not_asked_about_what_it_may_not_decide(graph_root):
    _break_util(graph_root)          # not migrated: no evidence
    autonomy.set_delegation(graph_root, True, by="h")
    [d] = assist.delegated(_nodes(graph_root), graph_root, _refuse)
    assert d["action"] == "left for H" and "not migrated" in d["reason"]


def test_delegated_a_reject_recommendation_leaves_it_for_h(graph_root):
    _migrated_util(graph_root)
    autonomy.set_delegation(graph_root, True, by="h")
    [d] = assist.delegated(_nodes(graph_root), graph_root, _h_prime("reject"))
    assert d["action"] == "left for H" and "recommends reject" in d["reason"]
    assert [c["node"] for c in accepted.pending(_nodes(graph_root), graph_root)] == ["util"]


# ---- H confirms or overrules afterwards ---------------------------------------

def _accepted_by_h_prime(root):
    _migrated_util(root)
    autonomy.set_delegation(root, True, by="h")
    assist.delegated(_nodes(root), root, _h_prime())


def test_h_confirms_what_h_prime_accepted(graph_root):
    _accepted_by_h_prime(graph_root)
    [d] = assist.decide(_nodes(graph_root), graph_root, ["util"], decision="accept", by="h")
    assert d["action"] == "confirmed"
    assert accepted.awaiting_review(graph_root) == []
    assert accepted.load(graph_root)["nodes"]["util"]["actor"] == "H"


def test_h_overrules_what_h_prime_accepted(graph_root):
    _accepted_by_h_prime(graph_root)
    [d] = assist.decide(_nodes(graph_root), graph_root, ["util"], decision="reject", by="h",
                        reason="keep log()")
    assert d["action"] == "overruled"
    assert "log()" in json.dumps(accepted.load(graph_root)["nodes"]["util"]["spec"])
    report = validate.run(_nodes(graph_root), str(graph_root))
    assert "HARD CHANGE REJECTED on util by h" in report and "keep log()" in report
    assert "gate: BLOCK" in report
    assert _log(graph_root)[-1]["action"] == "overruled"


def test_the_inbox_lists_acceptances_for_review(graph_root):
    _accepted_by_h_prime(graph_root)
    [item] = inbox.pending(_nodes(graph_root), graph_root)
    assert (item["type"], item["node"]) == ("delegated", "util")


# ---- the CLI -----------------------------------------------------------------

def test_cli_delegate_and_decide(graph_root, monkeypatch, capsys):
    from agent import reviewer
    _migrated_util(graph_root)
    assert cli.main(["decide", str(graph_root)]) == 0
    assert "delegation is off" in capsys.readouterr().out
    assert cli.main(["delegate", str(graph_root), "on", "--by", "hartwig"]) == 0
    cli.main(["delegate", str(graph_root)])
    assert "delegation on:" in capsys.readouterr().out
    monkeypatch.setattr(reviewer, "brief_hard_change",
                        lambda report, old, cur, **_: _h_prime()(report, old, cur))
    assert cli.main(["decide", str(graph_root)]) == 0
    assert "accepted   util:" in capsys.readouterr().out
    cli.main(["pending", str(graph_root)])
    out = capsys.readouterr().out
    assert "accepted by H' under the delegation, awaiting your review" in out
    assert "delegation: on" in out


def test_cli_pending_shows_scope_and_migration(graph_root, capsys):
    _break_util(graph_root)
    cli.main(["pending", str(graph_root)])
    out = capsys.readouterr().out
    assert "delegable: yes" in out and "migrated: no -- " in out
    assert "delegation: off (pending HARD changes are H's)" in out


def test_cli_test_records_evidence_from_the_start_of_the_run(graph_root, monkeypatch, capsys):
    import testrun
    monkeypatch.setattr(testrun, "build_roots", lambda nodes, root: [graph_root])
    monkeypatch.setattr(testrun, "test_command", lambda root: ["true"])
    monkeypatch.setattr(testrun, "covered", lambda nodes, root, broot: ["util"])
    monkeypatch.setattr(testrun, "now", lambda: TESTED)
    assert cli.main(["test", str(graph_root)]) == 0
    assert "PASS" in capsys.readouterr().out
    rec = lifecycle.load_evidence(graph_root)["util"]
    assert (rec["status"], rec["at"]) == ("pass", TESTED)
