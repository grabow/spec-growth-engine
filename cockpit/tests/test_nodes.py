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


# ---- rename -------------------------------------------------------------------

def test_rename_a_consumed_leaf_rewrites_its_edges_and_leaves_its_code(graph_root):
    """util -> tools: its consumer's depends_on and its parent's children follow;
    the SPEC.md moves, the code beside it stays, and the glob still owns it."""
    from engine import drift, validate
    n = parser.load_nodes(graph_root)
    result = nodes.rename_node(graph_root, "util", "tools", n)
    assert result["ids"] == {"util": "tools"}
    assert result["moves"] == [("util/SPEC.md", "tools/SPEC.md")]
    n = parser.load_nodes(graph_root)
    assert "util" not in n and n["tools"]["code"] == ["util/*.py"]
    assert n["api.hello"]["depends_on"] == ["tools"]
    assert n["app"]["design"]["children"] == ["api", "tools"]
    assert (graph_root / "util" / "log.py").exists()          # the code did not move
    for report in (validate.run(n, str(graph_root)), drift.run(n, str(graph_root))):
        assert "HARD errors: 0" in report, report


def test_rename_carries_the_subtree(graph_root):
    n = parser.load_nodes(graph_root)
    result = nodes.rename_node(graph_root, "api", "service", n)
    assert result["ids"] == {"api": "service", "api.hello": "service.hello"}
    n = parser.load_nodes(graph_root)
    assert n["service.hello"]["parent"] == "service"
    assert n["service"]["design"]["children"] == ["service.hello"]
    assert n["service.hello"]["_path"].endswith("service/hello/SPEC.md")
    assert (graph_root / "api" / "hello" / "greet.py").exists()   # the code stays


def test_rename_keeps_the_order_of_the_fields(graph_root):
    nodes.rename_node(graph_root, "util", "tools", parser.load_nodes(graph_root))
    head = (graph_root / "api" / "hello" / "SPEC.md").read_text(encoding="utf-8")
    assert head.index("id:") < head.index("parent:") < head.index("kind:")


def test_rename_reports_prose_that_still_names_the_old_id(graph_root):
    spec = graph_root / "api" / "hello" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8") + "\nLogs through util.\n",
                    encoding="utf-8")
    result = nodes.rename_node(graph_root, "util", "tools", parser.load_nodes(graph_root))
    assert result["mentions"] == ["api/hello/SPEC.md"]


@pytest.mark.parametrize("segment,message", [
    ("deep.tools", "more than one id part"),
    ("api", "already exists"),
    ("util", "already called that"),
])
def test_rename_refuses_what_cannot_be(graph_root, segment, message):
    n = parser.load_nodes(graph_root)
    with pytest.raises(ValueError, match=message):
        nodes.rename_plan(graph_root, "util", segment, n)
    assert (graph_root / "util" / "SPEC.md").exists()


def test_rename_plan_changes_nothing(graph_root):
    before = {p: p.read_text(encoding="utf-8") for p in graph_root.rglob("SPEC.md")}
    plan = nodes.rename_plan(graph_root, "util", "tools", parser.load_nodes(graph_root))
    assert plan["rewritten"] == ["SPEC.md", "api/hello/SPEC.md", "util/SPEC.md"]
    assert {p: p.read_text(encoding="utf-8") for p in graph_root.rglob("SPEC.md")} == before


def test_a_renamed_node_keeps_its_history(graph_root):
    """intents.jsonl is kept by id: without a `renamed` entry the growth record of
    the node would simply end at the old name."""
    from engine import intents
    nodes.rename_node(graph_root, "util", "tools", parser.load_nodes(graph_root), by="me")
    [entry] = intents.history(graph_root, "tools")
    assert entry["action"] == "renamed" and entry["intent"] == "renamed from util"


def test_cli_rename(graph_root, capsys):
    import cli
    assert cli.main(["rename", str(graph_root), "util", "tools", "--by", "me"]) == 0
    out = capsys.readouterr().out
    assert "renamed   util -> tools" in out and "moved     util/SPEC.md -> tools/SPEC.md" in out
    assert cli.main(["rename", str(graph_root), "tools", "a.b"]) == 2
