"""H's inbox (engine/inbox.py): listing pending requests and resolving them on disk."""
import datetime as dt

import frontmatter
import pytest

from engine import inbox, parser, validate

TODAY = dt.date(2026, 9, 17)


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n## Invariants\n- Errors are raised.\n\n"
        "## Decisions (ADRs)\n- TODO\n\n## Notes\n- keep me\n", encoding="utf-8")
    (tmp_path / "SPEC.md").write_text(
        "---\nid: svc\nparent: null\nkind: container\ncontract: {purpose: x}\n"
        "code: []\nstatus: specd\n---\n# svc\n", encoding="utf-8")
    (tmp_path / "gui").mkdir()
    (tmp_path / "gui" / "SPEC.md").write_text(
        "---\nid: svc.gui\nparent: svc\nkind: component\ncontract: {purpose: shows state}\n"
        "code: []\nwaiver:\n  state: requested\n  kind: known-gap\n"
        "  reason: choose() reports errors in the window\n  proposed_expiry: 2026-12-31\n"
        "status: implemented\n---\n# gui\n\nBody stays.\n", encoding="utf-8")
    (tmp_path / "tkwin").mkdir()
    (tmp_path / "tkwin" / "SPEC.md").write_text(
        "---\nid: svc.tkwin\nparent: svc\nkind: component\ncontract: {purpose: window}\n"
        "code: []\ndecision_requests:\n"
        "  - target: ARCHITECTURE.md\n    proposal: 'ADR: the GUI uses tkinter.'\n"
        "    reason: a GUI is wished for\n"
        "  - target: svc\n    proposal: 'provides: + a GUI via svc gui'\n"
        "    reason: the container now provides more\n"
        "status: implemented\n---\n# tkwin\n", encoding="utf-8")
    return tmp_path


def _nodes(root):
    return parser.load_nodes(root)


def _meta(root, rel):
    return frontmatter.load(root / rel).metadata


# ---- listing -----------------------------------------------------------------

def test_pending_lists_both_kinds_with_what_h_needs_to_decide(project):
    items = inbox.pending(_nodes(project))
    assert [(i["type"], i["node"], i["subject"]) for i in items] == [
        ("waiver", "svc.gui", "known-gap"),
        ("decision", "svc.tkwin", "ARCHITECTURE.md"),
        ("decision", "svc.tkwin", "svc"),
    ]
    assert items[0]["proposed_expiry"] == "2026-12-31"
    assert items[1]["reason"] == "a GUI is wished for"
    assert inbox.awaiting(_nodes(project)) == {"svc.gui", "svc.tkwin"}


# ---- waivers -----------------------------------------------------------------

def test_grant_writes_owner_and_expiry_and_keeps_the_rest_of_the_spec(project):
    inbox.grant_waiver(_nodes(project), "svc.gui", "hartwig", "2026-12-31", today=TODAY)
    post = frontmatter.load(project / "gui" / "SPEC.md")
    assert post.metadata["waiver"] == {"state": "granted", "kind": "known-gap",
                                       "owner": "hartwig", "expires": "2026-12-31",
                                       "reason": "choose() reports errors in the window"}
    assert list(post.metadata)[:3] == ["id", "parent", "kind"]   # not reordered
    assert "Body stays." in post.content


def test_a_granted_waiver_passes_the_gate_and_shows_as_open(project):
    inbox.grant_waiver(_nodes(project), "svc.gui", "hartwig", "2099-01-01", today=TODAY)
    out = validate.run(_nodes(project), str(project))
    assert "waivers: 1 open (svc.gui), next expiry 2099-01-01" in out


@pytest.mark.parametrize("owner,expires,msg", [
    ("", "2026-12-31", "needs an owner"),
    ("hartwig", "soon", "not a date"),
    ("hartwig", "2020-01-01", "in the past"),
])
def test_grant_refuses_what_would_be_invalid_or_block_at_once(project, owner, expires, msg):
    with pytest.raises(ValueError, match=msg):
        inbox.grant_waiver(_nodes(project), "svc.gui", owner, expires, today=TODAY)
    assert _meta(project, "gui/SPEC.md")["waiver"]["state"] == "requested"   # untouched


def test_grant_refuses_a_waiver_that_is_no_longer_requested(project):
    inbox.grant_waiver(_nodes(project), "svc.gui", "h", "2026-12-31", today=TODAY)
    with pytest.raises(ValueError, match="no requested waiver"):
        inbox.grant_waiver(_nodes(project), "svc.gui", "h", "2026-12-31", today=TODAY)


def test_reject_removes_the_waiver(project):
    inbox.reject_waiver(_nodes(project), "svc.gui")
    assert "waiver" not in _meta(project, "gui/SPEC.md")


# ---- decisions ---------------------------------------------------------------

def _decision(project, subject):
    return next(i for i in inbox.pending(_nodes(project))
                if i["type"] == "decision" and i["subject"] == subject)


def test_accepting_an_architecture_decision_records_a_dated_adr(project):
    d = _decision(project, "ARCHITECTURE.md")
    inbox.accept_decision(_nodes(project), project, d["node"], d["index"], d["text"], today=TODAY)
    arch = (project / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "- 2026-09-17: the GUI uses tkinter. (requested by svc.tkwin)" in arch
    assert "- TODO" not in arch                         # placeholder replaced
    assert "## Notes\n- keep me" in arch                # following section intact
    remaining = _meta(project, "tkwin/SPEC.md")["decision_requests"]
    assert [r["target"] for r in remaining] == ["svc"]   # only the accepted one gone


def test_a_node_targeted_decision_is_not_applied_automatically(project):
    d = _decision(project, "svc")
    with pytest.raises(ValueError, match="edit that contract, then resolve"):
        inbox.accept_decision(_nodes(project), project, d["node"], d["index"], d["text"])


def test_resolving_removes_the_request_and_the_field_when_it_was_the_last(project):
    for subject in ("svc", "ARCHITECTURE.md"):
        d = _decision(project, subject)
        inbox.resolve_decision(_nodes(project), d["node"], d["index"], d["text"])
    assert "decision_requests" not in _meta(project, "tkwin/SPEC.md")


def test_rejecting_can_record_the_rejection_so_it_is_not_asked_again(project):
    d = _decision(project, "svc")
    inbox.reject_decision(_nodes(project), project, d["node"], d["index"], d["text"], today=TODAY)
    arch = (project / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "- 2026-09-17: Rejected: provides: + a GUI via svc gui (requested by svc.tkwin)" in arch


def test_rejecting_without_record_leaves_architecture_alone(project):
    before = (project / "ARCHITECTURE.md").read_text(encoding="utf-8")
    d = _decision(project, "svc")
    inbox.reject_decision(_nodes(project), project, d["node"], d["index"], d["text"], record=False)
    assert (project / "ARCHITECTURE.md").read_text(encoding="utf-8") == before


def test_a_stale_list_cannot_resolve_the_wrong_request(project):
    """The cockpit's list can be out of date: acting on a shifted index would
    decide a request H never looked at."""
    d = _decision(project, "svc")                        # index 1
    first = _decision(project, "ARCHITECTURE.md")
    inbox.resolve_decision(_nodes(project), first["node"], first["index"], first["text"])
    with pytest.raises(ValueError, match="changed on disk"):
        inbox.resolve_decision(_nodes(project), d["node"], d["index"], d["text"])


def test_the_adr_section_is_created_when_missing(tmp_path, project):
    (project / "ARCHITECTURE.md").write_text("# Architecture\n", encoding="utf-8")
    d = _decision(project, "ARCHITECTURE.md")
    inbox.accept_decision(_nodes(project), project, d["node"], d["index"], d["text"], today=TODAY)
    arch = (project / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "## Decisions (ADRs)\n- 2026-09-17: the GUI uses tkinter." in arch


def test_after_resolving_everything_the_inbox_is_empty_and_the_gate_is_clean(project):
    nodes = _nodes(project)
    inbox.grant_waiver(nodes, "svc.gui", "hartwig", "2099-01-01", today=TODAY)
    d = _decision(project, "ARCHITECTURE.md")
    inbox.accept_decision(_nodes(project), project, d["node"], d["index"], d["text"], today=TODAY)
    d = _decision(project, "svc")
    inbox.resolve_decision(_nodes(project), d["node"], d["index"], d["text"])
    assert inbox.pending(_nodes(project)) == []
    out = validate.run(_nodes(project), str(project))
    assert "decisions: none" in out and "gate: pass" in out
