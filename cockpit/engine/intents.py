"""The growth record: every intent a node was grown from, in order.

A spec is the RESULT of its growth; the intents are the steps. Before this, the
text of `--intent` and `--change` went to the planner once and was gone: how a
node had grown, and why, could not be read back, and a judge of intent
fidelity (H') could compare a change only with the last request, never with
the node's history. Growth is the intent author's decision (I, or H in the
cockpit -- ORCHESTRATOR.md "How the graph grows"); this is its record.

  <root>/.sge/intents.jsonl    append-only, one line per growth step
  { at, node, action: drafted | revised, author: I | H, by: <P's model>,
    intent: <the text as written>, gate: <the change set's gate> }

`author` is who WROTE the intent, not who formalized it: an agent run marks
itself through SGE_ACTOR (agent/codex_cli.py sets it for the roles it starts);
without it, the author is H -- a person at a terminal or in the cockpit.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

_FILE = Path(".sge") / "intents.jsonl"


def author() -> str:
    """Who is writing intents in this process: the agent role, else H."""
    return os.environ.get("SGE_ACTOR") or "H"


def record(root: str | Path, node: str, action: str, text: str, *,
           by: str, gate: str | None) -> None:
    path = Path(root) / _FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "node": node, "action": action,
             "author": author(), "by": by, "intent": text, "gate": gate}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def history(root: str | Path, node: str | None = None) -> list[dict]:
    """Every recorded step, oldest first; one node's, or all."""
    path = Path(root) / _FILE
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if node is None or entry.get("node") == node:
            out.append(entry)
    return out


def format_history(entries: list[dict]) -> str:
    if not entries:
        return "(no recorded intent)"
    return "\n".join(f"{e.get('at', '')[:16]}  {e.get('action', ''):7} by {e.get('author', '?')}"
                     f"  [{e.get('gate') or '-'}]  {e.get('intent', '')}" for e in entries)
