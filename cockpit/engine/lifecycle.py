"""Status lifecycle enforcement: make `verified` EARNED, not just claimed.

GOVERNANCE.md names two failure modes the engine exists to prevent: drift (handled
by drift.py) and **fake completion** -- a node marked done while real gaps hide.
This module closes the second: a node's `status` must be backed by evidence.

  - `verified` REQUIRES a passing test-evidence record for that node.
  - `implemented`/`verified` components SHOULD own existing code.

Test evidence is recorded by the Run Tests action (or any caller) into a small
persistent store `<root>/.sge/evidence.json`, keyed by node id. It is a local
trust marker (the test command + verdict + timestamp), not cryptographic proof.
The engine writes/reads it deterministically; it authors no intent.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import attribution
from . import evidence as code_evidence

_STORE_DIR = ".sge"
_STORE_FILE = "evidence.json"
VALID_STATUS = {"specd", "in-slice", "implemented", "verified"}
# the lifecycle is ordered, which is what lets a parent be compared to its children
_RANK = {"specd": 0, "in-slice": 1, "implemented": 2, "verified": 3}


def _store_path(project_root: str | Path) -> Path:
    return Path(project_root) / _STORE_DIR / _STORE_FILE


def load_evidence(project_root: str | Path) -> dict[str, dict]:
    """Return {node_id: {status, command, at, build_root}} (empty if none/garbage)."""
    path = _store_path(project_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    nodes = data.get("nodes") if isinstance(data, dict) else None
    return nodes if isinstance(nodes, dict) else {}


def rename_evidence(project_root: str | Path, ids: dict[str, str]) -> None:
    """Test evidence follows a renamed node: the tests ran on the same code, and a
    rename changes none of it (nodes.rename_node)."""
    path = _store_path(project_root)
    if not path.is_file():
        return
    store = {"version": 1, "nodes": {ids.get(nid, nid): rec
                                      for nid, rec in load_evidence(project_root).items()}}
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def record_evidence(
    project_root: str | Path,
    node_ids: list[str],
    status: str,
    command: str,
    build_root: str | None = None,
    tests_by_node: dict[str, set[str]] | None = None,
    at: str | None = None,
) -> Path:
    """Record a test run as evidence for each covered node. `status` is 'pass'/'fail'.

    `node_ids` is everything under the tested BUILD ROOT -- that is what the run
    actually covers. `tests_by_node` (engine.attribution) additionally records
    which test files attribute to each node, which is the finer question.

    `at` is when the run STARTED, if the caller knows it: a file changed while
    the tests ran was not tested, and engine.migration compares file times
    against this stamp. Without it, the time of recording is used."""
    path = _store_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    store = {"version": 1, "nodes": load_evidence(project_root)}
    stamp = at or time.strftime("%Y-%m-%dT%H:%M:%S")
    for nid in node_ids:
        record = {
            "status": status, "command": command, "at": stamp, "build_root": build_root,
        }
        if tests_by_node is not None:
            # which test files actually attribute to this node (LIFECYCLE.md 5a).
            # An empty list is meaningful: covered by the run, exercised by nothing.
            record["tests"] = sorted(tests_by_node.get(nid, ()))
        store["nodes"][nid] = record
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return path


def log_autonomy(project_root: str | Path, entry: dict) -> None:
    """Append an autonomy decision to <root>/.sge/autonomy.jsonl for async audit.
    Every auto-cleared (or escalated) gate at D2 is recorded -- who decided what."""
    path = Path(project_root) / _STORE_DIR / "autonomy.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def status_issues(nodes: dict[str, dict], project_root: str | Path) -> list[tuple[str, str]]:
    """Return [(severity, message)] for status-lifecycle violations.

    severity is 'HARD' (blocks the gate) or 'WARN'. Drives the no-fake-completion
    rule: `verified` without passing test evidence is a HARD error."""
    ev = load_evidence(project_root)
    out: list[tuple[str, str]] = []
    for nid, n in nodes.items():
        st = n.get("status")
        kind = n.get("kind")
        if st and st not in VALID_STATUS:
            out.append(("WARN", f"unknown status '{st}': {nid}"))
        if st == "verified":
            rec = ev.get(nid)
            if not rec:
                out.append(("HARD", f"status 'verified' without test evidence: {nid} "
                                    "(run tests to record it, or lower the status)"))
            elif rec.get("status") != "pass":
                out.append(("HARD", f"status 'verified' but last test evidence is "
                                    f"'{rec.get('status')}': {nid}"))
        if st in ("implemented", "verified") and kind == "component":
            if not code_evidence.resolve_node_files(n, project_root):
                out.append(("WARN", f"status '{st}' but node owns no existing code: {nid}"))

    # A node is realized BY ITS CHILDREN as well as by its own code, so it cannot
    # be further along than they are. Without this a system node owning no code
    # reaches `verified` on evidence recorded for the build root while every
    # child is still `specd` -- fake completion one level up, which the evidence
    # rule alone does not see.
    children: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        if n.get("parent") in nodes:
            children.setdefault(n["parent"], []).append(nid)
    for nid, kids in sorted(children.items()):
        st = nodes[nid].get("status")
        if st not in _RANK:
            continue
        behind = sorted(k for k in kids if _RANK.get(nodes[k].get("status"), 0) < _RANK[st])
        if not behind:
            continue
        detail = ", ".join(f"{k} is '{nodes[k].get('status')}'" for k in behind[:3])
        if st == "verified":
            # `verified` means a slice exercised it end to end; with an unfinished
            # child that is simply false.
            out.append(("HARD", f"status 'verified' but a child is not: {nid} ({detail})"))
        else:
            # growing a graph means adding `specd` children all the time, so a
            # parent that is merely `implemented` gets a warning, not a block
            out.append(("WARN", f"status '{st}' is ahead of a child: {nid} ({detail})"))

    # The evidence above is per BUILD ROOT. This is the per-NODE question: did any
    # test actually exercise it? WARN, not HARD -- attribution is static, so a test
    # reaching the node by reflection or a subprocess is invisible (LIFECYCLE.md 5a).
    for nid in attribution.unattributed(nodes, project_root):
        out.append(("WARN", f"status 'verified' but no test attributes to {nid} "
                            "(its evidence covers the build root, not this node)"))
    return out
