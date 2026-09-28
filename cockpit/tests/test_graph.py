from engine import graph, parser


def test_spine_root_to_leaf(graph_root):
    nodes = parser.load_nodes(graph_root)
    assert graph.spine(nodes, "api.hello") == ["app", "api", "api.hello"]
    assert graph.spine(nodes, "app") == ["app"]


def test_no_cycles_in_clean_graph(graph_root):
    nodes = parser.load_nodes(graph_root)
    assert graph.dependency_cycles(nodes) == []


def test_cycle_detected():
    nodes = {
        "a": {"id": "a", "kind": "component", "parent": None, "depends_on": ["b"]},
        "b": {"id": "b", "kind": "component", "parent": None, "depends_on": ["a"]},
    }
    cycles = graph.dependency_cycles(nodes)
    assert cycles and set(cycles[0]) == {"a", "b"}
