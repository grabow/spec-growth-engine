"""The rounds of an orchestrated run (AUTONOMY.md: the run): when the intent author
stops, does the run go on?

One `codex exec` session ends when the model stops calling tools -- after a
slice, after a failure it gave up on, or because it believes it is done. Before
this, only the prompt said "work until the task is done": whether it was,
nobody checked, and a run that stopped after one slice looked like a finished
one.

A ROUND is one session of I. After it, E checks the FLOOR -- it records the
tests and runs the gate -- and, on a green floor, H' checks the GOAL: TASK.md
against what E computed (`facts`; agent/reviewer.check_goal). Then this rule,
E's and deterministic, decides: stop, or resume the SAME session
(`codex exec resume`) with what is missing.

  the session failed                 stop    error
  a resumed round did no work        stop    stalled    I only talked: H decides
  the floor is red                   resume             with E's failures; H' is not asked
  floor green, H' names gaps         resume             with the gaps
  floor green, no gap, something     stop    asking     H answers; then a new run
    waits for H
  floor green, H' names no gap       stop    done
  floor green, H' unavailable        stop    unchecked  if I said DONE; else resume
  a resume past the round limit      stop    limit      the open gaps are H's to read

  I ended with BLOCKED: <why>        the floor is measured and, on a green one,
                                     the goal checked all the same. If nothing is
                                     missing but what waits for H, the run ends
                                     `asking`: waiting for H is not being blocked
                                     (run 12 said BLOCKED over a green floor and
                                     six questions). Otherwise it ends `blocked`,
                                     and H reads why.

What "waits for H" is: an open decision request, and every statement of the task
that H' names as WAITING -- unmet only because it rests on something only H may
decide (a pending HARD change outside what H delegated, a node held back by
one). Those are not gaps: the intent author cannot close them, and sending it
back for them only burns rounds (run 11 was sent back for a root it could not
move). H' names them apart from the gaps, and the rule counts them apart.

I's DONE is a claim, never the verdict: a run is done when E's floor is green,
H' finds no gap and nothing waits for H. In the goal check H' can only keep a
run going, or let it end on a green floor; it accepts nothing there (what it
decides in H's place in an unsupervised run, it decides in engine/unsupervised.py,
for H to review), and every run ends with H's review anyway. A gap I thinks wrong is not argued round after round: I ends with
BLOCKED and says why, and H decides -- which is also why a resumed round
without a single command ends the run.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import accepted
from .evidence import EXCLUDED_DIRS

MAX_ROUNDS = 5

_CLAIM = re.compile(r"^(DONE|BLOCKED)\b[\s:.\-\u2013\u2014]*(.*)$")


def claim(message: str | None) -> tuple[str | None, str]:
    """I's claim, from the last non-empty line of its last message: `DONE`, or
    `BLOCKED: <why>` (markdown emphasis around it is ignored). (None, "") for a
    message without one. A BLOCKED without a reason takes the message's text."""
    lines = [ln.strip().lstrip("#> ").strip("*_`").strip()
             for ln in (message or "").splitlines()]
    lines = [ln for ln in lines if ln]
    match = _CLAIM.match(lines[-1]) if lines else None
    if not match:
        return None, ""
    kind, why = match.group(1), match.group(2).strip()
    if kind == "BLOCKED" and not why:
        why = " ".join(lines[:-1])[:500]
    return kind, why


def open_requests(nodes: dict) -> list[str]:
    """The decision requests waiting for H, one line each.

    A decision request is a question the WORK RESTS ON: the node needed a
    decision above it -- an ARCHITECTURE.md invariant, another node's contract --
    recorded it instead of making it, and carried on assuming an answer. A run
    whose graph carries one is not done, however green it is, so the rule stops
    it as `asking` rather than `done`.

    Not counted here: a pending HARD change, which is a decision about work
    already done and visible in its own diff, and a requested waiver, which is a
    bounded deviation that already holds its node back from `verified`. Those
    wait for H too; they do not make the rest of the work rest on an unknown.
    """
    from . import decisions
    out = []
    for nid in sorted(nodes):
        for req in decisions.requests_of(nodes[nid]):
            if isinstance(req, dict) and req.get("target"):
                out.append(f"{nid} -> {req['target']}: "
                           f"{str(req.get('proposal', '')).strip()}")
    return out


def _stop(outcome: str, why: str) -> dict:
    return {"next": "stop", "outcome": outcome, "why": why}


def _resume(why: str) -> dict:
    return {"next": "resume", "outcome": None, "why": why}


def stop_early(round_no: int, *, failed: str | None, worked: bool) -> dict | None:
    """What ends a run before the floor is even checked; None if nothing does.
    BLOCKED is not among them: E measures first, and `decide` tells a run that
    is blocked from one that only waits for H."""
    if failed:
        return _stop("error", failed)
    if round_no > 1 and not worked:
        return _stop("stalled", "a resumed round ran no command: the intent author "
                                "answered without working. If it disputes a gap, "
                                "that is H's to judge.")
    return None


def waiting(goal: dict | None, requests: list[str] = ()) -> list[str]:
    """What waits for H, one line each: the open decision requests, then what H'
    named as WAITING (unmet only because it rests on H)."""
    return list(requests) + list((goal or {}).get("waiting") or [])


def decide(round_no: int, max_rounds: int, *, claimed: str | None,
           floor_green: bool, goal: dict | None, requests: list[str] = (),
           why: str = "", rework: list[dict] = ()) -> dict:
    """Stop or resume, after the floor (and on a green one, the goal) was checked.
    `goal` is the reviewer's answer -- {"gaps": [...], "waiting": [...]} -- or
    {"unavailable": reason}; None when it was not asked (a red floor). `why` is
    I's reason, when it said BLOCKED. `rework` are the answers H' gave in H's
    place, in an unsupervised run, that the work has to follow
    (engine/unsupervised.rework): they come first -- the goal is checked against
    the work after it has followed them."""
    blocked = claimed == "BLOCKED"
    if rework:
        step = _resume(f"H' answered {len(rework)} decision request(s) in H's place, "
                       "and the work has to follow")
        if round_no >= max_rounds:
            return _stop("limit", f"{max_rounds} round(s), and {step['why']}")
        return step
    if blocked and not (floor_green and goal and "unavailable" not in goal
                        and not goal.get("gaps") and waiting(goal, requests)):
        return _stop("blocked", why or "(no reason given)")
    if floor_green:
        if goal is None or "unavailable" in goal:
            reason = (goal or {}).get("unavailable", "not asked")
            if claimed == "DONE":
                return _stop("unchecked", "the floor is green and the intent author said "
                                          f"DONE; H' could not check the goal ({reason})")
            step = _resume("the floor is green, but H' could not check the goal "
                           f"({reason}) and the intent author did not say DONE")
        elif not goal.get("gaps"):
            waits = waiting(goal, requests)
            if waits:
                return _stop("asking", ("the intent author said BLOCKED, but nothing is "
                                        "missing that it could close -- " if blocked else "")
                             + f"{len(waits)} item(s) wait for H: " + "; ".join(waits))
            return _stop("done", "the floor is green, H' found no gap, and nothing "
                                 "waits for H")
        else:
            step = _resume(f"H' found {len(goal['gaps'])} gap(s)")
    else:
        step = _resume("the floor is red")
    if round_no >= max_rounds:
        return _stop("limit", f"{max_rounds} round(s), and {step['why']}")
    return step


def failures(floor: dict) -> list[str]:
    """E's failures, one line each: the tests' FAIL lines, the gate's HARD errors."""
    out = []
    if not floor["tests"]["passed"]:
        out += [ln.strip() for ln in floor["tests"]["text"].splitlines()
                if ln.startswith("FAIL")] or ["the tests fail (run `test`)"]
    if not floor["gate"]["passed"]:
        out += [ln.strip()[4:] for ln in floor["gate"]["text"].splitlines()
                if ln.strip().startswith("[x]")] or ["the gate blocks (run `gate`)"]
    return out


_ANSWERED = {
    "accepted": "ACCEPTED   {node} -> {target}: {proposal}",
    "rejected": "REJECTED   {node} -> {target}: {proposal} -- {reason}",
    "left for H": "OPEN       {node} -> {target}: {proposal} -- {reason}",
}


def _answers(answered: list[dict]) -> list[str]:
    if not answered:
        return []
    lines = ["H' ANSWERED YOUR DECISION REQUESTS IN H'S PLACE (an unsupervised run: each "
             "answer is an ADR in ARCHITECTURE.md, and H reviews it afterwards):"]
    lines += ["- " + _ANSWERED[a["decision"]].format(**a) for a in answered]
    lines.append(
        "An ACCEPTED request for a node authorises exactly that change, even to a node "
        "you were given: make it, through `revise` or `code`. One for ARCHITECTURE.md is "
        "recorded; a design that ASSUMED it may now say it is decided. A REJECTED one: "
        "your work assumed it -- change the work, or ask differently. An OPEN one still "
        "waits for H.")
    return lines


def resume_prompt(round_no: int, max_rounds: int, floor: dict | None,
                  goal: dict | None, answered: list[dict] = ()) -> str:
    """What I is told when it is sent back: which round, what is missing -- and,
    in an unsupervised run, what H' decided in H's place."""
    parts = [f"ROUND {round_no} of at most {max_rounds}. You stopped, but the run is "
             "not done -- E and H' checked it after you."]
    if floor and not floor["green"]:
        parts.append("THE FLOOR IS RED (E: the tests you ran are recorded, the gate "
                     "was run):")
        parts += [f"- {f}" for f in failures(floor)]
    elif goal and goal.get("gaps"):
        parts.append("The floor is green. THE GOAL IS NOT MET -- H' checked TASK.md "
                     "against the specs and the tests and found:")
        parts += [f"- {g}" for g in goal["gaps"]]
    elif goal and "unavailable" in goal:
        parts.append("The floor is green, but H' could not check the goal. If the task "
                     "is done, say so; if not, go on.")
    elif not answered:
        parts.append("The floor is green, but the goal was not checked. If the task is "
                     "done, say so; if not, go on.")
    parts += _answers(answered)
    parts.append(
        "Close them the way your manual says -- through the commands, never by hand. "
        "The graph, the specs and your growth record (`intents`) are as you left "
        "them. If something above is wrong, or you cannot close it honestly, say "
        "why and end with the line BLOCKED: <reason> -- H decides. When everything "
        "is met, end your last message with the line DONE.")
    return "\n".join(parts)


# ---- the facts H' judges the goal by -- computed, not judged ----------------------

TEST_SOURCE_BUDGET = 60_000     # characters of test source shown in full; then names
_TEST_FILES = ("test_*.py", "*_test.py", "*.test.ts", "*.test.js", "*.spec.ts",
               "*.spec.js", "*_test.go", "*_test.dart")
_TEST_NAMES = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)"
                         r"|\b(?:it|test)\(\s*['\"`]([^'\"`]+)", re.M)


def _test_files(build_roots: list[Path]) -> list[Path]:
    found = set()
    for build_root in build_roots:
        for pattern in _TEST_FILES:
            for path in Path(build_root).rglob(pattern):
                if not EXCLUDED_DIRS & set(path.relative_to(build_root).parts):
                    found.add(path)
    return sorted(found)


def _tests(root: Path, build_roots: list[Path]) -> str:
    out, budget = [], TEST_SOURCE_BUDGET
    for path in _test_files(build_roots):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        if len(text) <= budget:
            budget -= len(text)
            out.append(f"--- {rel}\n{text.rstrip()}")
        else:
            names = [a or b for a, b in _TEST_NAMES.findall(text)]
            out.append(f"--- {rel} (names only: over the size shown in full)\n"
                       + "\n".join(f"  {n}" for n in names))
    return "\n".join(out) or "(no test file found)"


def _pending(nodes: dict, root: Path) -> str:
    try:
        waiting = accepted.pending(nodes, root)
    except accepted.Unreadable:
        return "(the accepted state is unreadable -- the gate reports it)"
    lines = [f"- {c['node']}: " + "; ".join(why for gate, why in c["reasons"] if gate == "HARD")
             + (f"  REJECTED: {c['rejected']['reason']}" if c.get("rejected") else "")
             for c in waiting]
    lines += [f"- {nid}: accepted by H' under the delegation, awaiting H's review"
              for nid in accepted.awaiting_review(root)]
    return "\n".join(lines) or "(none)"


def facts(nodes: dict, root: str | Path, floor: dict, build_roots: list[Path]) -> str:
    """Everything H' needs to check the goal, in one text: the floor, every node's
    spec (its frontmatter), the pending HARD changes, and the tests."""
    root = Path(root)
    passed = [ln.strip() for ln in floor["tests"]["text"].splitlines() if ln.startswith("PASS")]
    warned = [ln.strip()[4:] for ln in floor["gate"]["text"].splitlines()
              if ln.strip().startswith("[!]")]
    specs = []
    for nid in sorted(nodes):
        front = {k: v for k, v in nodes[nid].items() if not k.startswith("_")}
        specs.append(f"--- {nid}\n"
                     + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip())
    return "\n\n".join([
        "THE FLOOR: " + ("green -- the tests pass and the gate passes" if floor["green"]
                         else "RED: " + "; ".join(failures(floor))),
        "tests:\n" + ("\n".join(passed) or "(no build root with tests)"),
        "gate warnings:\n" + ("\n".join(warned) or "(none)"),
        "THE SPECS (every node's SPEC.md frontmatter):\n" + "\n\n".join(specs),
        "PENDING HARD CHANGES (they wait for a decision):\n" + _pending(nodes, root),
        "DECISION REQUESTS THE GRAPH RAISED (they wait for H; the work assumes an "
        "answer):\n" + ("\n".join(f"- {r}" for r in open_requests(nodes)) or "(none)"),
        "THE TESTS:\n" + _tests(root, build_roots),
    ])
