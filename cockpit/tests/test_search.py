"""Find in what the human writes -- the goal, the architecture, every spec."""
from engine import parser, search


def test_find_names_every_line_and_where_it_is(graph_root):
    (graph_root / "TASK.md").write_text("# Task\n- greet prints hallo\n", encoding="utf-8")
    hits = search.find(graph_root, parser.load_nodes(graph_root), "HALLO")
    assert hits[0] == {"where": "TASK.md", "file": "TASK.md", "line": 2,
                       "text": "- greet prints hallo"}
    assert any(h["where"] == "api.hello" for h in hits)          # the spec says it too
    assert search.find(graph_root, parser.load_nodes(graph_root), "  ") == []


def test_locate_finds_a_quote_yaml_wrapped_over_two_lines(graph_root):
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace(
        "log()", "log() -- the tones are generated\n    in memory with no file read"),
        encoding="utf-8")
    nodes = parser.load_nodes(graph_root)
    at = search.locate(graph_root, nodes, "util", "generated in memory")
    line = spec.read_text(encoding="utf-8").splitlines()[at["line"] - 1]
    assert at["file"] == "util/SPEC.md" and "generated" in line
    assert search.locate(graph_root, nodes, "util", "not there at all")["line"] is None
    assert search.locate(graph_root, nodes, "no.such.node", "x") is None


def test_cli_find(graph_root, capsys):
    import cli
    assert cli.main(["find", str(graph_root), "hallo"]) == 0
    assert "api.hello:" in capsys.readouterr().out
    assert cli.main(["find", str(graph_root), "zebra"]) == 1
