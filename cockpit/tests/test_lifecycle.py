"""Status lifecycle enforcement: `verified` must be backed by test evidence."""
from engine import lifecycle, parser, validate
from tests.conftest import write_spec


def _verified_project(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["c"]}, code=[])
    write_spec(tmp_path / "c", id="c", parent="app", kind="component",
               contract={"provides": ["go()"]}, code=["c/**"], status="verified")
    (tmp_path / "c" / "x.py").write_text("x = 1\n", encoding="utf-8")  # owns real code
    return tmp_path


def test_verified_without_evidence_is_hard(tmp_path):
    root = _verified_project(tmp_path)
    issues = lifecycle.status_issues(parser.load_nodes(root), str(root))
    assert any(sev == "HARD" and "verified" in m and "without test evidence" in m
               for sev, m in issues)


def test_verified_with_pass_evidence_ok(tmp_path):
    root = _verified_project(tmp_path)
    lifecycle.record_evidence(str(root), ["c"], "pass", "uv run pytest", "c")
    issues = lifecycle.status_issues(parser.load_nodes(root), str(root))
    assert not any(sev == "HARD" for sev, m in issues)


def test_verified_with_fail_evidence_is_hard(tmp_path):
    root = _verified_project(tmp_path)
    lifecycle.record_evidence(str(root), ["c"], "fail", "uv run pytest", "c")
    issues = lifecycle.status_issues(parser.load_nodes(root), str(root))
    assert any(sev == "HARD" and "fail" in m for sev, m in issues)


def test_evidence_roundtrip(tmp_path):
    lifecycle.record_evidence(str(tmp_path), ["a", "b"], "pass", "mvn -q test", "cli")
    ev = lifecycle.load_evidence(str(tmp_path))
    assert ev["a"]["status"] == "pass" and ev["b"]["build_root"] == "cli"
    assert "at" in ev["a"]


def test_validate_blocks_verified_without_evidence(tmp_path):
    root = _verified_project(tmp_path)
    out = validate.run(parser.load_nodes(root), str(root))
    assert "without test evidence" in out
    assert out.strip().endswith("gate: BLOCK")


def test_implemented_component_without_code_warns(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["c"]}, code=[])
    write_spec(tmp_path / "c", id="c", parent="app", kind="component",
               contract={"provides": ["go()"]}, code=["src/c/**"], status="implemented")
    # code glob points into the (empty) code tree -> owns no existing code
    issues = lifecycle.status_issues(parser.load_nodes(tmp_path), str(tmp_path))
    assert any(sev == "WARN" and "owns no existing code" in m for sev, m in issues)


# ---- a node cannot be further along than its children -----------------------
#
# Found while working through an agent run: a system node owning no code reached
# `verified` on evidence recorded for the build root while its only child was
# still `specd`, and the gate passed. Fake completion one level up.

def _graph(parent_status, child_status):
    return {
        "app": {"id": "app", "parent": None, "kind": "system",
                "contract": {"purpose": "x"}, "code": [], "status": parent_status},
        "app.c": {"id": "app.c", "parent": "app", "kind": "component",
                  "contract": {"purpose": "y"}, "code": [], "status": child_status},
    }


def test_verified_with_an_unfinished_child_is_hard(tmp_path):
    nodes = _graph("verified", "specd")
    lifecycle.record_evidence(str(tmp_path), list(nodes), "pass", "pytest", str(tmp_path))
    hard = [m for sev, m in lifecycle.status_issues(nodes, str(tmp_path)) if sev == "HARD"]
    assert any("'verified' but a child is not: app" in m and "app.c is 'specd'" in m
               for m in hard), hard


def test_implemented_ahead_of_a_child_only_warns(tmp_path):
    """Growing a graph means adding `specd` children constantly; demoting the
    parent every time would block normal work."""
    nodes = _graph("implemented", "specd")
    issues = lifecycle.status_issues(nodes, str(tmp_path))
    assert not [m for sev, m in issues if sev == "HARD"]
    assert any("is ahead of a child" in m for sev, m in issues if sev == "WARN")


def test_a_parent_level_with_its_children_is_quiet(tmp_path):
    nodes = _graph("implemented", "implemented")
    lifecycle.record_evidence(str(tmp_path), list(nodes), "pass", "pytest", str(tmp_path))
    assert not [m for sev, m in lifecycle.status_issues(nodes, str(tmp_path))
                if "child" in m]


def test_a_parent_behind_its_children_is_fine(tmp_path):
    """The rule is one-directional: a cautious parent is not a lie."""
    nodes = _graph("specd", "verified")
    lifecycle.record_evidence(str(tmp_path), list(nodes), "pass", "pytest", str(tmp_path))
    assert not [m for sev, m in lifecycle.status_issues(nodes, str(tmp_path))
                if "child" in m]


def test_a_leaf_is_not_measured_against_children_it_does_not_have(tmp_path):
    nodes = {"app": {"id": "app", "parent": None, "kind": "system",
                     "contract": {"purpose": "x"}, "code": [], "status": "verified"}}
    lifecycle.record_evidence(str(tmp_path), ["app"], "pass", "pytest", str(tmp_path))
    assert not [m for sev, m in lifecycle.status_issues(nodes, str(tmp_path))
                if "child" in m]
