"""H's inbox: the requests waiting for a human decision, and resolving them.

Waivers and decision requests give an agent a channel TO the human architect.
This module is the channel back: it lists what is pending and performs the
decision on disk, so the cockpit can offer Grant / Reject / Accept instead of
leaving H to hand-edit YAML -- which is what "the back-channel" amounted to
before, and only if H happened to press Validate and read the warnings.

Like engine/nodes.py it writes files; unlike the checks it is never called by the
gate. Every action is H's, taken in H's tool -- except decide_in_hs_place, which
an unsupervised run calls for H', and which leaves an ADR for H to review.

    pending(nodes, root)                 everything awaiting H: waivers, decision
                                         requests, and -- given a root that tracks
                                         an accepted state -- pending HARD changes
    grant_waiver / reject_waiver         a requested waiver
    accept_decision                      a request targeting ARCHITECTURE.md:
                                         the proposal becomes a dated ADR
    resolve_decision                     a request targeting a NODE, after H has
                                         edited that contract by hand
    reject_decision                      either target; optionally recorded as an ADR
    decide_in_hs_place                   an UNSUPERVISED run: H' answers a request of
                                         either target, recorded as an ADR H reviews

A decision that targets a node is deliberately NOT applied automatically: a
proposal like "provides: + a graphical interface" is prose, and merging prose
into a contract is exactly the judgement H is being asked for.

A pending HARD change is listed here but decided through engine.assist (accept,
or reject with a reason), which records whether H followed the brief from H'.

Actions verify the request they act on still says what the caller saw. The
cockpit's list can be stale -- an agent or an editor may have changed the file
since -- and acting on a shifted index would resolve the wrong request.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import frontmatter

from . import accepted, assist, decisions, waivers

ADR_HEADING = "## Decisions (ADRs)"


# ----------------------------------------------------------------- reading ---
def pending(nodes: dict[str, dict], root: str | Path | None = None) -> list[dict]:
    """Every request awaiting H, waivers first, each as a flat record. With a
    root, pending HARD changes follow (engine/accepted.py) -- a REJECTED one is
    decided and waits on the agent, not on H, so it is not listed."""
    out: list[dict] = []
    for nid, exc in sorted(waivers.requested_waivers(nodes).items()):
        out.append({"type": "waiver", "node": nid, "subject": str(exc.get("kind") or ""),
                    "text": str(exc.get("reason") or "").strip(),
                    "proposed_expiry": _iso(exc.get("proposed_expiry"))})
    for nid in sorted(nodes):
        for index, req in enumerate(decisions.requests_of(nodes[nid])):
            if not decisions._valid(nid, req, nodes):
                continue
            out.append({"type": "decision", "node": nid, "index": index,
                        "subject": str(req["target"]).strip(),
                        "text": str(req["proposal"]).strip(),
                        "reason": str(req["reason"]).strip()})
    if root is not None:
        try:
            hard = accepted.pending(nodes, root)
        except accepted.Unreadable:
            hard = []   # validate reports it as HARD; nothing to decide here
        briefs = assist.load(root)
        for change in hard:
            if change["rejected"]:
                continue
            why = next(r for g, r in change["reasons"] if g == "HARD")
            out.append({"type": "HARD", "node": change["node"], "subject": why,
                        "change": change, "fingerprint": change["fingerprint"],
                        "brief": assist.brief_for(root, change, briefs),
                        "stale": assist.is_stale(root, change, briefs)})
        # acceptances H' made under the delegation wait for H's review: confirm or overrule
        pending_nodes = {c["node"] for c in hard}
        state = accepted.load(root) if accepted.tracked(root) else None
        for nid in accepted.awaiting_review(root) if state else []:
            if nid in pending_nodes:
                continue   # changed again since: it is listed as a pending change
            record = state["nodes"][nid]
            out.append({"type": "delegated", "node": nid,
                        "subject": f"accepted by H' under the delegation "
                                   f"({record.get('at', '')[:16]})",
                        "record": record, "fingerprint": None})
    return out


def awaiting(nodes: dict[str, dict], root: str | Path | None = None) -> set[str]:
    """Nodes with at least one request awaiting H -- for marking them in a view."""
    return {r["node"] for r in pending(nodes, root)}


# ----------------------------------------------------------------- waivers ---
def grant_waiver(nodes: dict[str, dict], nid: str, owner: str, expires,
                 today: _dt.date | None = None) -> Path:
    """Turn a requested waiver into a granted one, owned and time-boxed."""
    today = today or _dt.date.today()
    owner = (owner or "").strip()
    if not owner:
        raise ValueError("a granted waiver needs an owner -- the person accepting the risk")
    due = _parse_date(expires)
    if due is None:
        raise ValueError(f"expiry {expires!r} is not a date (expected YYYY-MM-DD)")
    if due < today:
        raise ValueError(f"expiry {due.isoformat()} is in the past; the grant would "
                         "block the gate the moment it is written")
    post, path = _load(nodes, nid)
    request = post.metadata.get("waiver")
    if not isinstance(request, dict) or waivers.state_of(request) != "requested":
        raise ValueError(f"{nid} has no requested waiver (it may have changed on disk)")
    granted = {"state": "granted", "kind": request.get("kind"), "owner": owner,
               "expires": due.isoformat()}
    if request.get("reason"):
        granted["reason"] = request["reason"]
    post.metadata["waiver"] = granted
    return _save(post, path)


def reject_waiver(nodes: dict[str, dict], nid: str) -> Path:
    """Remove a requested waiver: the node must meet the rule after all."""
    post, path = _load(nodes, nid)
    request = post.metadata.get("waiver")
    if not isinstance(request, dict) or waivers.state_of(request) != "requested":
        raise ValueError(f"{nid} has no requested waiver (it may have changed on disk)")
    del post.metadata["waiver"]
    return _save(post, path)


# --------------------------------------------------------------- decisions ---
def accept_decision(nodes: dict[str, dict], root: str | Path, nid: str, index: int,
                    expected_proposal: str, today: _dt.date | None = None) -> list[Path]:
    """Record an ARCHITECTURE.md decision as a dated ADR and remove the request."""
    post, path, req = _decision(nodes, nid, index, expected_proposal)
    target = str(req["target"]).strip()
    if target != decisions.ARCHITECTURE:
        raise ValueError(f"this request targets {target!r}, a node contract: edit that "
                         "contract, then resolve the request -- a proposal in prose is "
                         "not merged into a contract automatically")
    adr = _append_adr(root, _adr_line(req, nid, today))
    return [adr, _remove_request(post, path, index)]


def resolve_decision(nodes: dict[str, dict], nid: str, index: int,
                     expected_proposal: str) -> Path:
    """Remove a request whose target H has already changed by hand."""
    post, path, _ = _decision(nodes, nid, index, expected_proposal)
    return _remove_request(post, path, index)


def decide_in_hs_place(nodes: dict[str, dict], root: str | Path, nid: str, index: int,
                       expected_proposal: str, *, accept: bool, reason: str, by: str,
                       today: _dt.date | None = None) -> list[Path]:
    """An unsupervised run (engine/unsupervised.py): H' answers a request in H's
    place. The answer is always recorded -- as an ADR that says it was H' who
    decided, for which target, and why -- and the request is removed.

    Recording it in ARCHITECTURE.md is what keeps it H's: a change to that file
    is a HARD change nobody but H may accept, so every answer H' gave waits in
    H's pending list until H accepts it -- or rejects it, and the gate blocks
    until it is taken back. An ACCEPTED request that targets a node is not merged
    into that node's contract here, for the reason above: it is prose. The ADR
    authorises the change; the intent author makes it, through P."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("an answer in H's place needs a reason -- H reviews it")
    post, path, req = _decision(nodes, nid, index, expected_proposal)
    note = f"decided by {by} in an unsupervised run, awaiting H's review: {reason}"
    line = _adr_line(req, nid, today, rejected=not accept, note=note)
    return [_append_adr(root, line), _remove_request(post, path, index)]


def reject_decision(nodes: dict[str, dict], root: str | Path, nid: str, index: int,
                    expected_proposal: str, record: bool = True,
                    today: _dt.date | None = None) -> list[Path]:
    """Remove a request H decided against, optionally recording the rejection as an
    ADR -- so the next agent does not ask the same question again."""
    post, path, req = _decision(nodes, nid, index, expected_proposal)
    written = []
    if record:
        written.append(_append_adr(root, _adr_line(req, nid, today, rejected=True)))
    written.append(_remove_request(post, path, index))
    return written


# ----------------------------------------------------------------- helpers ---
def _iso(value) -> str | None:
    d = _parse_date(value)
    return d.isoformat() if d else None


def _parse_date(value) -> _dt.date | None:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _load(nodes: dict[str, dict], nid: str):
    if nid not in nodes:
        raise ValueError(f"no such node: {nid}")
    path = Path(nodes[nid]["_path"])
    return frontmatter.load(path), path


def _save(post, path: Path) -> Path:
    # sort_keys=False: a decision must not reorder the rest of someone's spec
    text = frontmatter.dumps(post, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def _decision(nodes, nid, index, expected_proposal):
    post, path = _load(nodes, nid)
    reqs = decisions.requests_of(post.metadata)
    if not 0 <= index < len(reqs) or not isinstance(reqs[index], dict) \
            or str(reqs[index].get("proposal", "")).strip() != (expected_proposal or "").strip():
        raise ValueError(f"the decision request on {nid} changed on disk -- reload and "
                         "look again before deciding")
    return post, path, reqs[index]


def _remove_request(post, path: Path, index: int) -> Path:
    reqs = list(decisions.requests_of(post.metadata))
    del reqs[index]
    if reqs:
        post.metadata[decisions.FIELD] = reqs
    else:
        del post.metadata[decisions.FIELD]
    return _save(post, path)


def _adr_line(req: dict, nid: str, today, rejected: bool = False, note: str = "") -> str:
    today = today or _dt.date.today()
    text = re.sub(r"^\s*ADR\s*:\s*", "", str(req["proposal"]).strip(), flags=re.I)
    prefix = "Rejected: " if rejected else ""
    if not note:
        return f"- {today.isoformat()}: {prefix}{text} (requested by {nid})"
    # an answer in H's place names the target too: H reviews it without the request
    target = str(req.get("target") or "").strip()
    whom = f" for {target}" if target and target != decisions.ARCHITECTURE else ""
    return f"- {today.isoformat()}: {prefix}{text} (requested by {nid}{whom}; {note})"


def _append_adr(root: str | Path, line: str) -> Path:
    """Append a line to the ADR section of ARCHITECTURE.md, creating the section if
    needed and replacing the bootstrap placeholder `- TODO` if it is all there is."""
    arch = Path(root) / "ARCHITECTURE.md"
    text = arch.read_text(encoding="utf-8") if arch.exists() else "# Architecture\n"
    if ADR_HEADING not in text:
        text = text.rstrip("\n") + f"\n\n{ADR_HEADING}\n"
    start = text.index(ADR_HEADING)
    nxt = text.find("\n## ", start + len(ADR_HEADING))
    end = len(text) if nxt == -1 else nxt + 1
    items = [l for l in text[start + len(ADR_HEADING):end].strip("\n").splitlines()
             if l.strip() and l.strip() != "- TODO"]
    section = ADR_HEADING + "\n" + "\n".join(items + [line]) + "\n"
    rest = text[end:]
    arch.write_text(text[:start] + section + ("\n" + rest if rest else ""), encoding="utf-8")
    return arch
