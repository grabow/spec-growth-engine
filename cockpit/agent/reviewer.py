"""Draft reviewer (role H', the architect's deputy), on its own endpoint
(SGE_REVIEWER_* in cockpit/.env).

At the SOFT gate after Draft, this gives a second, skeptical opinion on the
planner's SPEC.md -- judging what the DETERMINISTIC engine cannot: contract
altitude, intent placement, testable acceptance criteria, reuse, and whether the
contract actually covers the human's stated intent.

It is ADVISORY (D1): findings are shown, the human still decides Save. The
deterministic gates (validate/drift/lifecycle) remain the hard floor and run
regardless -- H' never waves through a structurally broken spec. No API key ->
returns None (the feature degrades, drafting still works).
"""
from __future__ import annotations

from .llm import _call_tool, _client, reviewer_model

_REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_review",
        "description": "Review a drafted SPEC.md against the human's intent and the architecture.",
        "parameters": {
            "type": "object",
            "required": ["verdict", "confidence", "findings"],
            "properties": {
                "verdict": {"type": "string", "enum": ["approve", "revise", "reject"]},
                "confidence": {"type": "number", "description": "0.0 .. 1.0"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["severity", "area", "message"],
                        "properties": {
                            "severity": {"type": "string", "enum": ["blocker", "suggestion"]},
                            "area": {
                                "type": "string",
                                "description": "contract|placement|acceptance|depends_on|code|"
                                "secrets|verification|reuse|intent",
                            },
                            "message": {"type": "string", "description": "One concise, actionable line."},
                        },
                    },
                },
            },
        },
    },
}

_GUIDE = (
    "You are H', the architect's reviewer. Critique the planner's SPEC.md draft. "
    "Do NOT re-check things the deterministic engine already enforces (YAML, graph "
    "structure, import drift, status evidence). Judge what only review can:\n"
    "- altitude: contract is WHAT (outward promise), not HOW (that is design);\n"
    "- placement: this feature/behaviour belongs on THIS node, not its container/child;\n"
    "- acceptance_criteria: concrete and testable, derived from the intent; no TODO;\n"
    "- depends_on: usage only (never parent/ancestor/child);\n"
    "- code globs: into the code tree per the container's layout, never empty for a component;\n"
    "- secrets/verification: per ARCHITECTURE.md; offline-safe tests;\n"
    "- reuse: does it duplicate an existing capability (see registry)?;\n"
    "- intent fidelity: does the contract actually cover what the human asked?\n"
    "Be concise; each finding one actionable line. Use verdict 'approve' if only "
    "minor suggestions, 'revise' if a blocker is fixable in place, 'reject' if the "
    "draft is off-target. Call emit_review."
)


def review_draft(
    intent: str,
    spec: str,
    architecture: str = "",
    registry: list[dict] | None = None,
    model: str | None = None,
) -> dict | None:
    """Return {verdict, confidence, findings:[{severity, area, message}]}, or None
    without an API key (the feature is off) or without a usable answer. Raises
    RuntimeError, with the reason, when the provider refuses or the answer is
    cut off."""
    try:
        client = _client("reviewer")
    except RuntimeError:
        return None

    caps = "\n".join(
        f"- {c['node']}: {c.get('provides', [])}" for c in (registry or [])
    ) or "(none)"
    prompt = (
        f"{_GUIDE}\n\n"
        f"HUMAN INTENT:\n{intent}\n\n"
        f"DRAFTED SPEC.md:\n{spec}\n\n"
        f"ARCHITECTURE.md:\n{architecture or '(none)'}\n\n"
        f"EXISTING CAPABILITIES (for reuse):\n{caps}"
    )
    data, _ = _call_tool(client, _REVIEW_TOOL, prompt, model=model or reviewer_model())
    if not data:
        return None
    findings = []
    for f in data.get("findings", []):
        if isinstance(f, dict) and f.get("message"):
            findings.append({
                "severity": f.get("severity", "suggestion"),
                "area": f.get("area", ""),
                "message": str(f["message"]),
            })
    return {
        "verdict": data.get("verdict", "revise"),
        "confidence": data.get("confidence"),
        "findings": findings,
    }


# ---- assisted HARD (AUTONOMY.md 5c): prepare a decision, never take it ----------

_BRIEF_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_brief",
        "description": "Prepare a pending HARD change for the human architect's decision.",
        "parameters": {
            "type": "object",
            "required": ["recommendation", "confidence", "summary", "risks", "alternatives"],
            "properties": {
                "recommendation": {"type": "string", "enum": ["accept", "reject"]},
                "confidence": {
                    "type": "number",
                    "description": "0.0 .. 1.0: how likely the human, having read this, "
                                   "decides as you recommend",
                },
                "summary": {"type": "string",
                            "description": "2-3 sentences: what changes, and why it matters"},
                "risks": {"type": "array", "items": {"type": "string"},
                          "description": "one line each; empty if none"},
                "alternatives": {"type": "array", "items": {"type": "string"},
                                 "description": "non-breaking or smaller ways to the same "
                                                "end; one line each; empty if none"},
            },
        },
    },
}

_BRIEF_GUIDE = (
    "You are H', preparing a HARD decision for the human architect. You do NOT decide: "
    "you do the homework so the human can decide in a minute. The engine has already "
    "computed the facts below -- the change set, the consumers, what they mention, the "
    "evidence recorded against the old contract. Trust them; do not recompute them. "
    "Judge what only judgement can:\n"
    "- necessity: does the change serve what this node is for (its purpose, criteria, "
    "prose), or is it churn?\n"
    "- blast radius: given the consumers and what they mention, what breaks, and what "
    "has to be migrated?\n"
    "- alternatives: is there a non-breaking way -- add the new operation next to the "
    "old one, deprecate then migrate, a decision request instead of editing a node "
    "that was given?\n"
    "- fit: does it respect ARCHITECTURE.md; for a new container, is the boundary real?\n"
    "- intent fidelity: where the node's INTENT HISTORY is given, does the change still "
    "serve what it was grown for -- or does it quietly drop an earlier promise?\n"
    "Recommend 'accept' or 'reject'. Calibrate confidence honestly: it is compared, "
    "decision by decision, with what the human actually decides. Call emit_brief."
)


def brief_hard_change(
    report: str,
    accepted_spec: str,
    current_spec: str,
    architecture: str = "",
    model: str | None = None,
) -> dict | None:
    """Return {recommendation, confidence, summary, risks, alternatives, model},
    or None for an answer without a usable brief. Raises RuntimeError when H' is
    UNAVAILABLE (no API key, the provider refuses, the answer is cut off) -- with
    the reason, because "unavailable" alone sent nobody to the expired key. Advisory:
    engine.assist stores the brief, H decides."""
    client = _client("reviewer")   # RuntimeError without a key
    prompt = (
        f"{_BRIEF_GUIDE}\n\n"
        f"CHANGE SET (computed by the engine):\n{report}\n\n"
        f"ACCEPTED SPEC (before):\n{accepted_spec}\n\n"
        f"CURRENT SPEC.md (after):\n{current_spec}\n\n"
        f"ARCHITECTURE.md:\n{architecture or '(none)'}"
    )
    data, _ = _call_tool(client, _BRIEF_TOOL, prompt, model=model or reviewer_model())
    return {**data, "model": model or reviewer_model()} if data else None


# ---- the goal of a run (AUTONOMY.md: the run): is anything still missing? -----------

_GOAL_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_goal_check",
        "description": "Name what the task still asks for and the run has not delivered.",
        "parameters": {
            "type": "object",
            "required": ["summary", "gaps"],
            "properties": {
                "summary": {"type": "string",
                            "description": "1-2 sentences: where the run stands against the task"},
                "gaps": {"type": "array", "items": {"type": "string"},
                         "description": "one line each: '<the criterion, in a few words of "
                                        "TASK.md> -- <what is missing>'; only what the "
                                        "intent author can close; empty if none"},
                "waiting": {"type": "array", "items": {"type": "string"},
                            "description": "one line each: '<the criterion> -- <what only H "
                                           "may decide, that it rests on>'; statements unmet "
                                           "ONLY because they wait for H; empty if none"},
                "closed": {"type": "array", "items": {"type": "string"},
                           "description": "the gaps from the previous round that the facts now "
                                          "show met, copied verbatim; empty if none were given "
                                          "or none are closed"},
            },
        },
    },
}

_GOAL_GUIDE = (
    "You are H', checking whether an orchestrated run has met its goal. The intent "
    "author has stopped; you decide one thing: whether something the task asks for is "
    "still missing. The engine has computed the facts below -- the floor (the tests pass "
    "and the gate passes), every node's spec, the pending HARD changes, the tests. Trust "
    "them; do not recompute them.\n"
    "Go through TASK.md statement by statement -- what the system must DO, what must "
    "ALWAYS be true, and what it says DONE means (SPEC-GROWTH-ENGINE.md 3.12). A task "
    "states these however it likes: often under headings such as 'What it must do', "
    "'What must hold' or 'Done means', sometimes as plain prose with no headings at "
    "all. Judge what is SAID, not where it stands. Name a GAP for each statement the "
    "facts show unmet:\n"
    "- a behaviour the task lists that no test exercises;\n"
    "- a promise the task makes or changes that no contract states, or a contract that "
    "still states the old one;\n"
    "- a node at a status the task does not allow;\n"
    "- a wish of the task that nothing in the graph serves.\n"
    "Not a gap: what the floor catches (it is green); style; a better design; anything "
    "the task does not ask for; a pending HARD change as such (it waits for a decision -- "
    "judge the contract it carries); what you merely cannot verify from the facts.\n"
    "WAITING, not a gap: a statement unmet ONLY because it rests on something the "
    "intent author may not decide -- an open decision request, a pending HARD change "
    "that only H may accept, a node held back from its status by one of them. Name it "
    "under `waiting`, with what it waits for. The intent author cannot close it, and "
    "sending it back for it only burns a round. If the author COULD close it -- the "
    "change is its to make, only not made yet -- it is a gap.\n"
    "Each gap in one line: the criterion, in a few words of TASK.md, then what is "
    "missing. Say WHAT, never HOW -- how to close it is the intent author's. No gap "
    "and nothing waiting means the goal is met.\n"
    "Where gaps FROM THE PREVIOUS ROUND are given, answer for each one first: put it "
    "in `closed` if the facts now show it met, repeat it in `gaps` if they do not, or "
    "move it to `waiting` if all that is left of it waits for H. "
    "Only then look for new ones -- a run whose reviewer swaps its findings every round "
    "converges by exhaustion, not by agreement. Call emit_goal_check."
)


def check_goal(task: str, facts: str, previous: list[str] = (),
               model: str | None = None) -> dict | None:
    """Return {gaps, waiting, closed, summary, model} -- no gap and nothing waiting
    means the goal is met; `waiting` is what only H can move (a gap the intent
    author cannot close is not sent back to it) -- or
    None for an answer without a usable check. Raises RuntimeError when H' is
    UNAVAILABLE (no API key, the provider refuses, the answer is cut off). It sees
    the task and E's facts, not what the intent author said about its own work:
    nobody marks their own work, and the judge is not primed by the claim.

    `previous` are the gaps this check named after the LAST round. Without them it
    has no memory and judges afresh every time: run 11 was sent back three times,
    each time for two different things, and converged only when the rounds ran out.
    Given them, it must say of each whether it is closed before it looks for new
    ones -- so progress is visible and a new finding has to stand next to the old."""
    from engine.assist import _items   # a list sent as a JSON string, as GLM does
    client = _client("reviewer")   # RuntimeError without a key
    prompt = (
        f"{_GOAL_GUIDE}\n\n"
        f"TASK.md:\n{task}\n\n"
        f"FACTS (computed by the engine):\n{facts}"
        + ("\n\nGAPS YOU NAMED AFTER THE PREVIOUS ROUND (answer for each):\n"
           + "\n".join(f"- {g}" for g in previous) if previous else "")
    )
    data, _ = _call_tool(client, _GOAL_TOOL, prompt, model=model or reviewer_model())
    if not data:
        return None
    return {"gaps": _items(data.get("gaps")), "waiting": _items(data.get("waiting")),
            "closed": _items(data.get("closed")),
            "summary": str(data.get("summary", "")), "model": model or reviewer_model()}


# ---- an unsupervised run: H' answers a decision request in H's place --------------

_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_answer",
        "description": "Accept or reject a decision request, in the human architect's place.",
        "parameters": {
            "type": "object",
            "required": ["decision", "reason", "confidence"],
            "properties": {
                "decision": {"type": "string", "enum": ["accept", "reject"]},
                "reason": {"type": "string",
                           "description": "1-3 sentences, for H, who reviews this answer "
                                          "afterwards and for the intent author, who acts "
                                          "on it: why this answer"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
}

_ANSWER_GUIDE = (
    "You are H', the architect's deputy, in an UNSUPERVISED run: nobody is watching, "
    "and a node has asked for a decision above it -- an invariant in ARCHITECTURE.md, "
    "or the contract of a node the intent author may not grow (the root, a container, "
    "a file H gave it). You answer in H's place. H reviews every answer afterwards and "
    "can take it back; until then the run builds on it.\n"
    "Decide the proposal AS WORDED: accept it, or reject it. You do not reword it and "
    "you do not propose another -- if a different answer would be right, reject and say "
    "which, and the intent author asks again.\n"
    "Judge it as H would:\n"
    "- need: does the task (TASK.md) actually require it, or could the node do without "
    "reaching above itself?\n"
    "- fit: is it consistent with ARCHITECTURE.md and the target's contract, or does it "
    "quietly change a boundary H drew?\n"
    "- reach: an invariant binds every node; a container's contract is a public promise. "
    "The wider the reach, the higher the bar.\n"
    "- reversibility: prefer the answer that is cheaper to take back.\n"
    "Calibrate confidence honestly: below 0.6 your answer is not used, and the request "
    "waits for H. Call emit_answer."
)


def answer_request(request: dict, asker: str, asker_spec: str, target_text: str,
                   task: str = "", architecture: str = "",
                   model: str | None = None) -> dict | None:
    """Return {decision: accept | reject, reason, confidence, model}, or None for an
    answer without a usable decision. Raises RuntimeError when H' is UNAVAILABLE,
    as the other calls do. It decides the proposal as worded and authors nothing
    new; engine.unsupervised records the answer, and H reviews it."""
    client = _client("reviewer")   # RuntimeError without a key
    prompt = (
        f"{_ANSWER_GUIDE}\n\n"
        f"THE REQUEST (raised by {asker}):\n"
        f"  target:   {request.get('target')}\n"
        f"  proposal: {str(request.get('proposal', '')).strip()}\n"
        f"  reason:   {str(request.get('reason', '')).strip()}\n\n"
        f"THE TARGET, as it stands:\n{target_text or '(empty)'}\n\n"
        f"THE ASKING NODE's SPEC.md:\n{asker_spec}\n\n"
        f"ARCHITECTURE.md:\n{architecture or '(none)'}\n\n"
        f"TASK.md:\n{task or '(not given)'}"
    )
    data, _ = _call_tool(client, _ANSWER_TOOL, prompt, model=model or reviewer_model())
    if not data or data.get("decision") not in ("accept", "reject"):
        return None
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {"decision": data["decision"], "reason": str(data.get("reason", "")).strip(),
            "confidence": confidence, "model": model or reviewer_model()}
