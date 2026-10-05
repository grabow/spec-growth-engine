"""The accepted state: what a change set is measured against when nobody clicks Save.

A change set (changeset.py) needs a BEFORE. In the cockpit that is the file on
disk at the moment of Save. Headless there is no such moment: an agent writes
SPEC.md files and runs the gate, and "the file before this edit" is gone. So the
engine keeps one: <root>/.sge/accepted.json holds every node's spec as it was
last ACCEPTED, and ARCHITECTURE.md.

Who accepts what:

  E    on a passing gate, every change at SOFT or below -- GOVERNANCE §3: SOFT is
       "auto-approved if all policy checks pass" (cli.py gate)
  H'   at D2 in the cockpit, the SOFT drafts it cleared; under the delegation
       (`cli.py decide`), a pending HARD change inside the scope H delegated -- recorded with the
       spec it replaced, so H can confirm it (accept) or OVERRULE it afterwards
  H    anything, HARD included (cli.py accept, or Save in the cockpit)

A HARD change nobody has accepted is PENDING. It blocks nothing -- an agent keeps
working, which is the point of running one -- but the changed node is not done,
and for a breaking change neither are its consumers: `verified` on any of them is
a HARD error, and progress does not count them. The same shape as a decision
request, for the same reason: unattended, "stop and wait" produces silence.

Consumers are the ACCEPTED ones: nodes whose accepted spec depends on the changed
node. A consumer written since was written against the current contract.

H may also REJECT a pending HARD change, with a reason. The rejection is bound to
the change's fingerprint (accepted spec + current spec) and turns it into a HARD
error: the gate BLOCKS until the node is restored or changed differently. That is
the only way H's "no" reaches an unattended agent -- the gate is what it reads.
A different change has a different fingerprint and is simply pending again.

No file = nothing tracked, and validate and the gate behave exactly as before;
`cli.py accept ROOT --all` is how a project opts in. Like evidence.json this is a
local record, not a signature: an agent CAN run `accept`. The manual forbids it,
and the audit log names who did.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import changeset, lifecycle

# The rule an acceptance by H' under the delegation is recorded with
DELEGATED = "delegated"

ARCHITECTURE = "ARCHITECTURE.md"
E_CLEARS = ("NONE", "AUTO", "SOFT")
_DIR, _FILE = ".sge", "accepted.json"


class Unreadable(ValueError):
    """accepted.json exists but cannot be read. Never treated as 'not tracked':
    that would turn a corrupt file into a silent pass for every HARD change."""


def _path(root: str | Path) -> Path:
    return Path(root) / _DIR / _FILE


def tracked(root: str | Path) -> bool:
    return _path(root).is_file()


def load(root: str | Path) -> dict | None:
    """{"architecture": text, "nodes": {id: {spec, at, by, actor, gate}}}, or None
    when the project does not track an accepted state. Raises Unreadable."""
    path = _path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Unreadable(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        raise Unreadable(f"{path}: no `nodes` mapping")
    return data


def before(root: str | Path) -> dict[str, dict] | None:
    """The accepted graph {id: spec}, for changeset.classify; None if untracked."""
    state = load(root)
    return None if state is None else {nid: rec["spec"] for nid, rec in state["nodes"].items()}


def architecture_text(root: str | Path) -> str:
    """ARCHITECTURE.md as compared and stored (trailing whitespace ignored)."""
    path = Path(root) / ARCHITECTURE
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _fingerprint(before, after) -> str:
    """Identifies ONE change: what was accepted, and what it became. A brief or a
    rejection bound to it stops applying the moment the node changes again."""
    if isinstance(after, dict):
        after = changeset.normalize(after)
    blob = json.dumps({"before": before, "after": after}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _architecture_change() -> dict:
    return {
        "node": ARCHITECTURE, "new_node": False, "deleted": False, "breaking": True,
        "gate": "HARD", "consumers": [],
        "reasons": [("HARD", "ARCHITECTURE.md changed (root invariants reach every node)")],
        "provides": {"added": [], "removed": []}, "criteria": {"added": [], "removed": []},
    }


def changes(nodes: dict[str, dict], root: str | Path) -> list[dict]:
    """Every non-empty change set of the current graph against the accepted state,
    ARCHITECTURE.md included as a pseudo-node. [] when untracked."""
    state = load(root)
    if state is None:
        return []
    old = {nid: rec["spec"] for nid, rec in state["nodes"].items()}
    rejected = state.get("rejected") or {}
    out = []
    users = changeset.ancestor_users(nodes, root)    # a parent using its sub-component
    for nid in sorted(set(nodes) | set(old)):
        change = changeset.classify(old, nid, nodes.get(nid), users=users)
        if change["reasons"]:
            change["fingerprint"] = _fingerprint(old.get(nid), nodes.get(nid))
            out.append(change)
    arch = architecture_text(root)
    if arch != state.get("architecture", ""):
        change = _architecture_change()
        change["fingerprint"] = _fingerprint(state.get("architecture", ""), arch)
        out.append(change)
    for change in out:
        rej = rejected.get(change["node"])
        change["rejected"] = rej if rej and rej.get("fingerprint") == change["fingerprint"] \
            else None
    return out


def pending(nodes: dict[str, dict], root: str | Path) -> list[dict]:
    """The HARD change sets nobody has accepted yet."""
    return [c for c in changes(nodes, root) if c["gate"] == "HARD"]


def not_done(nodes: dict[str, dict], root: str | Path) -> set[str]:
    """Nodes a pending HARD change keeps from counting as done: the changed node,
    the consumers of a breaking change, and for ARCHITECTURE.md the root."""
    try:
        return _held(nodes, pending(nodes, root))
    except Unreadable:
        return set()   # issues() reports it as HARD; nothing here can be trusted


def _held(nodes: dict[str, dict], waiting: list[dict]) -> set[str]:
    out: set[str] = set()
    for c in waiting:
        if c["node"] == ARCHITECTURE:
            out |= {nid for nid, n in nodes.items()
                    if n.get("kind") == "system" or not n.get("parent")}
            continue
        out.add(c["node"])
        if c["breaking"]:
            out |= set(c["consumers"])
    return out & set(nodes)


def issues(nodes: dict[str, dict], root: str | Path) -> list[tuple[str, str]]:
    """[(severity, message)] for validate: every pending HARD change (WARN), and
    `verified` on a node one of them keeps from being done (HARD)."""
    try:
        waiting = pending(nodes, root)
    except Unreadable as exc:
        return [("HARD", f"accepted state unreadable: {exc} -- repair it, or delete it "
                         "to stop tracking HARD changes")]
    out: list[tuple[str, str]] = []
    for c in waiting:
        why = "; ".join(r for g, r in c["reasons"] if g == "HARD")
        rej = c["rejected"]
        if rej:
            out.append(("HARD", f"HARD CHANGE REJECTED on {c['node']} by {rej['by']} "
                                f"({rej['at'][:10]}): {rej['reason']} -- restore the "
                                "accepted spec (`pending` shows it), or change it "
                                f"differently. The change: {why}"))
        else:
            out.append(("WARN", f"HARD CHANGE PENDING on {c['node']}, awaiting H: {why}"))
    for nid in sorted(_held(nodes, waiting)):
        if nodes[nid].get("status") == "verified":
            out.append(("HARD", f"status 'verified' but a HARD change on or affecting {nid} "
                                "is not accepted (at most 'implemented' until it is)"))
    return out


def summary(nodes: dict[str, dict], root: str | Path) -> str:
    """One line for the validate header."""
    try:
        state = load(root)
    except Unreadable:
        return "UNREADABLE (see HARD errors)"
    if state is None:
        return "not tracked (HARD changes are not recorded; `cli.py accept ROOT --all` starts)"
    hard = pending(nodes, root)
    waiting = [c["node"] for c in hard]
    rejected = [c["node"] for c in hard if c["rejected"]]
    return (f"{len(state['nodes'])} node(s); HARD pending: "
            + (f"{len(waiting)} ({', '.join(waiting)})" if waiting else "none")
            + (f"; REJECTED: {', '.join(rejected)}" if rejected else ""))


# ---- writing -----------------------------------------------------------------

def rename(root: str | Path, ids: dict[str, str]) -> None:
    """A rename moves no promise (nodes.rename_node): each renamed node's accepted
    record moves to its new id, and every accepted spec that names a renamed id
    names the new one. So the rename is no change set of its own, and whatever was
    pending before it stays pending -- under the new name."""
    state = load(root)
    if state is None:
        return
    from . import nodes as nodeops   # nodes -> accepted at call time: no import cycle
    moved = {}
    for nid, rec in state["nodes"].items():
        spec = dict(rec.get("spec") or {})
        spec.update(nodeops._renamed(spec, ids))
        moved[ids.get(nid, nid)] = {**rec, "spec": spec}
    state["nodes"] = moved
    if state.get("rejected"):
        state["rejected"] = {ids.get(k, k): v for k, v in state["rejected"].items()}
    _write(root, state)


def _write(root: str | Path, state: dict) -> None:
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record(nodes: dict[str, dict], root: str | Path, ids: list[str], *,
            actor: str, by: str, action: str, gates: dict[str, str],
            log: bool = True, notes: dict[str, dict] | None = None,
            rule: str | None = None) -> None:
    state = load(root) or {"version": 1, "architecture": "", "nodes": {}}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    for nid in ids:
        (state.get("rejected") or {}).pop(nid, None)   # decided anew

        if nid == ARCHITECTURE:
            state["architecture"] = architecture_text(root)
        elif nid in nodes:
            record = {"spec": changeset.normalize(nodes[nid]), "at": stamp,
                      "actor": actor, "by": by, "gate": gates.get(nid)}
            if rule:   # a delegated acceptance keeps what it replaced, for H's review
                record["rule"] = rule
                old = state["nodes"].get(nid)
                if old:
                    record["previous"] = {k: v for k, v in old.items() if k != "previous"}
            state["nodes"][nid] = record
        else:
            state["nodes"].pop(nid, None)   # accepting a deletion
    _write(root, state)
    if not log:
        return
    for nid in ids:
        lifecycle.log_autonomy(root, {"actor": actor, "by": by, "action": action,
                                      "node": nid, "gate": gates.get(nid),
                                      **((notes or {}).get(nid) or {})})


def accept(nodes: dict[str, dict], root: str | Path, ids: list[str], *,
           by: str, actor: str = "H", notes: dict[str, dict] | None = None,
           rule: str | None = None) -> list[tuple[str, str]]:
    """Accept the CURRENT state of `ids` (node ids, or ARCHITECTURE.md), whatever
    its gate. HARD is H's to accept; H' passes actor="H'" for what it cleared at
    D2. `notes` add fields to each id's log entry (engine.assist records H's
    agreement with a brief there). Returns [(id, gate)] -- the gate each change
    had when it was accepted."""
    if not tracked(root):
        raise ValueError("no accepted state yet: `accept --all` starts one (accepting "
                         "single nodes would make every other node look new)")
    known = {c["node"]: c["gate"] for c in changes(nodes, root)}
    old = before(root) or {}
    unknown = [i for i in ids if i != ARCHITECTURE and i not in nodes and i not in old]
    if unknown:
        raise ValueError(f"not a node, and not in the accepted state: {', '.join(unknown)}")
    gates = {i: known.get(i, "NONE") for i in ids}
    _record(nodes, root, ids, actor=actor, by=by, action="accepted", gates=gates,
            notes=notes, rule=rule)
    return [(i, gates[i]) for i in ids]


def awaiting_review(root: str | Path) -> list[str]:
    """Nodes whose current acceptance H' made under the delegation and H has not
    yet confirmed or overruled. H accepting the node again confirms it (the record
    becomes H's)."""
    state = load(root) or {}
    return sorted(nid for nid, rec in state.get("nodes", {}).items()
                  if rec.get("rule") == DELEGATED)


def overrule(nodes: dict[str, dict], root: str | Path, nid: str, *,
             by: str, reason: str) -> None:
    """H takes back an acceptance H' made under the delegation: the node's accepted spec returns
    to what it was before, and the change H' accepted -- pending again -- is
    REJECTED with H's reason, so the gate blocks until the node is restored or
    changed differently. Nothing is lost: the delegation was always revocable."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("an overrule needs a reason -- it is what the agent reads")
    state = load(root)
    record = (state or {}).get("nodes", {}).get(nid)
    if not record or record.get("rule") != DELEGATED or "previous" not in record:
        raise ValueError(f"{nid} was not accepted by H' under the delegation; "
                         "nothing to overrule")
    state["nodes"][nid] = record["previous"]
    _write(root, state)
    change = next((c for c in pending(nodes, root) if c["node"] == nid), None)
    if change is not None:   # else the node is already back at the restored spec
        state = load(root)
        state.setdefault("rejected", {})[nid] = {
            "fingerprint": change["fingerprint"], "by": by, "reason": reason,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _write(root, state)
    lifecycle.log_autonomy(root, {"actor": "H", "by": by, "action": "overruled",
                                  "node": nid, "gate": "HARD", "reason": reason})


def reject(nodes: dict[str, dict], root: str | Path, ids: list[str], *,
           by: str, reason: str, notes: dict[str, dict] | None = None) -> None:
    """H rejects pending HARD changes. Each becomes a HARD error, bound to its
    fingerprint: the gate blocks until the node is restored or changed otherwise."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a rejection needs a reason -- it is what the agent reads")
    by_node = {c["node"]: c for c in pending(nodes, root)}
    missing = [i for i in ids if i not in by_node]
    if missing:
        raise ValueError(f"no pending HARD change on: {', '.join(missing)}")
    state = load(root)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    rejected = state.setdefault("rejected", {})
    for nid in ids:
        rejected[nid] = {"fingerprint": by_node[nid]["fingerprint"], "at": stamp,
                         "by": by, "reason": reason}
    _write(root, state)
    for nid in ids:
        lifecycle.log_autonomy(root, {"actor": "H", "by": by, "action": "rejected",
                                      "node": nid, "gate": "HARD", "reason": reason,
                                      **((notes or {}).get(nid) or {})})


def accept_all(nodes: dict[str, dict], root: str | Path, *, by: str) -> int:
    """H accepts the whole current graph: how a project starts tracking, and how
    a pending backlog is accepted wholesale. Logged as ONE entry."""
    _path(root).unlink(missing_ok=True)
    ids = sorted(nodes)
    _record(nodes, root, [*ids, ARCHITECTURE], actor="H", by=by, action="accepted",
            gates={}, log=False)
    lifecycle.log_autonomy(root, {"actor": "H", "by": by, "action": "accepted-all",
                                  "nodes": len(ids)})
    return len(ids)


def clear(nodes: dict[str, dict], root: str | Path) -> list[tuple[str, str]]:
    """E accepts every change at SOFT or below -- call on a PASSING gate only.

    Repeated to a fixed point: clearing a consumer's own change (it stopped
    depending on the node) can turn that node's breaking change from HARD to SOFT.
    A new node under a parent that is not accepted yet waits for its parent: a
    component inside a container nobody accepted is not a SOFT boundary.
    Returns [(id, gate)] in the order cleared; [] when untracked."""
    if not tracked(root):
        return []
    cleared: list[tuple[str, str]] = []
    for _ in range(len(nodes) + len(before(root) or {}) + 1):  # each round clears >= 1
        old = before(root) or {}
        batch = [c for c in changes(nodes, root)
                 if c["gate"] in E_CLEARS and c["node"] != ARCHITECTURE
                 and not (c["new_node"] and nodes[c["node"]].get("parent")
                          and nodes[c["node"]]["parent"] not in old)]
        if not batch:
            return cleared
        gates = {c["node"]: c["gate"] for c in batch}
        _record(nodes, root, list(gates), actor="E", by="gate", action="cleared",
                gates=gates)
        cleared += gates.items()
    raise RuntimeError("accepted.clear did not converge")  # pragma: no cover
