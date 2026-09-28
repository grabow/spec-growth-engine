"""Decision requests: asking H for a decision that is above the asker's authority.

Some decisions do not belong to the node that needs them. A GUI toolkit is an
architectural decision (ARCHITECTURE.md); what a container provides is the
container's contract. An agent may edit neither, and in an unattended run there
is nobody to "ask instead". Run 02 showed what happens then: the agent recorded
the toolkit choice nowhere, and bent its design to fit the wording of a container
contract it could not change -- a design space narrowed by authority, not merit.

A decision request records the question where it arises and grants nothing:

    decision_requests:
      - target: ARCHITECTURE.md        # or the id of another node, e.g. svc
        proposal: "ADR: the GUI uses tkinter from the standard library."
        reason: "Increment 2 asks for a GUI; stdlib-only leaves tkinter."

This is NOT a waiver. A waiver is a deviation from a rule that exists;
a decision request is a decision that does not exist yet. Choosing tkinter
breaks no rule -- it is simply undecided.

H resolves a request by changing the target (adding the ADR, extending the
container's contract) and deleting the request; a rejection is a deletion too,
optionally recorded as an ADR. In an unsupervised run H' resolves it in H's
place (engine/unsupervised.py): always as an ADR naming H', which H reviews.

What is enforced here:

    shape      each request has target, proposal and reason          -> HARD
    target     ARCHITECTURE.md or an existing node, never itself     -> HARD
    visible    every pending request, on every run                   -> WARN
    not done   `verified` while a request is pending                 -> HARD

NOT enforced: that H actually changed the target before the request was deleted.
Deleting the request is the resolution; git history is the audit.
"""
from __future__ import annotations

FIELD = "decision_requests"
ARCHITECTURE = "ARCHITECTURE.md"
_REQUIRED = ("target", "proposal", "reason")


def requests_of(node: dict) -> list:
    """The node's requests as a list. A single mapping is accepted as a list of
    one -- refusing it would push a second request back into prose, which is the
    failure this module exists to prevent."""
    raw = node.get(FIELD)
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return raw
    return [raw]   # malformed; `issues` says so


def _valid(nid: str, req, nodes: dict[str, dict]) -> bool:
    if not isinstance(req, dict):
        return False
    if any(not str(req.get(k) or "").strip() for k in _REQUIRED):
        return False
    target = str(req["target"]).strip()
    return target != nid and (target == ARCHITECTURE or target in nodes)


def pending(nodes: dict[str, dict]) -> list[tuple[str, str, str]]:
    """(requesting node, target, proposal) for every well-formed pending request."""
    out = []
    for nid in sorted(nodes):
        for req in requests_of(nodes[nid]):
            if _valid(nid, req, nodes):
                out.append((nid, str(req["target"]).strip(), str(req["proposal"]).strip()))
    return out


def issues(nodes: dict[str, dict]) -> list[tuple[str, str]]:
    """[(severity, message)] for every decision-request problem. HARD | WARN."""
    out: list[tuple[str, str]] = []
    for nid in sorted(nodes):
        node = nodes[nid]
        raw = node.get(FIELD)
        if raw is None:
            continue
        if not isinstance(raw, (dict, list)):
            out.append(("HARD", f"malformed {FIELD} on {nid}: expected a list of "
                                f"mappings with {', '.join(_REQUIRED)}"))
            continue
        reqs = requests_of(node)
        for i, req in enumerate(reqs, 1):
            label = f"decision request {i} on {nid}"
            if not isinstance(req, dict):
                out.append(("HARD", f"{label} is not a mapping with {', '.join(_REQUIRED)}"))
                continue
            missing = [k for k in _REQUIRED if not str(req.get(k) or "").strip()]
            if missing:
                out.append(("HARD", f"{label} has no {', '.join(missing)} (a request "
                                    "must say what, of whom, and why)"))
            target = str(req.get("target") or "").strip()
            if target and target == nid:
                out.append(("HARD", f"{label} targets its own node: edit your own "
                                    "SPEC.md instead of asking for it"))
            elif target and target != ARCHITECTURE and target not in nodes:
                out.append(("HARD", f"{label} targets {target!r}, which is neither "
                                    f"{ARCHITECTURE} nor a node"))
            if _valid(nid, req, nodes):
                proposal = str(req["proposal"]).strip()
                short = (proposal[:90] + "...") if len(proposal) > 90 else proposal
                out.append(("WARN", f"DECISION REQUESTED by {nid} for {target}, awaiting "
                                    f"H: {short}"))
        if reqs and node.get("status") == "verified":
            out.append(("HARD", f"status 'verified' with a pending decision request on "
                                f"{nid} (a node waiting on a decision is at most "
                                "'implemented')"))
    return out


def summary(nodes: dict[str, dict]) -> str:
    """One line for the validate header: requests are visible even when valid."""
    items = pending(nodes)
    if not items:
        return "none"
    return f"{len(items)} requested ({', '.join(f'{n} -> {t}' for n, t, _ in items)})"


def not_done(nodes: dict[str, dict]) -> set[str]:
    """Nodes waiting on a decision do not count as done (well-formed or not)."""
    return {nid for nid, n in nodes.items() if requests_of(n)}
