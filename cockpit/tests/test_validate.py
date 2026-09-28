from engine import parser, validate


def test_clean_graph_passes(graph_root):
    nodes = parser.load_nodes(graph_root)
    out = validate.run(nodes, str(graph_root))
    assert out.strip().endswith("gate: pass")


def test_dependency_on_ancestor_blocks(graph_root):
    nodes = parser.load_nodes(graph_root)
    nodes["api.hello"]["depends_on"] = ["api"]  # parent = ownership, not usage
    out = validate.run(nodes)
    assert "ownership line" in out
    assert out.strip().endswith("gate: BLOCK")


def test_self_dependency_blocks(graph_root):
    nodes = parser.load_nodes(graph_root)
    nodes["api.hello"]["depends_on"] = ["api.hello"]
    out = validate.run(nodes)
    assert "ownership line" in out and out.strip().endswith("gate: BLOCK")


def test_undeclared_target_blocks(graph_root):
    nodes = parser.load_nodes(graph_root)
    nodes["api.hello"]["depends_on"] = ["ghost"]
    out = validate.run(nodes)
    assert "undeclared dependency" in out and out.strip().endswith("gate: BLOCK")


def test_invalid_yaml_surfaced(graph_root):
    (graph_root / "util" / "SPEC.md").write_text("---\nid: util\nx:\n- `boom`\n---\n", encoding="utf-8")
    nodes = parser.load_nodes(graph_root)
    out = validate.run(nodes, str(graph_root))
    assert "invalid YAML" in out and out.strip().endswith("gate: BLOCK")
