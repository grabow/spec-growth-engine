"""Is a breaking change migrated? E's precondition for letting H' accept it (the delegation).

GOVERNANCE §7 does not let the engine APPROVE a breaking contract change: it
makes the change one transaction over the node and its consumers, and blocks
while any consumer is red. So this is not an approval. It is the checkable
half of the question -- have the consumers followed? -- and it leaves the other
half, whether the change should happen at all, to judgement (H, or H' under the delegation).

A change is migrated when, for the changed node AND every accepted consumer:

  green      the last recorded test evidence passed
  after      that run STARTED after the last modification of every file that
             matters: the node's SPEC.md and owned code, and for a consumer its
             own SPEC.md, owned code and attributed test files
  attributed at least one test file is attributed to it (engine.attribution);
             a run that covers the build root but exercises nothing of the node
             proves nothing about it
  let go     a consumer no longer mentions an operation the node no longer
             provides at all (the name search of changeset.impact). A reworded
             entry that KEEPS its name -- a new signature, an added parameter --
             is not removed: a consumer has to keep calling it, and whether it
             calls it right is what its tests after the change prove. (Run 04:
             read_text and render kept their names, and the first version of
             this rule held both changes back because svc.session still called
             them.)

Fails safe everywhere: no evidence, evidence without attribution, a timestamp
that cannot be compared -- all read as NOT migrated. What it cannot see: a
consumer's tests passing without exercising the changed promise (an invariant
tightened where no consumer test looks). That is why this is a precondition for
judgement, never a substitute for it.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from . import changeset, lifecycle
from . import evidence as code_evidence

_STAMP = "%Y-%m-%dT%H:%M:%S"


def _latest(paths: list[str]) -> str | None:
    """The newest modification time among `paths`, in the evidence format."""
    times = []
    for p in paths:
        try:
            times.append(Path(p).stat().st_mtime)
        except OSError:
            continue
    if not times:
        return None
    return _dt.datetime.fromtimestamp(max(times)).strftime(_STAMP)


def _files(node: dict | None, project_root: str | Path) -> list[str]:
    if not node:
        return []
    return [p for p in (node.get("_path"),) if p] + \
        code_evidence.resolve_node_files(node, project_root)


def check(nodes: dict[str, dict], project_root: str | Path, change: dict) -> dict:
    """{migrated: bool, missing: [why not, per node]} for a pending change.

    Only a breaking change with consumers has anything to migrate; anything else
    returns migrated=False with the reason, so a caller can never read "nothing
    to check" as "checked"."""
    nid = change["node"]
    if not change.get("breaking") or not change.get("consumers"):
        return {"migrated": False,
                "missing": ["not a breaking change to a consumed contract -- nothing that "
                            "migration could settle"]}
    ev = lifecycle.load_evidence(project_root)
    changed = nodes.get(nid)
    missing: list[str] = []
    reach = changeset.impact(nodes, project_root, change)
    mentions = {c["node"]: c["mentions"] for c in reach["consumers"]}
    still_provided = changeset.provided_names(changed)

    for who in [nid, *change["consumers"]]:
        node = nodes.get(who)
        if node is None:
            missing.append(f"{who}: no longer in the graph")
            continue
        rec = ev.get(who)
        if not rec:
            missing.append(f"{who}: no test evidence recorded")
            continue
        if rec.get("status") != "pass":
            missing.append(f"{who}: last test run {rec.get('status')!r}")
            continue
        tests = rec.get("tests") or []
        if not tests:
            missing.append(f"{who}: its evidence exercises nothing of it (no attributed "
                           "test file)")
            continue
        relevant = _files(changed, project_root) + (
            [] if who == nid else _files(node, project_root) + list(tests))
        latest = _latest(relevant)
        if latest is None or not rec.get("at") or rec["at"] <= latest:
            missing.append(f"{who}: tests ran {rec.get('at') or '(no time)'}, before the last "
                           f"change ({latest or 'unknown'})")
            continue
        gone = sorted({h for h, _ in mentions.get(who, [])} - still_provided)
        if who != nid and gone:
            missing.append(f"{who}: still mentions what was removed ({', '.join(gone)})")
    return {"migrated": not missing, "missing": missing}
