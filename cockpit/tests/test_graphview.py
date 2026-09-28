"""Node-graph view: collapse, dependency edges, orphan detection.

These are the pure layout helpers; the Tk drawing itself is not under test.
"""
import app


def _multi_container():
    """1 system, 3 containers, 4 components each; web depends on api."""
    nodes = {"sys": {"kind": "system", "parent": None}}
    for c in ("api", "web", "worker"):
        nodes[f"sys.{c}"] = {"kind": "container", "parent": "sys"}
        for k in range(4):
            nodes[f"sys.{c}.c{k}"] = {"kind": "component", "parent": f"sys.{c}"}
    nodes["sys.web.c0"]["depends_on"] = ["sys.api.c1"]
    return nodes


def test_containers_are_laid_out_side_by_side_without_overlap():
    nodes = _multi_container()
    pos, _ = app._node_graph_layout(nodes)
    xs = [pos[f"sys.{c}"][0] for c in ("api", "web", "worker")]
    assert xs == sorted(xs) and len(set(xs)) == 3
    assert min(abs(a - b) for a, b in zip(xs, xs[1:])) >= 170  # wider than a box
    ys = {pos[f"sys.{c}"][1] for c in ("api", "web", "worker")}
    assert len(ys) == 1 and pos["sys"][1] < ys.pop()


def test_collapsing_containers_shrinks_the_canvas():
    nodes = _multi_container()
    wide, _ = app._node_graph_layout(nodes)
    narrow, edges = app._node_graph_layout(nodes, collapsed=app._default_collapsed(nodes))
    assert len(narrow) == 4  # system + 3 containers
    assert max(x for x, _ in narrow.values()) < max(x for x, _ in wide.values()) / 2
    assert all(child in narrow for _, child in edges)  # no edge to a hidden box


def test_default_collapsed_is_everything_below_container_level():
    nodes = _multi_container()
    assert app._default_collapsed(nodes) == {"sys.api", "sys.web", "sys.worker"}


def test_childless_container_is_not_collapsible():
    nodes = {"sys": {"kind": "system", "parent": None},
             "sys.empty": {"kind": "container", "parent": "sys"}}
    assert app._default_collapsed(nodes) == set()


def test_hidden_counts_attribute_to_the_nearest_visible_parent():
    nodes = _multi_container()
    collapsed = {"sys.api"}
    pos, _ = app._node_graph_layout(nodes, collapsed=collapsed)
    counts = app._hidden_counts(nodes, pos)
    assert counts["sys.api"] == 4      # its 4 components
    assert counts["sys.web"] == 0      # expanded
    assert counts["sys"] == 0          # hidden nodes belong to sys.api, not to sys


def test_dependency_edge_is_lifted_to_the_collapsed_container():
    nodes = _multi_container()
    pos, _ = app._node_graph_layout(nodes, collapsed=app._default_collapsed(nodes))
    assert app._dependency_edges(nodes, pos) == [("sys.web", "sys.api")]


def test_dependency_edge_is_kept_between_visible_components():
    nodes = _multi_container()
    pos, _ = app._node_graph_layout(nodes)
    assert app._dependency_edges(nodes, pos) == [("sys.web.c0", "sys.api.c1")]


def test_dependency_inside_one_collapsed_subtree_is_dropped():
    nodes = _multi_container()
    nodes["sys.api.c0"]["depends_on"] = ["sys.api.c1"]
    pos, _ = app._node_graph_layout(nodes, collapsed={"sys.api"})
    assert ("sys.api", "sys.api") not in app._dependency_edges(nodes, pos)


def test_dependency_on_an_unknown_node_is_ignored():
    nodes = _multi_container()
    nodes["sys.web.c1"]["depends_on"] = ["nope.gone"]
    pos, _ = app._node_graph_layout(nodes)
    assert all("nope.gone" not in e for e in app._dependency_edges(nodes, pos))


def test_orphan_node_is_detected_not_silently_rooted():
    nodes = {"sys": {"kind": "system", "parent": None},
             "sys.api": {"kind": "container", "parent": "sys"},
             "stray": {"kind": "container", "parent": "deleted.parent"}}
    assert app._orphan_nodes(nodes) == {"stray"}
    pos, _ = app._node_graph_layout(nodes)
    assert pos["stray"][1] == pos["sys"][1]  # still drawn at root level


def test_real_root_is_not_an_orphan():
    assert app._orphan_nodes({"sys": {"kind": "system", "parent": None}}) == set()


def test_box_exit_lands_on_the_border():
    x, y, w, h = 100, 100, 170, 54
    assert app._box_exit(x, y, 400, 100, w, h) == (185, 100)   # straight right
    assert app._box_exit(x, y, 100, 400, w, h) == (100, 127)   # straight down
    assert app._box_exit(x, y, x, y, w, h) == (x, y)           # degenerate


def test_zoom_scales_the_layout_linearly():
    nodes = _multi_container()
    base, _ = app._node_graph_layout(nodes, x_gap=230, y_gap=130, x_origin=120, y_origin=70)
    half, _ = app._node_graph_layout(nodes, x_gap=115, y_gap=65, x_origin=60, y_origin=35)
    assert max(x for x, _ in half.values()) * 2 == max(x for x, _ in base.values())
    assert half["sys.api"][1] * 2 == base["sys.api"][1]


def test_scaled_font_never_collapses_to_nothing():
    assert app._scaled_font(("TkFixedFont", 12), 1.0) == ("TkFixedFont", 12)
    assert app._scaled_font(("TkFixedFont", 12), 0.5) == ("TkFixedFont", 6)
    assert app._scaled_font(("TkFixedFont", 12), 0.01)[1] >= 6  # floor, not 0


def test_fit_label_truncates_only_when_needed():
    assert app._fit_label("sys.api", 200, 12) == "sys.api"
    short = app._fit_label("sys.container.component", 60, 12)
    assert short.endswith("…") and len(short) < len("sys.container.component")
    assert len(app._fit_label("anything", 1, 12)) <= 3


def test_widget_size_ignores_an_unmapped_1x1_widget():
    class Unmapped:
        def winfo_width(self): return 1
        def winfo_height(self): return 1
        def winfo_reqwidth(self): return 1
        def winfo_reqheight(self): return 1

    class Mapped(Unmapped):
        def winfo_width(self): return 820
        def winfo_height(self): return 540

    assert app._widget_size(Unmapped(), fallback=(900, 600)) == (900, 600)
    assert app._widget_size(Mapped()) == (820, 540)
