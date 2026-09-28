"""Assisted HARD (AUTONOMY.md 5c) and the delegation: H' prepares a pending HARD
change; H decides it -- or, where H delegated it (`cli.py delegate ROOT on`), H'
does.

A pending HARD change (engine/accepted.py) waits for a decision, and deciding
it is homework: who breaks, what must be migrated, whether a non-breaking way
existed. H' does the homework.

  prepare     H' writes a brief for each pending HARD change without a fresh one
              (5c: it RECOMMENDS, and decides nothing)
  brief_for   the brief for a change -- only while it still describes that change
  decide      H accepts or rejects a pending change; H confirms or overrules an
              acceptance H' made under the delegation. The log records the brief
              H had.
  delegated   `cli.py decide`: under the delegation, H' decides the pending
              changes in its scope (engine.autonomy.delegable_scope) that E found migrated
              (engine.migration); everything else stays pending for H

A brief is bound to the change's FINGERPRINT (accepted spec + current spec). When
the node changes again the brief describes something nobody is deciding any
more: it is STALE, and shown as stale, never as current. Its successor is
prepared WITH it -- H' sees what it said about the earlier version, so a
cosmetic edit does not buy a fresh opinion.

Nothing here counts how often H' was right. The delegation is H's act, bounded by
structure (zones, migration, revocability), not a measured grant.

H' is INJECTED (brief_fn), as in engine.autonomy: the engine calls no model.
Store: <root>/.sge/briefs.json -- advisory, so an unreadable file is treated as
empty (the cost is preparing again), unlike accepted.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import yaml

from . import accepted, autonomy, changeset, intents, lifecycle, migration

RECOMMENDATIONS = ("accept", "reject")
_STORE = Path(".sge") / "briefs.json"

# (report, accepted spec, current spec) -> {recommendation, confidence, summary,
#  risks, alternatives, model}, or None for an answer with no usable brief.
# Raises RuntimeError when H' is unavailable (no key, the provider refuses, the
# answer is cut off).
BriefFn = Callable[[str, str, str], "dict | None"]


def load(root: str | Path) -> dict[str, dict]:
    path = Path(root) / _STORE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(root: str | Path, briefs: dict) -> None:
    path = Path(root) / _STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(briefs, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def brief_for(root: str | Path, change: dict, briefs: dict | None = None) -> dict | None:
    """The brief for this exact change, or None (none prepared, or stale)."""
    rec = (load(root) if briefs is None else briefs).get(change["node"])
    return rec if rec and rec.get("fingerprint") == change.get("fingerprint") else None


def is_stale(root: str | Path, change: dict, briefs: dict | None = None) -> bool:
    """A brief exists for the node, but for an earlier version of the change."""
    rec = (load(root) if briefs is None else briefs).get(change["node"])
    return bool(rec) and rec.get("fingerprint") != change.get("fingerprint")


def sides(nodes: dict[str, dict], root: str | Path, change: dict) -> tuple[str, str]:
    """(accepted, current) as text -- what H' compares, and what `pending` shows
    an agent that has to restore a rejected change."""
    nid = change["node"]
    if nid == accepted.ARCHITECTURE:
        state = accepted.load(root) or {}
        return (state.get("architecture") or "(empty)",
                accepted.architecture_text(root) or "(empty)")
    old = (accepted.before(root) or {}).get(nid)
    old_text = (yaml.safe_dump(old, sort_keys=False, allow_unicode=True) if old
                else "(not accepted before: a new node)")
    node = nodes.get(nid)
    cur_text = Path(node["_path"]).read_text(encoding="utf-8") if node else "(deleted)"
    return old_text, cur_text


def _items(value) -> list[str]:
    """A list field as the model actually sends it. Seen from GLM-5.2: an array
    JSON-encoded INTO a string ('["a", "b"]'), which iterated as a list printed one
    character per line. Also accepted: a plain string, one item per line."""
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = json.loads(text) if text.startswith("[") else None
        except json.JSONDecodeError:
            parsed = None
        value = parsed if isinstance(parsed, list) else \
            [line.strip().lstrip("-*").strip() for line in text.splitlines()]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _clean(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("recommendation") not in RECOMMENDATIONS:
        return None
    try:
        conf = min(max(float(raw.get("confidence")), 0.0), 1.0)
    except (TypeError, ValueError):
        conf = None
    return {
        "recommendation": raw["recommendation"], "confidence": conf,
        "summary": str(raw.get("summary") or "").strip(),
        "risks": _items(raw.get("risks")),
        "alternatives": _items(raw.get("alternatives")),
        "model": raw.get("model"),
    }


def prepare(nodes: dict[str, dict], root: str | Path, brief_fn: BriefFn,
            only: set[str] | None = None) -> list[tuple[str, dict | None]]:
    """Have H' brief every pending HARD change (or those in `only`) that has no
    fresh brief. A rejected change is decided and needs none. Returns
    [(node, brief)] -- brief None where H' answered nothing usable. When H' is
    unavailable the RuntimeError propagates, after the briefs written so far are
    saved: a dead key fails the same way for every change, so it stops at one."""
    briefs = load(root)
    out: list[tuple[str, dict | None]] = []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        for change in accepted.pending(nodes, root):
            nid = change["node"]
            if (only is not None and nid not in only) or change["rejected"] \
                    or brief_for(root, change, briefs):
                continue
            report = changeset.report(change, changeset.impact(nodes, root, change))
            grown = intents.history(root, nid)
            if grown:
                # intent fidelity is judged against how the node was grown, not
                # only against the last request
                report += ("\n\nINTENT HISTORY of this node -- the growth steps it was "
                           "built from, oldest first:\n" + intents.format_history(grown))
            earlier = briefs.get(nid)   # stale by now, or it would have been skipped
            if earlier:
                report += ("\n\nEARLIER BRIEF on this node, for a previous version of the "
                           f"change: recommended {earlier.get('recommendation')} "
                           f"(confidence {earlier.get('confidence')}): "
                           f"{earlier.get('summary') or ''}\nJudge the change as it is "
                           "NOW; say so if it merely re-words what was advised against.")
            brief = _clean(brief_fn(report, *sides(nodes, root, change)))
            if brief:
                briefs[nid] = {**brief, "fingerprint": change["fingerprint"], "at": stamp}
                lifecycle.log_autonomy(root, {
                    "actor": "H'", "by": brief.get("model"), "action": "briefed", "node": nid,
                    "fingerprint": change["fingerprint"],
                    "recommendation": brief["recommendation"],
                    "confidence": brief["confidence"]})
            out.append((nid, brief))
    finally:
        _save(root, briefs)
    return out


def decide(nodes: dict[str, dict], root: str | Path, ids: list[str], *, decision: str,
           by: str, reason: str = "", expected: dict[str, str] | None = None) -> list[dict]:
    """H decides. For a PENDING change: accept, or reject with a reason. For an
    acceptance H' made under the delegation: accept CONFIRMS it (the record becomes H's), reject
    OVERRULES it (engine.accepted.overrule). Each log entry records the brief H
    had in front of it -- what H' had said, as a fact, not a score.

    `expected` maps id -> the fingerprint H looked at, for pending changes. A
    change that moved since is refused: a list gone stale must not decide a
    change H never saw."""
    if decision not in RECOMMENDATIONS:
        raise ValueError(f"decision must be one of {RECOMMENDATIONS}")
    by_node = {c["node"]: c for c in accepted.pending(nodes, root)}
    for nid, fingerprint in (expected or {}).items():
        now = by_node.get(nid)
        if now is None or now["fingerprint"] != fingerprint:
            raise ValueError(f"{nid} changed on disk since you looked at it -- "
                             "refresh and decide again")
    reviewing = set(accepted.awaiting_review(root)) - set(by_node)
    briefs = load(root)
    notes: dict[str, dict] = {}
    for nid in ids:
        brief = brief_for(root, by_node[nid], briefs) if nid in by_node else None
        notes[nid] = {"brief": {"recommendation": brief["recommendation"],
                                "confidence": brief["confidence"]} if brief else None}
    overruled = [nid for nid in ids if nid in reviewing and decision == "reject"]
    for nid in overruled:
        accepted.overrule(nodes, root, nid, by=by, reason=reason)
    rest = [nid for nid in ids if nid not in overruled]
    if rest and decision == "accept":
        accepted.accept(nodes, root, rest, by=by, notes=notes)
    elif rest:
        accepted.reject(nodes, root, rest, by=by, reason=reason, notes=notes)
    return [{"node": nid, **notes[nid],
             "action": ("overruled" if nid in overruled
                        else "confirmed" if nid in reviewing
                        else "accepted" if decision == "accept" else "rejected")}
            for nid in ids]


def delegated(nodes: dict[str, dict], root: str | Path, brief_fn: BriefFn) -> list[dict]:
    """`cli.py decide`: under the delegation, H' decides each pending HARD change
    it may.

    Scope and migration are checked FIRST, deterministically -- H' is asked only
    about changes it could accept, and never spends a call on a zone. Returns
    [{node, action: 'accepted' | 'left for H', reason}]. Raises ValueError when
    H has not delegated, and RuntimeError when H' is unavailable (as `prepare`
    does)."""
    if not autonomy.delegated(root):
        raise ValueError("delegation is off: pending HARD changes are H's "
                         "(H turns it on with `cli.py delegate ROOT on`)")
    out: list[dict] = []
    for change in accepted.pending(nodes, root):
        nid = change["node"]
        if change["rejected"]:
            continue   # H decided it; it waits on the agent
        in_scope, why = autonomy.delegable_scope(change)
        if not in_scope:
            out.append({"node": nid, "action": "left for H", "reason": why})
            continue
        migrated = migration.check(nodes, root, change)
        if not migrated["migrated"]:
            out.append({"node": nid, "action": "left for H",
                        "reason": "not migrated: " + "; ".join(migrated["missing"])})
            continue
        brief = brief_for(root, change)
        if brief is None:
            prepare(nodes, root, brief_fn, only={nid})
            brief = brief_for(root, change)
        ok, why = autonomy.delegated_decide(change, brief, migrated)
        if not ok:
            out.append({"node": nid, "action": "left for H", "reason": why})
            continue
        accepted.accept(nodes, root, [nid], by=brief.get("model") or "H'", actor="H'",
                        rule=accepted.DELEGATED, notes={nid: {
                            "brief": {"recommendation": brief["recommendation"],
                                      "confidence": brief["confidence"]},
                            "reason": why}})
        out.append({"node": nid, "action": "accepted", "reason": why})
    return out


def format_brief(brief: dict | None, stale: bool = False) -> str:
    if brief is None:
        return ("H' brief: STALE -- the node changed after it was prepared; prepare again."
                if stale else "H' brief: none yet (Prepare, or `cli.py prepare ROOT`).")
    conf = brief.get("confidence")
    lines = [f"H' recommends: {brief['recommendation'].upper()}"
             + (f" (confidence {conf:.2f})" if isinstance(conf, (int, float)) else "")]
    if brief.get("summary"):
        lines.append(f"  {brief['summary']}")
    if brief.get("risks"):
        lines.append("  risks:")
        lines += [f"    - {r}" for r in brief["risks"]]
    if brief.get("alternatives"):
        lines.append("  alternatives:")
        lines += [f"    - {a}" for a in brief["alternatives"]]
    lines.append("  (a recommendation -- the decision is H's)")
    return "\n".join(lines)

