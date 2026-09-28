"""Two edge types: ownership tree (parent) and dependency DAG (depends_on)."""
from __future__ import annotations

import networkx as nx


def ownership_tree(nodes: dict[str, dict]) -> nx.DiGraph:
    """parent -> child edges (the Spine follows these)."""
    g = nx.DiGraph()
    for nid, n in nodes.items():
        g.add_node(nid)
        parent = n.get("parent")
        if parent:
            g.add_edge(parent, nid)
    return g


def dependency_dag(nodes: dict[str, dict]) -> nx.DiGraph:
    """node -> dependency edges ('uses the contract of')."""
    g = nx.DiGraph()
    for nid, n in nodes.items():
        g.add_node(nid)
        for dep in n.get("depends_on") or []:
            g.add_edge(nid, dep)
    return g


def spine(nodes: dict[str, dict], target: str) -> list[str]:
    """Ownership path root -> ... -> parent -> target."""
    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = target
    while cur and cur in nodes and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = nodes[cur].get("parent")
    return list(reversed(chain))


def dependency_cycles(nodes: dict[str, dict]) -> list[list[str]]:
    """Dependency edges must be acyclic; return any cycles found."""
    return list(nx.simple_cycles(dependency_dag(nodes)))
