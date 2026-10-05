"""Find words in what the human writes: TASK.md, ARCHITECTURE.md and every
SPEC.md -- deterministic, no model.

  find(root, nodes, query)          every line holding `query`, case ignored
  locate(root, nodes, where, quote) the line where `quote` starts in one of them

A label names each file the way the cockpit opens it: the node's id for a
SPEC.md, else "TASK.md" or "ARCHITECTURE.md". `locate` is what makes a gap H'
names openable: it quotes a few words from where the gap sits, and a SPEC.md's
YAML wraps long text over lines, so the words are matched with whitespace
collapsed -- across a line break too.
"""
from __future__ import annotations

import re
from pathlib import Path

GOAL, ARCHITECTURE = "TASK.md", "ARCHITECTURE.md"


def files(root: str | Path, nodes: dict[str, dict]) -> list[tuple[str, Path]]:
    """(label, path) of everything searched: the goal, the architecture, then the
    specs by id."""
    root = Path(root)
    out = [(name, root / name) for name in (GOAL, ARCHITECTURE) if (root / name).is_file()]
    out += [(nid, Path(nodes[nid]["_path"])) for nid in sorted(nodes)
            if nodes[nid].get("_path")]
    return out


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def find(root: str | Path, nodes: dict[str, dict], query: str) -> list[dict]:
    """[{where, file, line, text}] for every line holding `query`, case ignored;
    `line` counts from 1, `file` is project-root-relative."""
    needle = query.strip().lower()
    if not needle:
        return []
    root = Path(root)
    hits = []
    for where, path in files(root, nodes):
        for n, text in enumerate(_lines(path), 1):
            if needle in text.lower():
                hits.append({"where": where, "file": _rel(path, root), "line": n,
                             "text": text.strip()})
    return hits


def locate(root: str | Path, nodes: dict[str, dict], where: str,
           quote: str) -> dict | None:
    """{where, file, line} of the first place `quote` stands in the file `where`
    names -- whitespace collapsed and case ignored, so a quote YAML wrapped over
    two lines is found where it starts. `line` is None when the words are not
    there verbatim; None for a `where` that names no file."""
    root = Path(root)
    path = dict(files(root, nodes)).get(where)
    if path is None:
        return None
    found = {"where": where, "file": _rel(path, root), "line": None}
    needle = _collapse(quote).lower()
    if not needle:
        return found
    text, starts = "", []
    for line in _lines(path):
        starts.append(len(text))
        text += _collapse(line) + " "
    at = text.lower().find(needle)
    if at >= 0:
        found["line"] = max(n for n, s in enumerate(starts, 1) if s <= at)
    return found


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
