"""The commit gate: the graph (validate) and the code (drift) must both pass --
and on a pass, E clears every change at SOFT or below against the accepted state.

  run(nodes, root)        {validate, drift, blocked, pending, cleared, waiting, tracked}
  text(result, details)   the report; `details` adds each pending SOFT change with
                          its diff, for a person -- `cli.py gate`, which agents
                          read, stays as short as it was

One place for what `cli.py gate`, the git hook and the cockpit's Validate > Gate
all mean by "the gate".
"""
from __future__ import annotations

from pathlib import Path

from . import accepted, changeset, drift, validate


def blocked(report: str) -> bool:
    """A report blocks iff its trailing gate line is BLOCK (stable convention)."""
    return "gate: BLOCK" in report


def run(nodes: dict[str, dict], root: str | Path, *, clear: bool = True) -> dict:
    """Validate and drift; on a pass (and `clear`), E clears what it may.
    `pending` is what was waiting at or below SOFT BEFORE the clearing -- what a
    person is shown being cleared, or, on a block, what waits for a pass."""
    v, d = validate.run(nodes, str(root)), drift.run(nodes, str(root))
    out = {"validate": v, "drift": d, "blocked": blocked(v) or blocked(d),
           "tracked": accepted.tracked(root), "pending": [], "cleared": [], "waiting": []}
    if not out["tracked"]:
        return out
    try:
        out["pending"] = [c for c in accepted.changes(nodes, root)
                          if c["gate"] in accepted.E_CLEARS
                          and c["node"] != accepted.ARCHITECTURE]
        if clear and not out["blocked"]:
            out["cleared"] = accepted.clear(nodes, root)
        out["waiting"] = [c["node"] for c in accepted.pending(nodes, root)]
    except accepted.Unreadable:
        pass    # validate reported it as a HARD error, which blocked the gate
    return out


def hard_errors(result: dict) -> int:
    """How many HARD errors the two reports name together."""
    total = 0
    for report in (result["validate"], result["drift"]):
        for line in report.splitlines():
            if line.startswith("HARD errors:"):
                total += int(line.split(":", 1)[1].strip() or 0)
    return total


def text(result: dict, *, details: bool = False) -> str:
    """The report: both checks, the verdict, what E cleared and what waits for H."""
    lines = [result["validate"], "", result["drift"], "",
             f"==> spec-growth-engine gate: {'BLOCK' if result['blocked'] else 'PASS'}"]
    if not result["tracked"]:
        lines.append("accepted: not tracked -- `accept ROOT --all` records HARD changes "
                     "from now on")
        return "\n".join(lines)
    if details and result["pending"]:
        lines += ["", ("cleared by E on this PASS:" if result["cleared"] else
                       "waiting for a passing gate, then cleared by E:")]
        for change in result["pending"]:
            lines += ["", changeset.report(change)]
        lines.append("")
    if result["cleared"]:
        lines.append(f"accepted: E cleared {len(result['cleared'])} change(s) at SOFT or "
                     "below: " + ", ".join(f"{n} ({g})" for n, g in result["cleared"]))
    if result["waiting"]:
        lines.append(f"accepted: HARD pending, awaiting H: {', '.join(result['waiting'])} "
                     "(`pending ROOT` shows the impact)")
    return "\n".join(lines)
