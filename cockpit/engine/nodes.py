"""Deterministic node CRUD on the filesystem.

Nodes are NOT fixed in the engine - they are your SPEC.md files. This module
creates and deletes them, keeping the parent's `design.children` list in sync.
It authors no contract content (that is the planner's job); a new node starts as
an empty skeleton you then fill via the planner.

Layout rule (matches the examples):
  - a child's directory   = parent_dir / <segment>
  - a child's id          = <segment>            if the parent is the system root
                          = <parent_id>.<segment> otherwise
"""
from __future__ import annotations

from pathlib import Path

import frontmatter


def bootstrap_root(root_dir: str, system_id: str = "app", purpose: str = "", force: bool = False) -> str:
    """Create the root SPEC.md (kind: system) + an ARCHITECTURE.md skeleton.

    Use this to start a brand-new spec graph in an empty target directory.
    Returns the path to the created root SPEC.md.
    """
    root = Path(root_dir)
    spec = root / "SPEC.md"
    if spec.exists() and not force:
        # Refuse only if it is already a VALID root node; a SPEC.md without an `id`
        # is broken (e.g. accidentally overwritten) and may be repaired/overwritten.
        try:
            existing = frontmatter.load(spec).metadata
        except Exception:
            existing = {}
        if existing.get("id"):
            raise ValueError(
                f"a valid root SPEC.md already exists at {spec} (id={existing['id']})"
            )
    root.mkdir(parents=True, exist_ok=True)

    post = frontmatter.Post(
        "# System context\n",
        id=system_id,
        parent=None,
        kind="system",
        contract={"purpose": purpose.strip() or "TODO: one or two sentences."},
        design={"children": []},
        code=[],
        status="specd",
    )
    spec.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")

    arch = root / "ARCHITECTURE.md"
    if not arch.exists():
        arch.write_text(
            "# Architecture (cross-cutting)\n\n"
            "## Invariants (apply everywhere)\n- TODO\n\n"
            "## Decisions (ADRs)\n- TODO\n",
            encoding="utf-8",
        )
    return str(spec)


def compute_id(parent: dict, segment: str) -> str:
    return segment if parent.get("kind") == "system" else f"{parent['id']}.{segment}"


def children_of(nodes: dict[str, dict], node_id: str) -> list[str]:
    return sorted(k for k, v in nodes.items() if v.get("parent") == node_id)


def dependents_of(nodes: dict[str, dict], node_id: str) -> list[str]:
    return sorted(k for k, v in nodes.items() if node_id in (v.get("depends_on") or []))


def new_node(
    parent_id: str,
    segment: str,
    kind: str,
    nodes: dict[str, dict],
    layout_invariants: list[str] | None = None,
    manifest: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Create a skeleton SPEC.md under `parent_id`. Returns (new_id, path).

    `layout_invariants` (used for containers) are invariant line templates that may
    contain `{container}`; it is substituted here with the node's project-root-
    relative path so the convention reads concretely (the Spine carries these down
    to the container's components). The catalog itself lives outside the engine.

    `manifest` (file name, content) is that container's BUILD manifest, from the
    same catalog entry: the layout convention says in prose where the package root
    is, the manifest says it again in the build tool's language, and seeding them
    together is the only thing that keeps the two spellings of one decision in
    step. It is written only if no such file is there, and the container declares
    it as its own `code` -- a file no node owns is an orphan and blocks the gate.
    The engine stays language-agnostic: it writes bytes it was handed.
    """
    segment = segment.strip().strip("/").replace(" ", "-")
    if not segment:
        raise ValueError("segment name is empty")
    if parent_id not in nodes:
        raise ValueError(f"unknown parent: {parent_id}")
    parent = nodes[parent_id]
    nid = compute_id(parent, segment)
    if nid in nodes:
        raise ValueError(f"node already exists: {nid}")

    node_dir = Path(parent["_dir"]) / segment
    spec = node_dir / "SPEC.md"
    if spec.exists():
        raise ValueError(f"SPEC.md already exists at {spec}")
    node_dir.mkdir(parents=True, exist_ok=True)

    contract: dict = {"provides": []}
    container_path = nid.replace(".", "/")
    if layout_invariants:
        contract["invariants"] = [
            line.replace("{container}", container_path) for line in layout_invariants
        ]
    owns: list[str] = []
    if manifest:
        name, text = manifest
        path = node_dir / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        owns = [f"{container_path}/{name}"]

    post = frontmatter.Post(
        f"# {nid}\n",
        id=nid,
        parent=parent_id,
        kind=kind,
        contract=contract,
        design={"approach": ""},
        depends_on=[],
        code=owns,
        status="specd",
    )
    spec.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    _rewrite_children(parent, add=nid)
    return nid, str(spec)


def delete_node(
    node_id: str, nodes: dict[str, dict], recursive: bool = False
) -> tuple[list[str], list[str]]:
    """Delete a node (and optionally its subtree). Returns (removed_ids, dependents)."""
    if node_id not in nodes:
        raise ValueError(f"unknown node: {node_id}")
    kids = children_of(nodes, node_id)
    if kids and not recursive:
        raise ValueError(f"node has children {kids}; delete them first or use recursive")

    order = _subtree_postorder(nodes, node_id) if recursive else [node_id]
    removed: list[str] = []
    for nid in order:
        path = Path(nodes[nid]["_path"])
        if path.exists():
            path.unlink()
        _rmdir_if_empty(path.parent)
        removed.append(nid)

    parent_id = nodes[node_id].get("parent")
    if parent_id and parent_id in nodes:
        _rewrite_children(nodes[parent_id], remove=node_id)

    return removed, dependents_of(nodes, node_id)


# ---- internals -----------------------------------------------------------
def _subtree_postorder(nodes: dict[str, dict], root_id: str) -> list[str]:
    out: list[str] = []

    def rec(nid: str) -> None:
        for child in children_of(nodes, nid):
            rec(child)
        out.append(nid)

    rec(root_id)
    return out


def _rewrite_children(parent: dict, *, add: str | None = None, remove: str | None = None) -> None:
    path = Path(parent["_path"])
    post = frontmatter.load(path)
    design = post.metadata.get("design") or {}
    children = list(design.get("children") or [])
    if add and add not in children:
        children.append(add)
    if remove and remove in children:
        children.remove(remove)
    design["children"] = children
    post.metadata["design"] = design
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


def _rmdir_if_empty(directory: Path) -> None:
    try:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    except OSError:
        pass
