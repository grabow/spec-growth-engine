"""project.index.json generation: spec graph + capabilities + edges + evidence."""
import json

from engine import index, lifecycle, parser
from tests.conftest import write_spec


def _graph(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["a", "b"]}, code=[])
    write_spec(tmp_path / "a", id="a", parent="app", kind="component",
               contract={"provides": ["x()"]}, depends_on=["b"], code=["a/**"],
               status="implemented")
    write_spec(tmp_path / "b", id="b", parent="app", kind="component",
               contract={"provides": ["y()"]}, code=["b/**"])
    return tmp_path


def test_build_index_shape(tmp_path):
    idx = index.build_index(parser.load_nodes(_graph(tmp_path)), str(tmp_path))
    assert idx["node_count"] == 3
    assert set(idx["nodes"]) == {"app", "a", "b"}
    assert idx["nodes"]["a"]["depends_on"] == ["b"]
    assert idx["nodes"]["a"]["status"] == "implemented"
    assert idx["nodes"]["app"]["children"] == ["a", "b"]
    assert ["a", "b"] in idx["edges"]["dependency"]
    assert ["app", "a"] in idx["edges"]["ownership"]
    assert {c["node"] for c in idx["capabilities"]} == {"a", "b"}  # app has no provides
    assert "generated_at" in idx


def test_index_includes_test_evidence(tmp_path):
    root = _graph(tmp_path)
    lifecycle.record_evidence(str(root), ["a"], "pass", "uv run pytest", "a")
    idx = index.build_index(parser.load_nodes(root), str(root))
    assert idx["nodes"]["a"]["test_evidence"]["status"] == "pass"
    assert idx["nodes"]["b"]["test_evidence"] is None


def test_write_index_creates_file(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": []}, code=[])
    p = index.write_index(str(tmp_path))
    assert p.name == "project.index.json" and p.is_file()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["node_count"] == 1 and "nodes" in data


# ---- the index must be writable, whatever the frontmatter holds -------------

def _spec_with_waiver(root, expires: str):
    """`expires` unquoted is the spelling GOVERNANCE.md §8 uses, and PyYAML turns
    it into a datetime.date."""
    (root / "SPEC.md").write_text(
        "---\nid: a\nparent: null\nkind: system\ncontract: {purpose: x}\n"
        "code: []\nstatus: implemented\n"
        f"waiver:\n  state: granted\n  kind: deferred-test\n  owner: h\n  expires: {expires}\n"
        "---\n\n# a\n", encoding="utf-8")


def test_an_unquoted_yaml_date_does_not_break_the_index(tmp_path):
    """The bug: json.dumps cannot write a datetime.date, so `cli.py index`
    crashed on exactly the spelling the governance document recommends."""
    _spec_with_waiver(tmp_path, "2099-01-01")
    idx = index.build_index(parser.load_nodes(tmp_path), str(tmp_path))
    json.dumps(idx)      # would raise TypeError before
    assert idx["nodes"]["a"]["waiver"]["expires"] == "2099-01-01"


def test_a_quoted_date_survives_unchanged(tmp_path):
    _spec_with_waiver(tmp_path, '"2099-01-01"')
    idx = index.build_index(parser.load_nodes(tmp_path), str(tmp_path))
    assert idx["nodes"]["a"]["waiver"]["expires"] == "2099-01-01"


def test_write_index_produces_a_readable_file(tmp_path):
    _spec_with_waiver(tmp_path, "2099-01-01")
    path = index.write_index(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["progress"]["open_waivers"] == ["a"]
    assert data["progress"]["done"] == 0


def test_the_whole_index_is_json_serialisable(tmp_path, graph_root):
    """The invariant, not just the one field: build_index promises a
    machine-readable snapshot."""
    idx = index.build_index(parser.load_nodes(graph_root), str(graph_root))
    assert json.loads(json.dumps(idx)) == idx
