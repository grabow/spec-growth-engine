"""Persistent, non-secret cockpit settings (cockpit.json next to app.py).

Holds: the planner model, how the coder CLI is invoked, the last working
directory (so the cockpit reopens where you left off), and per-project graph
view state. The API key is NOT stored here - it stays in .env. Values seed from
the environment on first run.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "cockpit.json"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

# Which model plays which role is NOT a cockpit setting: every role has its own
# endpoint in cockpit/.env (agent/llm.py), and only there -- a second place would
# silently overrule the first.
_DEFAULTS = {
    "last_root": "",
    # let the planner's model re-rank capability search + confirm duplicates
    # semantically; falls back to lexical automatically when the planner has no
    # endpoint.
    "semantic_match": os.environ.get("SGE_SEMANTIC_MATCH", "1") not in ("0", "false", ""),
    # the draft gate D0..D2: 0 off, 1 advisory H'
    # draft review, 2 auto-clear the draft gate. The cockpit caps it at D2
    # (engine.autonomy.DRAFT_MAX); the delegation and a run are not set here.
    # Degrades to nothing without an API key. The deterministic gate is unaffected.
    "draft_gate": _int_env("SGE_DRAFT_GATE", 1),
    # graph window state per spec root: {root: {"collapsed": [...], "zoom": 1.0}}.
    # Purely cosmetic -- a missing or corrupt entry just falls back to the default.
    "graph_view": {},
}

ZOOM_MIN, ZOOM_MAX = 0.4, 2.5
_GRAPH_VIEW_LIMIT = 20  # keep the N most recently used roots, drop the rest


def load() -> dict:
    cfg = copy.deepcopy(_DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: stored[k] for k in _DEFAULTS if k in stored})
        except (OSError, ValueError):
            pass
    return cfg


def save(cfg: dict) -> None:
    data = {k: cfg.get(k, _DEFAULTS[k]) for k in _DEFAULTS}
    try:
        CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def graph_view_get(cfg: dict, root: str) -> tuple[set[str] | None, float]:
    """Stored (collapsed node ids, zoom) for one spec root.

    Returns collapsed=None when nothing was stored for this root, so the caller
    can apply its own default. Anything unreadable degrades to the default too --
    view state is never worth an error dialog.
    """
    entry = (cfg.get("graph_view") or {}).get(_root_key(root))
    if not isinstance(entry, dict):
        return None, 1.0
    stored = entry.get("collapsed")
    collapsed = ({str(n) for n in stored} if isinstance(stored, list) else None)
    try:
        zoom = min(max(float(entry.get("zoom", 1.0)), ZOOM_MIN), ZOOM_MAX)
    except (TypeError, ValueError):
        zoom = 1.0
    return collapsed, zoom


def graph_view_set(cfg: dict, root: str, collapsed: set[str], zoom: float) -> None:
    """Remember the graph window state for one spec root, most recent last."""
    store = cfg.setdefault("graph_view", {})
    if not isinstance(store, dict):
        store = cfg["graph_view"] = {}
    key = _root_key(root)
    store.pop(key, None)  # re-insert at the end: insertion order = recency
    store[key] = {"collapsed": sorted(collapsed),
                  "zoom": round(min(max(float(zoom), ZOOM_MIN), ZOOM_MAX), 3)}
    while len(store) > _GRAPH_VIEW_LIMIT:
        store.pop(next(iter(store)))


def _root_key(root: str) -> str:
    try:
        return str(Path(root).resolve())
    except OSError:
        return str(root)
