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


def test_a_spec_without_id_is_reported_not_skipped_in_silence(graph_root):
    """load_nodes skips it -- and its code looked orphaned with the cause nowhere."""
    stray = graph_root / "api" / "extra" / "SPEC.md"
    stray.parent.mkdir()
    stray.write_text("---\nparent: api\nkind: component\n---\n# no id\n", encoding="utf-8")
    reported = parser.unloaded_specs(graph_root)
    assert len(reported) == 1 and reported[0].startswith("SPEC.md without id: api/extra/SPEC.md")


def test_a_duplicate_id_is_reported_with_both_files(graph_root):
    twin = graph_root / "api" / "twin" / "SPEC.md"
    twin.parent.mkdir()
    twin.write_text("---\nid: util\nparent: app\nkind: component\n---\n", encoding="utf-8")
    reported = parser.unloaded_specs(graph_root)
    assert reported == ["duplicate id 'util': api/twin/SPEC.md and util/SPEC.md -- the "
                        "graph holds only one of them"]


def test_validate_and_drift_block_on_a_spec_that_is_no_node(graph_root):
    from engine import drift, validate
    (graph_root / "notes").mkdir()
    (graph_root / "notes" / "SPEC.md").write_text("# just prose, no frontmatter\n",
                                                  encoding="utf-8")
    nodes = parser.load_nodes(graph_root)
    for report in (validate.run(nodes, str(graph_root)), drift.run(nodes, str(graph_root))):
        assert "SPEC.md without id: notes/SPEC.md" in report
        assert "HARD errors: 0" not in report


def test_the_example_graphs_have_no_spec_that_is_no_node():
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent
    for root in (here / "example", here / "example-ts"):
        assert parser.unloaded_specs(root) == [], root
