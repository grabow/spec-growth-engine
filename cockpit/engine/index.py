"""Generate `project.index.json`: a deterministic, machine-readable snapshot of the
spec graph + capabilities + edges + test evidence.

Engine-owned and GENERATED -- never hand-authored. It is the queryable view the
Capability Registry concept refers to, the natural home for tooling/CLI queries,
and it surfaces test evidence alongside each node's status.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path

from . import accepted, capability, decisions, evidence, waivers, lifecycle, parser

INDEX_FILE = "project.index.json"


def _jsonable(value):
    """Make a YAML-derived value JSON-serializable.

    `waiver` is copied into the index verbatim, and PyYAML turns an unquoted
    `expires: 2099-01-01` -- the spelling GOVERNANCE.md §8 itself uses -- into a
    datetime.date, which json.dumps cannot write. Normalising the whole tree
    rather than that one field keeps the rule general: build_index promises a
    machine-readable snapshot, so whatever a human put in the frontmatter must
    come out writable.
    """
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def build_index(nodes: dict[str, dict], project_root: str | Path) -> dict:
    """Build the index dict from the loaded nodes + code evidence + test evidence."""
    root = str(project_root)
    ev = evidence.build_evidence(nodes, project_root)
    owners = ev["owners"]
    test_ev = lifecycle.load_evidence(project_root)

    # node-level code edges (owner(importer) -> owner(imported), cross-owner only)
    code_edges: set[tuple[str, str]] = set()
    for a, b in ev["edges"]:
        oa = next(iter(owners[a])) if len(owners[a]) == 1 else None
        ob = next(iter(owners[b])) if len(owners[b]) == 1 else None
        if oa and ob and oa != ob:
            code_edges.add((oa, ob))

    node_index = {}
    for nid, n in nodes.items():
        contract = n.get("contract") if isinstance(n.get("contract"), dict) else {}
        node_index[nid] = {
            "id": nid,
            "parent": n.get("parent"),
            "kind": n.get("kind"),
            "status": n.get("status"),
            "depends_on": list(n.get("depends_on") or []),
            "children": sorted(k for k, v in nodes.items() if v.get("parent") == nid),
            "code": list(n.get("code") or []),
            "provides": contract.get("provides", []),
            "test_evidence": test_ev.get(nid),
            "waiver": n.get("waiver"),
        }

    # GOVERNANCE 8: a node with an open waiver does not count as done.
    excepted = waivers.not_done(nodes)
    waiting = decisions.not_done(nodes)
    held = accepted.not_done(nodes, root)   # pending HARD changes (accepted.py)
    done = {nid for nid, n in nodes.items()
            if n.get("status") == "verified" and nid not in excepted | waiting | held}

    return _jsonable({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": root,
        "node_count": len(nodes),
        "progress": {
            "verified": sorted(done),
            "open_waivers": sorted(excepted),
            "pending_decisions": [
                {"node": n, "target": tgt, "proposal": prop}
                for n, tgt, prop in decisions.pending(nodes)
            ],
            "pending_hard": sorted(held),
            "done": len(done),
            "of": len(nodes),
        },
        "nodes": node_index,
        "capabilities": capability.build_registry(nodes),
        "edges": {
            "ownership": sorted([p, c] for c, p in
                                ((cid, n.get("parent")) for cid, n in nodes.items())
                                if p),
            "dependency": sorted([nid, d] for nid, n in nodes.items()
                                 for d in (n.get("depends_on") or [])),
            "code": sorted([a, b] for a, b in code_edges),
        },
    })


def write_index(project_root: str | Path) -> Path:
    """Load the project, build the index, write `project.index.json`, return its path."""
    nodes = parser.load_nodes(project_root)
    index = build_index(nodes, project_root)
    path = Path(project_root) / INDEX_FILE
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return path
