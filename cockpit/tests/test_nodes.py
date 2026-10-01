import pytest

from engine import nodes, parser


def test_new_node_creates_and_links(graph_root):
    n = parser.load_nodes(graph_root)
    nid, path = nodes.new_node("api", "report", "component", n)
    assert nid == "api.report"
    n = parser.load_nodes(graph_root)
    assert "api.report" in n
    assert "api.report" in n["api"]["design"]["children"]
    assert n["api.report"].get("code") == []  # always-present code key


def test_new_node_under_system_has_no_prefix(graph_root):
    n = parser.load_nodes(graph_root)
    nid, _ = nodes.new_node("app", "worker", "container", n)
    assert nid == "worker"  # child of system root drops the prefix


def test_delete_node_with_children_guarded(graph_root):
    n = parser.load_nodes(graph_root)
    with pytest.raises(ValueError):
        nodes.delete_node("api", n)  # api has child api.hello


def test_delete_node_recursive(graph_root):
    n = parser.load_nodes(graph_root)
    removed, _ = nodes.delete_node("api", n, recursive=True)
    assert set(removed) == {"api", "api.hello"}
    n = parser.load_nodes(graph_root)
    assert "api" not in n and "api.hello" not in n


def test_bootstrap_root_creates(tmp_path):
    spec = nodes.bootstrap_root(str(tmp_path), "shop", "an online shop")
    n = parser.load_nodes(tmp_path)
    assert n["shop"]["kind"] == "system"
    assert (tmp_path / "ARCHITECTURE.md").exists()


def test_bootstrap_refuses_valid_root(tmp_path):
    nodes.bootstrap_root(str(tmp_path), "shop", "x")
    with pytest.raises(ValueError):
        nodes.bootstrap_root(str(tmp_path), "shop", "x")


def test_bootstrap_repairs_broken_root(tmp_path):
    (tmp_path / "SPEC.md").write_text("# not a node, no id\n", encoding="utf-8")
    nodes.bootstrap_root(str(tmp_path), "app", "x")  # should repair, not raise
    n = parser.load_nodes(tmp_path)
    assert "app" in n


def test_the_whole_id_typed_as_the_segment_is_read_as_its_last_part(graph_root):
    """`api.report` typed under api made `api.api.report`, in a folder named
    `api.report` -- the id is meant, so its last part is taken."""
    n = parser.load_nodes(graph_root)
    nid, path = nodes.new_node("api", "api.report", "component", n)
    assert nid == "api.report"
    assert path.endswith("/api/report/SPEC.md")


def test_a_segment_of_more_than_one_id_part_is_refused(graph_root):
    n = parser.load_nodes(graph_root)
    with pytest.raises(ValueError, match="more than one id part"):
        nodes.new_node("api", "deep.report", "component", n)
    assert not (graph_root / "api" / "deep.report").exists()
