"""Change set + consumer impact (AUTONOMY.md 5a): which gate a SPEC.md change
falls under, and whom it reaches. graph_root: api.hello depends_on util."""
import copy

import pytest

from engine import changeset, lifecycle, nodes as nodeops, parser


def _nodes(root):
    return parser.load_nodes(root)


def _edit(nodes, nid, **changes):
    """The node's metadata with `changes` applied, as a proposed SPEC.md parses."""
    meta = copy.deepcopy({k: v for k, v in nodes[nid].items() if not k.startswith("_")})
    meta["_body"] = nodes[nid]["_body"]
    for key, value in changes.items():
        if key.startswith("contract__"):
            meta.setdefault("contract", {})[key[len("contract__"):]] = value
        else:
            meta[key] = value
    return meta


def _classify(root, nid, **changes):
    nodes = _nodes(root)
    return changeset.classify(nodes, nid, _edit(nodes, nid, **changes))


# ---- new nodes -------------------------------------------------------------

@pytest.mark.parametrize("kind,parent,gate", [
    ("component", "api", "SOFT"),
    ("code", "api.hello", "SOFT"),
    ("container", "app", "HARD"),
    ("system", None, "HARD"),
    ("banana", "api", "HARD"),   # kind is unenforced: unknown -> fail safe
])
def test_a_new_node_is_gated_by_its_kind(graph_root, kind, parent, gate):
    new = {"id": "x", "kind": kind, "parent": parent, "contract": {"provides": ["f()"]}}
    change = changeset.classify(_nodes(graph_root), "x", new)
    assert change["new_node"] and change["gate"] == gate
    assert change["provides"]["added"] == ["f()"]


def test_drafting_into_a_fresh_skeleton_stays_soft(graph_root):
    """The everyday D2 case: H creates a component, the planner fills it in.
    Nothing depends on it and it owns no code, so the whole contract is SOFT."""
    nodes = _nodes(graph_root)
    nid, _ = nodeops.new_node("api", "store", "component", nodes)
    nodes = _nodes(graph_root)
    draft = _edit(nodes, nid, contract={
        "provides": ["save(item)"], "invariants": ["items are unique"],
        "acceptance_criteria": ["a saved item can be read back"],
    }, depends_on=["util"], code=["api/store/*.py"], design={"approach": "a dict"})
    change = changeset.classify(nodes, nid, draft)
    assert change["gate"] == "SOFT", change["reasons"]
    assert change["breaking"]   # the invariant is new -- but nobody can break
    assert any("no node depends on it yet" in why for _, why in change["reasons"])


# ---- contract changes ------------------------------------------------------

def test_a_pure_addition_to_provides_is_additive(graph_root):
    change = _classify(graph_root, "util", contract__provides=["log()", "flush()"])
    assert change["gate"] == "SOFT" and not change["breaking"]
    assert change["provides"] == {"added": ["flush()"], "removed": []}


def test_removing_a_consumed_operation_is_hard(graph_root):
    change = _classify(graph_root, "util", contract__provides=["write(line)"])
    assert change["gate"] == "HARD" and change["breaking"]
    assert change["provides"]["removed"] == ["log()"]
    assert any("consumed by api.hello" in why for _, why in change["reasons"])


def test_breaking_a_contract_nobody_uses_is_soft(graph_root):
    change = _classify(graph_root, "api.hello", contract__provides=["hello()"])
    assert change["breaking"] and change["gate"] == "SOFT"


def test_breaking_a_container_is_hard_even_without_consumers(graph_root):
    """A container's consumers may sit outside the graph."""
    change = _classify(graph_root, "api", contract__provides=["grpc"])
    assert change["gate"] == "HARD"
    assert any("outside the graph" in why for _, why in change["reasons"])


# ---- declared protection (AUTONOMY.md 5b): the run-03 hole --------------------
#
# `svc.cli` was a component, nothing in the graph depended on it, so a breaking
# change to the CLI's promise read SOFT and E accepted it. The gate cannot see a
# consumer OUTSIDE the graph; H declares the node instead.

def test_a_declared_protected_component_breaks_hard(graph_root):
    change = _classify(graph_root, "api.hello", protected=True,
                       contract__provides=["hello()"])
    assert change["gate"] == "HARD" and change["protected"]
    assert any("declared protected" in why for _, why in change["reasons"])


def test_a_declared_protected_subtree_covers_its_children(graph_root):
    """H declares the boundary once, on the container."""
    nodes = _nodes(graph_root)
    nodes["api"]["protected"] = True
    change = changeset.classify(nodes, "api.hello",
                                _edit(nodes, "api.hello", contract__provides=["hello()"]))
    assert change["gate"] == "HARD" and change["protected"]


def test_deleting_a_declared_protected_node_is_hard(graph_root):
    nodes = _nodes(graph_root)
    nodes["api.hello"]["protected"] = True
    change = changeset.classify(nodes, "api.hello", None)
    assert change["deleted"] and change["gate"] == "HARD"
    assert any("protected node is deleted" in why for _, why in change["reasons"])


def test_declaring_protection_is_soft_and_removing_it_is_hard(graph_root):
    """Tightening a guard may proceed; loosening it is H's decision."""
    assert _classify(graph_root, "api.hello", protected=True)["gate"] == "SOFT"
    nodes = _nodes(graph_root)
    nodes["api.hello"]["protected"] = True
    new = _edit(nodes, "api.hello")
    new.pop("protected")
    change = changeset.classify(nodes, "api.hello", new)
    assert change["gate"] == "HARD"
    assert any("protection removed" in why for _, why in change["reasons"])


def test_an_unmarked_consumer_less_break_is_soft_but_says_how_to_protect_it(graph_root):
    """The hole stays open for an undeclared node, so it must not stay SILENT."""
    change = _classify(graph_root, "api.hello", contract__provides=["hello()"])
    assert change["gate"] == "SOFT" and not change["protected"]
    assert any("not declared protected" in why for _, why in change["reasons"])
    assert "protected: true" in changeset.report(change)


@pytest.mark.parametrize("key", ["invariants", "error_behavior", "purpose"])
def test_any_other_promise_changing_is_breaking(graph_root, key):
    """Tightened or widened cannot be read off a sentence: fail safe."""
    change = _classify(graph_root, "util", **{f"contract__{key}": ["a new promise"]})
    assert change["breaking"] and change["gate"] == "HARD"


def test_reordering_or_rewrapping_is_not_a_change(graph_root):
    nodes = _nodes(graph_root)
    nodes["api.hello"]["contract"]["invariants"] = ["prints hallo", "never raises"]
    new = _edit(nodes, "api.hello", contract__invariants=["never raises", "prints   hallo"])
    assert changeset.classify(nodes, "api.hello", new)["gate"] == "NONE"


def test_the_root_contract_is_a_root_invariant(graph_root):
    change = _classify(graph_root, "app", contract__acceptance_criteria=["more"])
    assert change["gate"] == "HARD"


def test_acceptance_criteria_follow_the_contract(graph_root):
    change = _classify(graph_root, "api.hello",
                       contract__acceptance_criteria=["greet prints hallo twice"])
    assert change["gate"] == "SOFT" and not change["breaking"]
    assert change["criteria"]["removed"] == ["greet prints hallo"]


# ---- structure and the other fields ---------------------------------------

@pytest.mark.parametrize("changes", [
    {"kind": "container"}, {"parent": "app"}, {"id": "api.hi"},
])
def test_structure_changes_are_hard(graph_root, changes):
    assert _classify(graph_root, "api.hello", **changes)["gate"] == "HARD"


@pytest.mark.parametrize("changes,gate", [
    ({}, "NONE"),
    ({"design": {"approach": "print it"}}, "NONE"),
    ({"_body": "Different prose."}, "NONE"),
    ({"depends_on": []}, "AUTO"),
    ({"status": "implemented"}, "AUTO"),
    ({"code": ["api/hello/**/*.py"]}, "SOFT"),
    ({"protected": True}, "SOFT"),   # a guard tightens; removing it is HARD below
    ({"waiver": {"state": "requested", "kind": "known-gap", "reason": "r"}}, "NONE"),
    ({"waiver": {"state": "granted", "kind": "known-gap", "owner": "me",
                 "expires": "2099-01-01", "reason": "r"}}, "HARD"),
])
def test_field_gates(graph_root, changes, gate):
    assert _classify(graph_root, "api.hello", **changes)["gate"] == gate


def test_no_change_has_no_reasons(graph_root):
    change = _classify(graph_root, "api.hello")
    assert change["gate"] == "NONE" and change["reasons"] == []


# ---- impact ----------------------------------------------------------------

@pytest.mark.parametrize("entry,expected", [
    ("createOrder(cart): Order", "createOrder"),
    ("log()", "log"),
    ("GET /search?q=term", "/search"),
    ("Order: the order record", "Order"),
    ("HTTP API for product search", None),
    ("TextReadError: carries .path; str() is 'cannot read'", "TextReadError"),
    ("async fetch(url): Response", "fetch"),
    ("svc.textfile.read_text(path) -> str", "read_text"),
    ("List<Order> of recent orders", None),
    ("http", None),   # one word is not yet a name
])
def test_handle_is_the_name_a_consumer_would_write(entry, expected):
    assert changeset.handle(entry) == expected


def test_impact_lists_consumers_and_what_they_mention(graph_root):
    (graph_root / "api" / "hello" / "greet.py").write_text(
        "from util.log import log\nlog('hallo')\n", encoding="utf-8")
    nodes = _nodes(graph_root)
    change = changeset.classify(nodes, "util", _edit(nodes, "util",
                                                     contract__provides=["write(line)"]))
    reach = changeset.impact(nodes, graph_root, change)
    [consumer] = reach["consumers"]
    assert consumer["node"] == "api.hello"
    assert ("log", "api/hello/greet.py") in consumer["mentions"]


def test_a_consumer_is_listed_even_when_it_mentions_nothing(graph_root):
    nodes = _nodes(graph_root)
    change = changeset.classify(nodes, "util", _edit(nodes, "util",
                                                     contract__provides=["write(line)"]))
    reach = changeset.impact(nodes, graph_root, change)
    assert [c["node"] for c in reach["consumers"]] == ["api.hello"]
    assert reach["consumers"][0]["mentions"] == []
    assert "no mention of what was removed found" in changeset.report(change, reach)


def test_prose_promises_are_reported_as_unchecked(graph_root):
    nodes = _nodes(graph_root)
    change = changeset.classify(nodes, "api", _edit(nodes, "api", contract__provides=[]))
    assert changeset.impact(nodes, graph_root, change)["unchecked"] == ["http"]


def test_evidence_against_the_old_contract_is_reported_stale(graph_root):
    lifecycle.record_evidence(graph_root, ["util"], "pass", "pytest")
    nodes = _nodes(graph_root)
    nodes["api.hello"]["status"] = "verified"
    change = changeset.classify(nodes, "util", _edit(nodes, "util",
                                                     contract__provides=["write(line)"]))
    stale = changeset.impact(nodes, graph_root, change)["stale"]
    assert any(s.startswith("util: test evidence (pass") for s in stale)
    assert "api.hello is 'verified' against the old contract" in stale


def test_an_additive_change_leaves_evidence_alone(graph_root):
    lifecycle.record_evidence(graph_root, ["util"], "pass", "pytest")
    nodes = _nodes(graph_root)
    change = changeset.classify(nodes, "util", _edit(nodes, "util",
                                                     contract__provides=["log()", "flush()"]))
    assert changeset.impact(nodes, graph_root, change)["stale"] == []


# ---- text in, report out ---------------------------------------------------

def test_assess_parses_the_proposed_text(graph_root):
    text = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    text = text.replace("log()", "write(line)")
    change, reach = changeset.assess(_nodes(graph_root), graph_root, "util", text)
    report = changeset.report(change, reach)
    assert report.startswith("change set util: HARD (breaking)")
    assert "[HARD] breaking: provides removed or reworded: log()" in report
    assert "api.hello" in report


def test_unparsable_text_is_not_assessed(graph_root):
    assert changeset.assess(_nodes(graph_root), graph_root, "util",
                            "---\nid: a\n\tkind: x\n---\n") is None


# ---- a new node: the report must say WHAT is proposed ------------------------
#
# Run 08's container arrived as "change set app: HARD (new node) / [HARD] new
# container" and nothing else. H is asked to accept a boundary and was shown
# only that a boundary exists -- the promises were in the record all along.

def _proposed(**contract) -> dict:
    return changeset.classify({}, "app.new", {"id": "app.new", "parent": "app",
                                              "kind": "container", "contract": contract})


def test_a_new_node_reports_what_it_would_provide():
    report = changeset.report(_proposed(purpose="the notebook itself",
                                        provides=["add(text)", "remove(id)"]))
    assert "purpose: the notebook itself" in report
    assert "it would provide (2):" in report
    assert "  - add(text)" in report and "  - remove(id)" in report


def test_a_long_list_is_capped_and_says_where_the_rest_is():
    promises = [f"op{i}()" for i in range(12)]
    report = changeset.report(_proposed(provides=promises))
    assert "it would provide (12):" in report
    assert "  - op7()" in report and "  - op8()" not in report
    assert "and 4 more (the spec of app.new has them all)" in report


def test_a_boundary_that_promises_nothing_says_so():
    """A container with no contract is the case H most needs to see."""
    assert "it provides nothing yet" in changeset.report(_proposed())


def test_a_changed_node_still_leads_with_its_purpose(graph_root):
    change = _classify(graph_root, "util", contract__purpose="the logger",
                       contract__provides=["log()", "flush()"])
    report = changeset.report(change)
    assert "purpose: the logger" in report
    assert "it would provide" not in report, "not a new node: the diff says what changed"


# ---- what changed, entry by entry ---------------------------------------------

def test_the_report_shows_a_reworded_invariant_before_and_after(graph_root):
    """'invariants changed' says THAT; H, asked to clear a HARD change, needs WHAT
    -- the run that dropped "no sound" from core.window said only the first."""
    nodes = _nodes(graph_root)
    nodes["util"]["contract"]["invariants"] = ["logs to stdout"]
    change = changeset.classify(nodes, "util", _edit(
        nodes, "util", contract__invariants=["logs to stdout, never to a file"]))
    assert change["gate"] == "HARD"                                   # consumed by api.hello
    assert change["diff"]["invariants"] == {"removed": ["logs to stdout"],
                                            "added": ["logs to stdout, never to a file"]}
    report = changeset.report(change)
    assert "    - logs to stdout\n" in report + "\n"
    assert "    + logs to stdout, never to a file" in report


def test_the_diff_shows_soft_and_auto_changes_too(graph_root):
    """The gate decides WHO clears it, not what H gets to see: an added promise
    (SOFT), a new dependency and a status (AUTO) are spelled out as well."""
    change = _classify(graph_root, "api.hello",
                       contract__provides=["greet()", "wave()"],
                       depends_on=["util", "api"], status="verified")
    diff = change["diff"]
    assert diff["provides"] == {"removed": [], "added": ["wave()"]}
    assert diff["depends_on"]["added"] == ["api"]
    assert diff["status"] == {"removed": [], "added": ["verified"]}   # the fixture had none
    assert ("SOFT", "provides added (1)") in change["reasons"]       # short: the entry is below
    report = changeset.report(change)
    assert "  provides\n    + wave()" in report
    assert "  depends_on\n    + api" in report


def test_the_diff_leaves_out_what_gates_nothing(graph_root):
    """design and the prose are NONE: long, and nobody clears them."""
    change = _classify(graph_root, "api.hello", design={"approach": "a new approach"})
    assert change["diff"] == {}
    assert "what changed" not in changeset.report(change)


def test_a_long_diff_is_cut_with_a_count(graph_root):
    many = [f"promise {i}()" for i in range(12)]
    change = _classify(graph_root, "api.hello", contract__provides=["greet()", *many])
    report = changeset.report(change)
    assert "+ promise 7()" in report and "+ promise 8()" not in report
    assert "... and 4 more (the spec of api.hello has them all)" in report


def test_a_new_node_has_no_diff_its_promises_are_listed_instead(graph_root):
    new = {"id": "x", "kind": "component", "parent": "api",
           "contract": {"provides": ["f()"]}}
    change = changeset.classify(_nodes(graph_root), "x", new)
    assert change["diff"] == {}
    assert "it would provide (1):\n  - f()" in changeset.report(change)
