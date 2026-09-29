"""Parse SPEC.md nodes and the transversal ARCHITECTURE.md."""
from __future__ import annotations

from pathlib import Path

import frontmatter

SPEC_NAME = "SPEC.md"
ARCH_NAME = "ARCHITECTURE.md"


def load_nodes(root: str | Path) -> dict[str, dict]:
    """Walk `root` for SPEC.md files and return {id: metadata}.

    Each node keeps its frontmatter plus three derived fields:
      _path : absolute path to the SPEC.md
      _dir  : the node's directory (used to resolve `code` globs)
      _body : the markdown prose below the frontmatter
    """
    root = Path(root)
    nodes: dict[str, dict] = {}
    for spec in sorted(root.rglob(SPEC_NAME)):
        try:
            post = frontmatter.load(spec)
        except Exception:
            # A single malformed SPEC.md must NOT break the whole load. Skip it
            # here; invalid_specs() surfaces it as a HARD error in validate/drift.
            continue
        meta = dict(post.metadata)
        nid = meta.get("id")
        if not nid:
            continue
        # normalise depends_on to a clean list of strings (tolerate malformed YAML)
        raw_deps = meta.get("depends_on")
        if isinstance(raw_deps, list):
            meta["depends_on"] = [d for d in raw_deps if isinstance(d, str)]
        elif isinstance(raw_deps, str):
            meta["depends_on"] = [raw_deps]
        elif raw_deps is not None:
            meta["depends_on"] = []
        meta["_path"] = str(spec)
        meta["_dir"] = str(spec.parent)
        meta["_body"] = post.content
        nodes[nid] = meta
    return nodes


def load_architecture(root: str | Path) -> str:
    """Return the cross-cutting ARCHITECTURE.md text (or '' if absent)."""
    arch = Path(root) / ARCH_NAME
    return arch.read_text(encoding="utf-8") if arch.exists() else ""


def unloaded_specs(root: str | Path) -> list[str]:
    """SPEC.md files that parse but do not become a node, one line each: one
    with no `id` (load_nodes skips it) and one whose `id` another SPEC.md
    already has (the later replaces the earlier in the graph). Both vanished
    without a word -- the code they claim then looks orphaned, and the real
    cause was nowhere -- so validate and drift report them as HARD errors, like
    a file that does not parse (invalid_specs)."""
    root = Path(root)
    out: list[str] = []
    first: dict[str, str] = {}
    for spec in sorted(root.rglob(SPEC_NAME)):
        try:
            meta = frontmatter.load(spec).metadata
        except Exception:
            continue                      # invalid_specs reports those
        rel = str(spec.relative_to(root)) if spec.is_relative_to(root) else str(spec)
        nid = meta.get("id")
        if not nid:
            out.append(f"SPEC.md without id: {rel} -- it is no node, and whatever it "
                       "claims is unowned")
        elif nid in first:
            out.append(f"duplicate id '{nid}': {first[nid]} and {rel} -- the graph "
                       "holds only one of them")
        else:
            first[nid] = rel
    return out


def invalid_specs(root: str | Path) -> list[tuple[str, str]]:
    """Find SPEC.md files whose YAML frontmatter does not parse.

    Returns [(relative_path, short_error)]. Used to surface broken specs as HARD
    errors instead of silently dropping the node.
    """
    root = Path(root)
    bad: list[tuple[str, str]] = []
    for spec in sorted(root.rglob(SPEC_NAME)):
        try:
            frontmatter.load(spec)
        except Exception as exc:
            rel = str(spec.relative_to(root)) if spec.is_relative_to(root) else str(spec)
            msg = str(exc).splitlines()[0]
            bad.append((rel, msg))
    return bad
