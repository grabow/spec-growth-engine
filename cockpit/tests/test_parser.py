from engine import parser


def test_load_nodes_basic(graph_root):
    nodes = parser.load_nodes(graph_root)
    assert set(nodes) == {"app", "api", "api.hello", "util"}
    assert nodes["api.hello"]["parent"] == "api"


def test_depends_on_normalized_to_string_list(graph_root):
    nodes = parser.load_nodes(graph_root)
    assert nodes["api.hello"]["depends_on"] == ["util"]
    # node without depends_on key stays absent or empty-safe
    assert nodes["util"].get("depends_on", []) in ([], None)


def test_invalid_yaml_is_skipped_not_crashing(graph_root):
    # leading backtick is reserved in YAML -> invalid frontmatter
    bad = graph_root / "api" / "hello" / "SPEC.md"
    bad.write_text("---\nid: api.hello\ncontract:\n  x:\n  - `boom`\n---\n", encoding="utf-8")
    nodes = parser.load_nodes(graph_root)  # must not raise
    assert "api.hello" not in nodes  # dropped
    assert {"app", "api", "util"} <= set(nodes)


def test_invalid_specs_reports_bad_file(graph_root):
    bad = graph_root / "util" / "SPEC.md"
    bad.write_text("---\nid: util\nx:\n- `boom`\n---\n", encoding="utf-8")
    reported = parser.invalid_specs(graph_root)
    rels = [r for r, _ in reported]
    assert any("util/SPEC.md" in r for r in rels)
