"""The three autonomy switches as code: the draft gate, the delegation, and the rule.

AUTONOMY.md defines them; this module is where they become a DECISION. That
decision used to live inside the Tk class (app.Cockpit._d2_draft), so nothing
headless could reach it: a change-set check wired there protected the cockpit
and nothing an agent does through the CLI.

The engine authors no intent and calls no model. The reviewer (H') and the
planner (P) are INJECTED as plain callables -- the pattern capability.find uses
for its reranker -- so given their answers the decision is deterministic, and
testable without an API key.

Three different things are delegated, and each has its own switch.

  the draft gate (D0..D2)       who reviews and clears a drafted SPEC.md before
                                it is saved -- the cockpit slider. It stops at
                                D2: a draft is not on disk, so it cannot be
                                migrated, so the delegation's precondition can
                                never hold for it.
  the delegation (on | off)     PENDING HARD changes: whether H' may accept the
                                ones in its scope (delegable_scope +
                                delegated_decide). Not a degree above D2 but a
                                yes/no, <root>/.sge/autonomy.json, set only by H
                                (`cli.py delegate`), default off.
  the run (off | on |           not here: the operating mode of an orchestrated
   unsupervised)                run (engine/iteration.py, engine/unsupervised.py).

The delegation is not a measured grant: nothing here counts how often H' was
right. Its safety is structural -- the zones stay H's, E must find the change
migrated, H' must recommend it, and H can overrule every acceptance afterwards
(engine.accepted.overrule).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from . import accepted, changeset, lifecycle

# The draft gate D0..D2, keyed by the slider's value (config: draft_gate).
NAMES = {0: "Assist (off)", 1: "LLM review", 2: "LLM auto-SOFT"}
DRAFT_MAX = 2        # the cockpit slider: a draft cannot be migrated, see above
_DELEGATION_FILE = Path(".sge") / "autonomy.json"

# D2 auto-accept tuning.
AUTO_ACCEPT_CONF = 0.6
AUTO_MAX_ROUNDS = 2


def decide(change: dict | None, review: dict, *, rounds: int) -> tuple[str, str]:
    """One D2 step: ('accept' | 'revise' | 'escalate', reason).

    `change` is the draft's change set (engine.changeset), None if the draft does
    not parse. The order is the order of authority: what E decides (the gate the
    change falls under) comes before H's declared protected zones, and both before
    H's deputy.

    The protected-zone check reads `change['protected']`, which engine.changeset
    derives from the spec's `protected: true` marking (AUTONOMY.md 5b) -- a
    DECLARED zone, not a keyword guess. The keyword scan this replaced lived
    here; it is gone, so an undeclared zone is no longer guessed: declaring it is
    H's act (engine/changeset.py surfaces the unmarked case).
    """
    if change is None:
        return "escalate", "the draft does not parse -> human review"
    if change["gate"] == "HARD":
        return "escalate", "HARD gate -> human decision (D2 clears SOFT only)"
    if change.get("protected"):
        return "escalate", "declared protected zone (AUTONOMY 5b) -> human review"
    verdict = review.get("verdict")
    conf = review.get("confidence") or 0.0
    blockers = [f for f in review.get("findings", []) if f.get("severity") == "blocker"]
    if verdict == "approve" and not blockers and conf >= AUTO_ACCEPT_CONF:
        return "accept", f"H' approved (confidence {conf:.2f})"
    if verdict == "revise" and rounds < AUTO_MAX_ROUNDS:
        return "revise", f"H' asks for a revision (round {rounds + 1} of {AUTO_MAX_ROUNDS})"
    return "escalate", f"verdict '{verdict}', confidence {conf:.2f} -> human review"


def clear_draft(
    spec: str,
    review: dict,
    *,
    assess: Callable[[str], tuple[dict, dict] | None],
    revise: Callable[[str, str], str],
    rereview: Callable[[str], dict | None],
    on_revision: Callable[[str], None] | None = None,
) -> dict:
    """D2: may H' clear this draft's gate? Runs the bounded revise loop.

    assess(spec)            -> (change, reach) | None     E: engine.changeset
    revise(spec, findings)  -> revised spec               P: raises RuntimeError
                                                             when unavailable
    rereview(spec)          -> review | None              H': raises RuntimeError
                                                             when unavailable

    Returns {action: 'accept' | 'escalate', reason, spec, review, rounds,
    change, reach}. The change set is recomputed every round: a revision can turn
    a SOFT draft into a HARD one. Nothing is written here -- the caller saves on
    'accept', and the deterministic gate still runs on what it saved.

    The declared protected zone is read off the change set, so it needs no intent
    text here: a node is protected by what its SPEC.md says, not by keywords.
    """
    rounds = 0
    while True:
        assessed = assess(spec)
        change, reach = assessed if assessed else (None, None)
        action, reason = decide(change, review, rounds=rounds)
        if action == "revise":
            instruction = ("Apply these review findings; change only what they require:\n"
                           + "\n".join("- " + f["message"] for f in review.get("findings", [])))
            try:
                spec = revise(spec, instruction)
            except RuntimeError as exc:
                action, reason = "escalate", f"revise unavailable: {exc}"
            else:
                if on_revision:
                    on_revision(spec)
                try:
                    nxt = rereview(spec)
                except RuntimeError as exc:
                    action, reason = "escalate", f"re-review unavailable: {exc}"
                else:
                    if nxt:
                        review, rounds = nxt, rounds + 1
                        continue
                    action, reason = ("escalate",
                                      "re-review unavailable: H' gave no usable answer")
        return {"action": action, "reason": reason, "spec": spec, "review": review,
                "rounds": rounds, "change": change, "reach": reach}


# ---- the delegation: H' accepts a pending HARD change, within its scope ------

def delegated(root: str | Path) -> bool:
    """Has H delegated pending HARD changes in this project? No, unless H said
    so. Anything unreadable reads as no -- a delegation must be stated, never
    inferred."""
    path = Path(root) / _DELEGATION_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("delegation") is True


def set_delegation(root: str | Path, on: bool, *, by: str) -> None:
    """H's act: delegate pending HARD changes to H', or take it back. Logged,
    like every decision about who decides."""
    if not isinstance(on, bool):
        raise ValueError("the delegation is on or off")
    path = Path(root) / _DELEGATION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"delegation": on, "by": by,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2) + "\n",
                    encoding="utf-8")
    lifecycle.log_autonomy(root, {"actor": "H", "by": by, "action": "delegation",
                                  "delegation": on})


def delegable_scope(change: dict) -> tuple[bool, str]:
    """May H' decide this pending HARD change at all? Everything H set as a zone,
    and every HARD reason other than "it breaks an accepted consumer", stays H's.
    What is left is exactly what migration can settle: a breaking change to a
    component's contract that nodes in the graph consume."""
    if change["node"] == accepted.ARCHITECTURE:
        return False, "ARCHITECTURE.md is H's"
    if change.get("protected"):
        return False, "declared protected (5b): H's"
    if change.get("new_node"):
        return False, "a new container or root is H's"
    if change.get("deleted"):
        return False, "a deletion is H's"
    if change.get("kind") != "component":
        return False, f"a {change.get('kind') or 'node of unknown kind'} is H's"
    other = [why for gate, why in change["reasons"]
             if gate == "HARD" and not why.startswith(changeset.BREAKING)]
    if other:
        return False, "HARD for a reason only H decides: " + "; ".join(other)
    if not (change.get("breaking") and change.get("consumers")):
        return False, "not a breaking change to a consumed contract"
    return True, "a breaking change to a consumed component contract"


def delegated_decide(change: dict, brief: dict | None, migrated: dict) -> tuple[bool, str]:
    """(accept?, why) for one pending HARD change under the delegation. `migrated` is
    engine.migration.check's answer, `brief` the fresh brief from H'."""
    ok, why = delegable_scope(change)
    if not ok:
        return False, why
    if change.get("rejected"):
        return False, "H rejected this change"
    if not migrated["migrated"]:
        return False, "not migrated: " + "; ".join(migrated["missing"])
    if not brief:
        return False, "no brief from H'"
    if brief.get("recommendation") != "accept":
        return False, f"H' recommends {brief.get('recommendation')}"
    conf = brief.get("confidence") or 0.0
    if conf < AUTO_ACCEPT_CONF:
        return False, f"H' is unsure (confidence {conf:.2f} < {AUTO_ACCEPT_CONF})"
    return True, f"H' accepts (confidence {conf:.2f}); E found the consumers migrated"
