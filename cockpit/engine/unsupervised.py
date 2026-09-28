"""An unsupervised run: between rounds, H' decides in H's place what H would.

The run switch has three settings (AUTONOMY.md §2): off (H writes the intent in
the cockpit), on (an agent does, and what is above a node waits for H), and
unsupervised. In a supervised run -- on -- a decision request waits for H and the
run ends `asking`; H answers, and the next run builds on it. In an unsupervised
run nobody is there to answer, so H' does, between rounds:

  requests    every open decision request is answered -- accepted or rejected
              as worded, never reworded (answer). The answer is recorded as an
              ADR that says H' gave it, and the request is removed
              (engine.inbox.decide_in_hs_place).
  delegated   the pending HARD changes inside what H delegated are decided as
              `cli.py decide` would (engine.assist.delegated) -- so an unsupervised
              run requires the delegation to be on.

Everything H' decides here stays H's to review, and nothing new is invented to
make that so: an answer is a line in ARCHITECTURE.md, a change to that file is a
HARD change only H may accept, and so every answer waits in H's pending list
until H accepts it -- or rejects it, which blocks the gate until it is taken
back. An acceptance under the delegation waits for H's confirmation as always.

What stays H's even here: TASK.md (the goal), the zones H declared (a HARD
change in one is outside the delegation and simply stays pending), and every
answer after the fact. An answer H' is unsure of (below AUTO_ACCEPT_CONF) is not
given: the request stays open, and the run ends `asking` for it.

An accepted request that targets a node is not merged into that node here --
it is prose (engine/inbox.py). The ADR authorises the change; the intent author
makes it through P. `rework` says which answers send it back to work.

H' is INJECTED (answer_fn, brief_fn), as in engine.assist: the engine calls no
model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import assist, autonomy, decisions, inbox, lifecycle, parser

# answer_fn(request, asker, asker_spec, target_text) -> {decision, reason, confidence,
# model} | None; raises RuntimeError when H' is unavailable
AnswerFn = Callable[[dict, str, str, str], "dict | None"]

ACCEPTED, REJECTED, LEFT = "accepted", "rejected", "left for H"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _target_text(nodes: dict, root: Path, target: str) -> str:
    if target == decisions.ARCHITECTURE:
        return _read(root / decisions.ARCHITECTURE)
    return _read(Path(nodes[target]["_path"])) if target in nodes else ""


def answer(root: str | Path, answer_fn: AnswerFn) -> list[dict]:
    """Answer every open decision request in H's place. Returns one record per
    request: {node, target, proposal, decision: accepted | rejected | left for H,
    reason, by}. An unavailable H' leaves the rest for H -- the run then ends
    `asking` for them, as a supervised one would."""
    root = Path(root)
    out: list[dict] = []
    left: set[tuple[str, str]] = set()     # requests H' did not answer: skip them
    unavailable = ""
    while True:
        nodes = parser.load_nodes(str(root))  # re-read: every answer rewrites a spec
        todo = [(nid, target, proposal) for nid, target, proposal in decisions.pending(nodes)
                if (nid, proposal) not in left]
        if not todo:
            return out
        nid, target, proposal = todo[0]
        index, req = next((i, r) for i, r in enumerate(decisions.requests_of(nodes[nid]))
                          if isinstance(r, dict)
                          and str(r.get("proposal", "")).strip() == proposal)
        record = {"node": nid, "target": target, "proposal": proposal}
        verdict = None
        if not unavailable:
            try:
                verdict = answer_fn(req, nid, _read(Path(nodes[nid]["_path"])),
                                    _target_text(nodes, root, target))
            except RuntimeError as exc:
                unavailable = f"H' unavailable: {exc}"
        if unavailable or not verdict:
            left.add((nid, proposal))
            out.append({**record, "decision": LEFT, "by": None,
                        "reason": unavailable or "H' gave no usable answer"})
            continue
        if verdict["confidence"] < autonomy.AUTO_ACCEPT_CONF:
            left.add((nid, proposal))
            out.append({**record, "decision": LEFT, "by": verdict["model"],
                        "reason": f"H' is unsure (confidence {verdict['confidence']:.2f} < "
                                  f"{autonomy.AUTO_ACCEPT_CONF}): {verdict['reason']}"})
            continue
        accept = verdict["decision"] == "accept"
        inbox.decide_in_hs_place(nodes, root, nid, index, proposal, accept=accept,
                                 reason=verdict["reason"], by=f"H' ({verdict['model']})")
        decision = ACCEPTED if accept else REJECTED
        lifecycle.log_autonomy(root, {"actor": "H'", "by": verdict["model"],
                                      "action": "request-" + decision, "node": nid,
                                      "target": target, "proposal": proposal,
                                      "confidence": verdict["confidence"],
                                      "reason": verdict["reason"]})
        out.append({**record, "decision": decision, "by": verdict["model"],
                    "reason": verdict["reason"]})


def rework(answered: list[dict], claimed: str | None = None) -> list[dict]:
    """The answers that send the intent author back to work: a rejection (its
    work assumed the answer), an acceptance for a node (the ADR authorises a
    change it has to make) -- and, when it said BLOCKED, every answer: it was
    waiting for exactly that."""
    given = [a for a in answered if a["decision"] in (ACCEPTED, REJECTED)]
    if claimed == "BLOCKED":
        return given
    return [a for a in given
            if a["decision"] == REJECTED or a["target"] != decisions.ARCHITECTURE]


def stand_in(root: str | Path, answer_fn: AnswerFn, brief_fn) -> dict:
    """One round's worth of H's place: answer the open requests, then let H'
    decide the pending HARD changes inside the delegation. {answered: [...],
    delegated: [...]} -- the second as engine.assist.delegated reports it."""
    answered = answer(root, answer_fn)
    try:
        delegated = assist.delegated(parser.load_nodes(str(root)), root, brief_fn)
    except ValueError as exc:         # the delegation is off, or nothing is tracked
        delegated = [{"node": "-", "action": "left for H", "reason": str(exc)}]
    except RuntimeError as exc:       # H' unavailable
        delegated = [{"node": "-", "action": "left for H", "reason": f"H' unavailable: {exc}"}]
    return {"answered": answered, "delegated": delegated}
