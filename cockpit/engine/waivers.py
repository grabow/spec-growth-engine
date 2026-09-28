"""The waiver model: typed, owned, time-boxed deviations (GOVERNANCE.md §8).

A waiver is how a node may deviate from the rules WITHOUT the deviation
becoming permanent. It is the guard against `PENDING-EXTERNAL-EVIDENCE` rot: a
marker that carries an owner and a deadline, and that the gate keeps raising
until someone acts.

Called a WAIVER, not an "exception": that word collides with programming
exceptions, and in the case that motivated this model the collision was total --
ARCHITECTURE.md said "errors are raised as exceptions", svc.gui.choose
deliberately raises none, and so a deviation that meant "this code raises no
exception" needed "an exception". A waiver is the established engineering term
for a formal, time-boxed permission to deviate from a requirement.

Requesting and granting are separate acts, by separate parties:

    waiver:
      state: requested          # anyone -- including an agent -- may write this
      kind: known-gap
      reason: <why the deviation is needed>
      proposed_expiry: <YYYY-MM-DD>       (optional)

    waiver:
      state: granted            # only H: the grant is the acceptance of the risk
      kind: pending-external-evidence | known-gap | deferred-test | frontier-stub
      owner: <who>
      expires: <YYYY-MM-DD>
      reason: <text>

Why the split: when only H could WRITE a waiver, an agent that had to deviate
deviated anyway and described it in prose -- no owner, no expiry, invisible to
the gate (run 02, svc.gui). The rule stopped the deviation from being RECORDED,
not from happening. A request records it; a grant accepts it.

What is enforced here:

    state        must be `requested` or `granted`, never implied    -> HARD
    typed        `kind` must be one of the four (both states)       -> HARD
    requested    must give a reason; is reported on every run       -> WARN
    granted      owner, and a parseable expiry                      -> HARD
    expired      a granted waiver past its date                  -> HARD
    expiring     within EXPIRY_WARN_DAYS                            -> WARN
    not done     `verified` with any unresolved waiver           -> HARD
    frontier     a frontier-stub may not be implemented/verified    -> HARD

NOT enforced here: that a GRANT came from H. Authorship is not a property of the
file. The planner downgrades anything it drafts to `requested`
(agent/planner._clean_waiver), so for the planner the rule holds; for an
agent editing YAML directly it is a rule of the manual, not of the gate.
"""
from __future__ import annotations

import datetime as _dt
from typing import Iterable

TYPES = ("pending-external-evidence", "known-gap", "deferred-test", "frontier-stub")
STATES = ("requested", "granted")
# The field's former name. Nothing reads it, so `issues` reports it -- otherwise
# the rename would turn every existing grant, expired or not, into a silent pass.
LEGACY_FIELD = "exception"
EXPIRY_WARN_DAYS = 14
# a frontier stub is a deliberate FAKE; it may never present itself as built
_FRONTIER_FORBIDDEN = ("implemented", "verified")


def of(node: dict) -> dict | None:
    """The node's waiver block, or None. A non-mapping value is not an
    waiver -- it is reported as malformed by `issues`, not silently ignored."""
    exc = node.get("waiver")
    return exc if isinstance(exc, dict) else None


def state_of(exc: dict) -> str | None:
    """`requested` or `granted`; None when absent or unknown. Deliberately no
    default: reading a missing state as `granted` would make the permissive value
    the one you get by saying nothing."""
    state = exc.get("state")
    return state if state in STATES else None


def expiry(exc: dict, key: str = "expires") -> _dt.date | None:
    """Parse a date field. PyYAML already turns an unquoted 2026-01-31 into a
    date, so accept both that and a string."""
    raw = exc.get(key)
    if isinstance(raw, _dt.datetime):
        return raw.date()
    if isinstance(raw, _dt.date):
        return raw
    if isinstance(raw, str):
        try:
            return _dt.date.fromisoformat(raw.strip())
        except ValueError:
            return None
    return None


def is_expired(exc: dict, today: _dt.date | None = None) -> bool:
    """True only for a well-formed GRANTED waiver whose date has passed. An
    unparseable date is malformed, not expired; a request has no expiry."""
    if state_of(exc) != "granted":
        return False
    due = expiry(exc)
    return due is not None and due < (today or _dt.date.today())


def open_waivers(nodes: dict[str, dict],
                    today: _dt.date | None = None) -> dict[str, dict]:
    """node id -> its waiver, for GRANTED waivers that have not expired.
    "Open" means in force: a deviation H has accepted and that still holds."""
    today = today or _dt.date.today()
    return {nid: exc for nid, n in nodes.items()
            if (exc := of(n)) is not None and state_of(exc) == "granted"
            and not is_expired(exc, today)}


def requested_waivers(nodes: dict[str, dict]) -> dict[str, dict]:
    """node id -> its waiver, for requests awaiting a decision by H."""
    return {nid: exc for nid, n in nodes.items()
            if (exc := of(n)) is not None and state_of(exc) == "requested"}


def issues(nodes: dict[str, dict],
           today: _dt.date | None = None) -> list[tuple[str, str]]:
    """[(severity, message)] for every waiver problem. severity: HARD | WARN."""
    today = today or _dt.date.today()
    out: list[tuple[str, str]] = []
    for nid in sorted(nodes):
        node = nodes[nid]
        if LEGACY_FIELD in node:
            # Renaming a field must not make its old spelling silently inert: an
            # expired grant under the old name would pass the gate unseen.
            out.append(("HARD", f"{nid} still uses the field `{LEGACY_FIELD}:`, which was "
                                "renamed to `waiver:` (it collided with programming "
                                "exceptions). Rename the key; nothing reads the old one."))
        raw = node.get("waiver")
        if raw is None:
            continue
        if not isinstance(raw, dict):
            out.append(("HARD", f"malformed waiver on {nid}: expected a mapping "
                                f"with state/kind/reason, got {type(raw).__name__}"))
            continue

        state = state_of(raw)
        kind = raw.get("kind")
        if state is None:
            out.append(("HARD", f"waiver on {nid} has no valid state "
                                f"({raw.get('state')!r}): write `state: requested` to ask "
                                "for a deviation; only H writes `state: granted`"))
        if kind not in TYPES:
            out.append(("HARD", f"waiver on {nid} has unknown kind "
                                f"{kind!r} (expected one of: {', '.join(TYPES)})"))

        if state == "requested":
            reason = str(raw.get("reason") or "").strip()
            if not reason:
                out.append(("HARD", f"waiver requested on {nid} gives no reason "
                                    "(a request has to say why the deviation is needed)"))
            if raw.get("proposed_expiry") is not None and expiry(raw, "proposed_expiry") is None:
                out.append(("HARD", f"waiver requested on {nid} has an unparseable "
                                    f"proposed_expiry {raw.get('proposed_expiry')!r} "
                                    "(expected YYYY-MM-DD)"))
            short = (reason[:90] + "...") if len(reason) > 90 else reason
            out.append(("WARN", f"waiver REQUESTED on {nid} ({kind}), awaiting a "
                                f"decision by H: {short}"))

        if state == "granted":
            if not raw.get("owner"):
                out.append(("HARD", f"waiver on {nid} has no owner "
                                    "(a granted waiver must be owned by a person)"))
            due = expiry(raw)
            if raw.get("expires") is None:
                out.append(("HARD", f"waiver on {nid} has no expiry "
                                    "(a granted waiver must be time-boxed)"))
            elif due is None:
                out.append(("HARD", f"waiver on {nid} has an unparseable expiry "
                                    f"{raw.get('expires')!r} (expected YYYY-MM-DD)"))
            elif due < today:
                out.append(("HARD", f"waiver on {nid} EXPIRED {due.isoformat()} "
                                    f"({(today - due).days} days ago): renew it, or "
                                    "resolve what it was covering"))
            elif (due - today).days <= EXPIRY_WARN_DAYS:
                out.append(("WARN", f"waiver on {nid} expires {due.isoformat()} "
                                    f"(in {(due - today).days} days)"))

        status = node.get("status")
        if status == "verified":
            what = "a requested" if state == "requested" else "an open"
            out.append(("HARD", f"status 'verified' with {what} waiver on {nid} "
                                "(a node with a waiver is at most 'implemented')"))
        if kind == "frontier-stub" and status in _FRONTIER_FORBIDDEN:
            out.append(("HARD", f"frontier-stub waiver on {nid} but status is "
                                f"'{status}': a deliberate fake may not present "
                                "itself as built"))
    return out


def summary(nodes: dict[str, dict], today: _dt.date | None = None) -> str:
    """One line for the validate report header, so waivers are visible even
    when nothing is wrong with them -- granted ones AND requests awaiting H."""
    today = today or _dt.date.today()
    opened = open_waivers(nodes, today)
    requested = requested_waivers(nodes)
    parts = []
    if opened:
        soonest = min((d for exc in opened.values() if (d := expiry(exc))), default=None)
        tail = f", next expiry {soonest.isoformat()}" if soonest else ""
        parts.append(f"{len(opened)} open ({', '.join(sorted(opened))}){tail}")
    if requested:
        parts.append(f"{len(requested)} requested ({', '.join(sorted(requested))})")
    return "; ".join(parts) if parts else "none"


def not_done(nodes: dict[str, dict], today: _dt.date | None = None) -> set[str]:
    """Nodes that must NOT be counted as done (GOVERNANCE §8): any unresolved
    waiver -- granted, requested, or malformed -- disqualifies a node. Only an
    EXPIRED grant drops out, because it blocks the gate instead."""
    today = today or _dt.date.today()
    out = set()
    for nid, n in nodes.items():
        raw = n.get("waiver")
        if raw is None:
            continue
        if isinstance(raw, dict) and is_expired(raw, today):
            continue
        out.add(nid)
    return out
