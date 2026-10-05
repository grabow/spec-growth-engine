"""The commit gate: validate + drift; on a pass E clears what is at SOFT or below."""
from engine import accepted, gate, parser


def _grow_util(graph_root):
    """An addition to util: SOFT, E's to clear."""
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("- log()", "- log()\n  - flush()"),
                    encoding="utf-8")


def test_a_passing_gate_clears_what_was_soft_and_shows_it(graph_root):
    accepted.accept_all(parser.load_nodes(graph_root), graph_root, by="setup")
    _grow_util(graph_root)
    result = gate.run(parser.load_nodes(graph_root), graph_root)
    assert not result["blocked"]
    assert [c["node"] for c in result["pending"]] == ["util"]
    assert result["cleared"] == [("util", "SOFT")]
    detailed = gate.text(result, details=True)
    assert "cleared by E on this PASS:" in detailed and "+ flush()" in detailed
    assert "+ flush()" not in gate.text(result)        # the CLI's report stays short
    assert accepted.changes(parser.load_nodes(graph_root), graph_root) == []


def test_a_blocked_gate_clears_nothing_and_says_what_waits(graph_root):
    accepted.accept_all(parser.load_nodes(graph_root), graph_root, by="setup")
    _grow_util(graph_root)
    hello = graph_root / "api" / "hello" / "SPEC.md"
    hello.write_text(hello.read_text(encoding="utf-8").replace("- util", "- nowhere"),
                     encoding="utf-8")                    # a HARD error: no such node
    result = gate.run(parser.load_nodes(graph_root), graph_root)
    assert result["blocked"] and result["cleared"] == [] and gate.hard_errors(result) >= 1
    assert "util" in [c["node"] for c in result["pending"]]
    assert "waiting for a passing gate, then cleared by E:" in gate.text(result, details=True)
