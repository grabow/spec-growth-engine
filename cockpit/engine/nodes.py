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

import re
import shutil
from pathlib import Path

import frontmatter

from . import graph

SPEC = "SPEC.md"


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
    if parent_id not in nodes:
        raise ValueError(f"unknown parent: {parent_id}")
    parent = nodes[parent_id]
    # the whole id typed where only its last part belongs -- `core.sound.player`
    # under core.sound -- made `core.sound.core.sound.player`; _segment reads it
    segment = _segment(nodes, parent_id, segment)
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


def _segment(nodes: dict[str, dict], parent_id: str | None, segment: str) -> str:
    """The last id part, as typed: spaces become dashes; the whole id typed instead
    (`core.sound.player` under core.sound) is read as its last part; anything still
    holding a dot is refused -- a segment is ONE id part."""
    segment = segment.strip().strip("/").replace(" ", "-")
    parent = nodes.get(parent_id) if parent_id else None
    if parent and parent.get("kind") != "system" and segment.startswith(f"{parent_id}."):
        segment = segment[len(parent_id) + 1:]
    if not segment:
        raise ValueError("segment name is empty")
    if "." in segment:
        raise ValueError(f"'{segment}' is more than one id part: a segment is the LAST "
                         "part of the id. For a node further down, pick the node above "
                         "it as the parent.")
    return segment


def rename_plan(root: str | Path, node_id: str, segment: str,
                nodes: dict[str, dict]) -> dict:
    """What renaming `node_id` to the new last id part `segment` would do -- and
    nothing done yet. Raises ValueError for a rename that cannot be.

    {"ids": {old: new} (the node and every descendant whose id carries it),
     "moves": [(old SPEC.md, new SPEC.md)] (project-root-relative),
     "rewritten": [SPEC.md files whose fields name a renamed id]}

    Only the SPEC.md files move. A file beside one -- code kept in the spec
    tree, notes -- stays where it is, and the `code` globs, project-root-relative,
    keep naming the same files: renaming a node never re-points ownership
    (SPEC-GROWTH-ENGINE.md 3.2a). The code is renamed, if at all, as a change of
    its own (Revise the globs, let Codex move it)."""
    if node_id not in nodes:
        raise ValueError(f"unknown node: {node_id}")
    node = nodes[node_id]
    parent_id = node.get("parent")
    segment = _segment(nodes, parent_id, segment)
    parent = nodes.get(parent_id) if parent_id else None
    new_id = compute_id(parent, segment) if parent else segment
    if new_id == node_id:
        raise ValueError(f"{node_id} is already called that")
    below = [d for d in nodes if d != node_id and node_id in graph.spine(nodes, d)]
    ids = {node_id: new_id}
    for d in below:
        if d.startswith(f"{node_id}."):
            ids[d] = new_id + d[len(node_id):]
    taken = [new for old, new in ids.items() if new in nodes and new not in ids]
    if taken:
        raise ValueError(f"node already exists: {', '.join(taken)}")

    root = Path(root).resolve()
    moves: list[tuple[str, str]] = []
    if parent is not None:                     # the root's SPEC.md stays at the root
        old_dir = Path(node["_dir"]).resolve()
        new_dir = old_dir.parent / segment
        if (new_dir / SPEC).exists():
            raise ValueError(f"{(new_dir / SPEC).relative_to(root)} already exists")
        for nid in [node_id, *below]:
            path = Path(nodes[nid]["_path"]).resolve()
            if path.is_relative_to(old_dir):
                moves.append((str(path.relative_to(root)),
                              str((new_dir / path.relative_to(old_dir)).relative_to(root))))
    rewritten = sorted(str(Path(m["_path"]).resolve().relative_to(root))
                       for m in nodes.values() if _renamed(m, ids))
    return {"ids": ids, "moves": moves, "rewritten": rewritten}


def rename_node(root: str | Path, node_id: str, segment: str,
                nodes: dict[str, dict], *, by: str = "") -> dict:
    """Rename `node_id` -- and its subtree -- to the new last id part `segment`:
    every field that names a renamed id is rewritten (`id`, `parent`,
    `depends_on`, `design.children`, a decision request's `target`), the SPEC.md
    files move (rename_plan), and the folders they leave empty go. The plan, plus
    "mentions": files whose PROSE still names an old id -- not rewritten, for
    the human to read: a sentence is not a reference the engine can be sure of.

    What follows is the gate's, as for any change: the old ids leave the graph
    and the new ones arrive, SOFT -- HARD where another node depended on one.
    The growth record (intents.jsonl) is kept by id, so each renamed node gets
    a `renamed` entry naming its old id: its history does not end at the rename."""
    from . import intents, lifecycle
    plan = rename_plan(root, node_id, segment, nodes)
    root = Path(root).resolve()
    ids = plan["ids"]
    for meta in nodes.values():
        if _renamed(meta, ids):
            path = Path(meta["_path"])
            post = frontmatter.load(path)
            post.metadata.update(_renamed(post.metadata, ids))
            _write(path, post)
    left: set[Path] = set()
    for old, new in plan["moves"]:
        src, dst = root / old, root / new
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        left.add(src.parent)
    for directory in sorted(left, key=lambda d: len(d.parts), reverse=True):
        while directory != root and directory.is_relative_to(root):
            _rmdir_if_empty(directory)
            if directory.exists():
                break
            directory = directory.parent
    for old, new in ids.items():
        intents.record(root, new, "renamed", f"renamed from {old}", by=by, gate=None)
        lifecycle.log_autonomy(root, {"actor": intents.author(), "by": by,
                                      "action": "renamed", "node": new, "from": old})
    return {**plan, "mentions": _mentions(root, ids)}


def rename_text(result: dict) -> str:
    """What a rename did, for the CLI and the cockpit."""
    lines = [f"renamed   {old} -> {new}" for old, new in result["ids"].items()]
    lines += [f"moved     {old} -> {new}" for old, new in result["moves"]]
    lines += [f"rewrote   {path}" for path in result["rewritten"]]
    lines += [f"mentions  {path}  (prose still names an old id -- read it)"
              for path in result.get("mentions") or []]
    lines += ["code      untouched: the globs still name the same files. To rename the "
              "code too, Revise the globs and let Codex move it.",
              "next      run the tests (evidence is kept per id), then the gate -- a "
              "renamed node others depended on is a HARD change for H to accept"]
    return "\n".join(lines)


def _renamed(meta: dict, ids: dict[str, str]) -> dict:
    """The fields of `meta` that name a renamed id, with the new ids -- {} when
    none does. Those fields: `id`, `parent`, `depends_on`, `design.children`, a
    decision request's `target`."""
    def one(value):
        return ids.get(value, value) if isinstance(value, str) else value

    def many(value):
        return [one(v) for v in value] if isinstance(value, list) else one(value)

    out: dict = {}
    for key in ("id", "parent"):
        if one(meta.get(key)) != meta.get(key):
            out[key] = one(meta[key])
    if many(meta.get("depends_on")) != meta.get("depends_on"):
        out["depends_on"] = many(meta["depends_on"])
    design = meta.get("design")
    if isinstance(design, dict) and many(design.get("children")) != design.get("children"):
        out["design"] = {**design, "children": many(design["children"])}
    requests = meta.get("decision_requests")
    if isinstance(requests, list):
        moved = [{**r, "target": one(r.get("target"))} if isinstance(r, dict) else r
                 for r in requests]
        if moved != requests:
            out["decision_requests"] = moved
    return out


def _mentions(root: Path, ids: dict[str, str]) -> list[str]:
    """Files whose text still names an old id: SPEC.md prose, ARCHITECTURE.md,
    TASK.md. A path segment of the same name (`util/*.py` for the id `util`) is
    a path, not the id."""
    pattern = re.compile("|".join(rf"(?<![\w./]){re.escape(old)}(?![\w/-])"
                                  for old in sorted(ids, key=len, reverse=True)))
    hits = []
    for path in sorted([*root.rglob(SPEC), root / "ARCHITECTURE.md", root / "TASK.md"]):
        try:
            if pattern.search(path.read_text(encoding="utf-8")):
                hits.append(str(path.relative_to(root)))
        except OSError:
            continue
    return hits


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
    _write(path, post)


def _write(path: Path, post) -> None:
    """A SPEC.md back to disk, its keys in the order they were (id, parent, kind,
    ... -- yaml.dump would sort them, and every touched file would look rewritten)."""
    path.write_text(frontmatter.dumps(post, sort_keys=False) + "\n", encoding="utf-8")


def _rmdir_if_empty(directory: Path) -> None:
    try:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    except OSError:
        pass
