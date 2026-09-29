"""Change set and consumer impact: what a proposed SPEC.md change IS, and whom it breaks.

GOVERNANCE.md makes a breaking contract change a HARD gate and an additive one
SOFT, and says the engine tells them apart "by diffing the declared
contract.provides surface; ambiguous cases default to breaking". Until this
module nothing did: D2 auto-saved a draft that removed an operation its consumer
calls, and a draft that created a new container, because the only thing between
an approved draft and the disk was a keyword scan (since replaced by the declared
protection of AUTONOMY.md 5b).

Two deterministic questions (AUTONOMY.md 5a), useful whatever the autonomy switches say:

  classify   which gate does saving this SPEC.md fall under, and why
  impact     who depends on the changed contract, which of them visibly use what
             was removed, and which evidence was recorded against the old one

The rules, in GOVERNANCE.md's terms (the strictest reason decides the gate):

  new system node / root               HARD  set root invariant
  new container                        HARD  add container
  new component or code node           SOFT  new component boundary
  node deleted                         HARD  if a node depends on it or it is a
                                             container/system -- else SOFT
  id, kind or parent changed           HARD  structure
  contract of the system root changed  HARD  root invariant
  provides: entries only added         SOFT  additive contract change
  breaking contract change             HARD  if someone can break: a declared
    (provides removed or reworded,           consumer, an OUTWARD node (container,
     invariants / error_behavior / any       system), or a node DECLARED protected
     other contract key changed)             (`protected: true`, AUTONOMY.md 5b)
                                             -- else SOFT, it is still being
                                             authored and nobody depends on it
  protection declared                  SOFT  a guard tightens
  protection removed                   HARD  a guard loosens; breaking changes
                                             could be auto-cleared again
  acceptance_criteria changed          SOFT  follows the contract; evidence goes stale
  code / excluded globs, shared        SOFT
  a waiver GRANT added or changed      HARD  only H grants
  depends_on, status changed           AUTO  the drift / lifecycle gate decides
  design, prose, a request             NONE

"Breaking" is decided on TEXT, and fails safe: whether an invariant was
tightened or widened cannot be read off a sentence, so any change to one counts
as breaking. The only additive change the engine can prove is a pure addition
to `provides`.

Kept deliberately, also for a pure ADDITION to invariants or error_behavior
(decided 2026-09-22): a new invariant may be a stronger guarantee or a new
precondition on callers, and the text does not say which. The cost is known --
a real revise that grew svc.textfile by one field still went HARD for the
invariant it added -- and the harmless cases are the reviewer's to recognise,
under the delegation, without waiting for H.

What `impact` cannot see: a consumer that uses the contract without mentioning
the removed name (reflection, a re-export, a qualified alias). A consumer is
listed whenever it DECLARES the dependency; a mention is extra evidence, its
absence is not proof of safety.
"""
from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import frontmatter

from . import evidence as code_evidence
from . import lifecycle
from . import nodes as nodeops

GATES = ("NONE", "AUTO", "SOFT", "HARD")
# every reason a breaking contract change contributes starts with this -- so a
# caller (engine.autonomy.delegable_scope) can tell "HARD because it breaks someone"
# from every other HARD reason without reading prose
BREAKING = "breaking: "
OUTWARD_KINDS = ("system", "container")
# H's declaration that a node's consumers may sit OUTSIDE the graph (a CLI, an
# API, a file format) or that it is high-stakes (auth, persistence, payment).
# A subtree property: declaring it on a container covers its descendants.
PROTECTED_FIELD = "protected"
# the contract keys with their own rule; every other key is "some other promise"
_PROVIDES, _CRITERIA = "provides", "acceptance_criteria"
_FIELD_GATES = {
    "code": "SOFT", "excluded": "SOFT", "shared": "SOFT",
    "depends_on": "AUTO", "status": "AUTO",
    "design": "NONE", "decision_requests": "NONE",
}
_HANDLED = {"id", "kind", "parent", "contract", "waiver", PROTECTED_FIELD, *_FIELD_GATES}
# what the report spells out entry by entry: every contract key, and the SOFT and
# AUTO fields. NONE fields (design, decision_requests) and the prose stay out --
# long, and they gate nothing.
_CONTRACT_ORDER = ("purpose", "provides", "invariants", "error_behavior",
                   "acceptance_criteria")
_DIFF_FIELDS = ("depends_on", "code", "excluded", "shared", "status")
# the LEADING name only: 'TextReadError: ...; str() is ...' is about TextReadError,
# and a `str(` further along is prose, not the thing provided
_LEAD = re.compile(
    r"^\s*(?:(?:export|public|static|async|def|function|fn|func|class|interface|type|"
    r"enum|const|let|val|var)\s+)*([A-Za-z_$][\w$.]*)\s*[(:]")
_ROUTE = re.compile(r"^\s*(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)", re.I)


# ---- parsing ---------------------------------------------------------------
def parse(text: str) -> dict | None:
    """A proposed SPEC.md as node metadata (with `_body`), or None if its
    frontmatter does not parse. Repair it first (specfix) -- this does not."""
    try:
        post = frontmatter.loads(text)
    except Exception:
        return None
    meta = dict(post.metadata)
    meta["_body"] = post.content
    return meta


def normalize(meta: dict) -> dict:
    """Frontmatter as compared and stored: derived `_` fields dropped, JSON-safe.
    Both sides of a comparison go through this, so a YAML date (a waiver's
    expiry) and its stored ISO string do not read as a change."""
    return json.loads(json.dumps({k: v for k, v in meta.items() if not k.startswith("_")},
                                 default=str))


def _entries(value) -> list[str]:
    """A contract list as whitespace-normalised strings. A YAML item written as
    `name: type` parses to a mapping; it is the same promise, so stringify it."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        if isinstance(item, dict):
            item = ", ".join(f"{k}: {v}" for k, v in item.items())
        text = " ".join(str(item).split())
        if text:
            out.append(text)
    return out


def _contract(meta: dict | None) -> dict:
    raw = (meta or {}).get("contract")
    if raw is None:
        return {}
    return raw if isinstance(raw, dict) else {"(contract)": raw}


def _names(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    return sorted(str(v) for v in value) if isinstance(value, list) else []


def _is_root(meta: dict) -> bool:
    return meta.get("kind") == "system" or not meta.get("parent")


def _truthy(value) -> bool:
    """Whether a declaration is switched on. `false`, `no`, empty and null are
    NOT: a field written out to say "not protected" must not read as protected,
    and YAML would hand back the string `'false'` for an unquoted one."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "none", "null", "0")
    return bool(value)


def _protected_above(nodes: dict[str, dict], start) -> bool:
    """True if `start` or any ancestor declares `protected`, walking `parent` in
    the graph given (the BEFORE graph: a marking removed in the same edit still
    counts, fail safe). The marking is a SUBTREE property (AUTONOMY.md 5b)."""
    seen: set[str] = set()
    current = start
    while isinstance(current, str) and current and current not in seen:
        seen.add(current)
        meta = nodes.get(current)
        if not isinstance(meta, dict):
            break
        if _truthy(meta.get(PROTECTED_FIELD)):
            return True
        current = meta.get("parent")
    return False


# ---- classify --------------------------------------------------------------
def classify(nodes: dict[str, dict], node_id: str, new: dict | None) -> dict:
    """Which gate saving `new` as `node_id`'s SPEC.md falls under; `new=None` is
    the node's deletion. `nodes` is the graph BEFORE the change: the node's old
    spec, and who depends on it, are read from there.

    Returns {node, kind, new_node, deleted, gate, breaking, protected, consumers,
             reasons: [(gate, why)], provides: {added, removed},
             criteria: {added, removed}, diff: {key: {removed, added}}}. `kind`
             is the node's kind before the change (after it, for a new node);
             `diff` is empty for a new or deleted node."""
    raw = nodes.get(node_id)
    reasons: list[tuple[str, str]] = []
    # a subtree property: the node itself, or any ancestor, may declare it
    is_protected = (_truthy((raw or {}).get(PROTECTED_FIELD))
                    or _protected_above(nodes, (raw or {}).get("parent")))
    change = {
        "node": node_id, "kind": (raw or new or {}).get("kind"),
        "new_node": raw is None, "deleted": new is None,
        "breaking": False, "reasons": reasons, "protected": is_protected,
        "consumers": nodeops.dependents_of(nodes, node_id) if raw is not None else [],
        "provides": {"added": [], "removed": []},
        "criteria": {"added": [], "removed": []},
        "diff": {},
    }
    if new is None:
        return _finish(_deletion(raw, change)) if raw is not None else _finish(change)
    # prose is compared only where both sides carry it (a stored state does not)
    prose_changed = ("_body" in (raw or {}) and "_body" in new
                     and raw["_body"].strip() != new["_body"].strip())
    old = normalize(raw) if raw is not None else None
    new = normalize(new)
    # a new node is not in `nodes` yet: its declaration, or its parent's subtree,
    # is what counts
    change["protected"] = (change["protected"] or _truthy(new.get(PROTECTED_FIELD))
                           or _protected_above(nodes, new.get("parent")))

    new_id = new.get("id")
    if not new_id:
        reasons.append(("HARD", "the proposed SPEC.md has no id"))
    elif new_id != node_id:
        reasons.append(("HARD", f"id changed: {node_id} -> {new_id} (a rename moves every edge)"))

    if old is None:
        kind = new.get("kind")
        if _is_root(new):
            reasons.append(("HARD", "new system root (sets root invariants)"))
        elif kind == "container":
            reasons.append(("HARD", "new container"))
        elif kind in ("component", "code"):
            reasons.append(("SOFT", f"new {kind} boundary under {new.get('parent')}"))
        else:
            reasons.append(("HARD", f"new node of unknown kind {kind!r} (cannot classify, "
                                    "fail safe)"))
        _waiver(None, new, reasons)
        change["purpose"] = str(_contract(new).get("purpose") or "").strip()
        change["provides"]["added"] = _entries(_contract(new).get(_PROVIDES))
        change["criteria"]["added"] = _entries(_contract(new).get(_CRITERIA))
        return _finish(change)

    change["purpose"] = str(_contract(new).get("purpose") or "").strip()
    for key in ("kind", "parent"):
        if old.get(key) != new.get(key):
            reasons.append(("HARD", f"{key} changed: {old.get(key)} -> {new.get(key)}"))

    was, now = _truthy(old.get(PROTECTED_FIELD)), _truthy(new.get(PROTECTED_FIELD))
    if was != now:
        reasons.append(("SOFT", "declared protected (breaking changes here now need H)")
                       if now else
                       ("HARD", "protection removed (a breaking change here could be "
                                "auto-cleared again)"))

    _contract_diff(old, new, change)
    _waiver(old, new, reasons)

    for key, gate in _FIELD_GATES.items():
        before, after = old.get(key), new.get(key)
        if key == "depends_on":
            before, after = _names(before), _names(after)
        if before != after and not (before in (None, [], {}) and after in (None, [], {})):
            reasons.append((gate, f"{key} changed" + _why(key)))
    for key in sorted(set(old) | set(new)):
        if key.startswith("_") or key in _HANDLED:
            continue
        if old.get(key) != new.get(key):
            reasons.append(("SOFT", f"field {key!r} changed (unclassified field)"))
    if prose_changed:
        reasons.append(("NONE", "prose changed"))
    change["diff"] = _diff(old, new, change)
    return _finish(change)


def _diff(old: dict, new: dict, change: dict) -> dict[str, dict]:
    """{key: {gate, removed, added}} for every contract key and every SOFT or AUTO
    field that moved. The reasons say THAT something changed and which gate that
    means; H, asked to clear it, has to see WHAT changed -- a reworded entry is
    one removed and one added -- and which part of it is the reason for the gate:
    each key carries the gate its own change falls under, by the same rules the
    reasons follow."""
    broken = change.get("breaking_gate", "SOFT")

    def gate_of(key: str, removed: list) -> str:
        if key in _DIFF_FIELDS:
            return _FIELD_GATES[key]
        if _is_root(old):
            return "HARD"                     # the root's contract reaches every spine
        if key == _PROVIDES:
            return broken if removed else "SOFT"
        if key == _CRITERIA:
            return "SOFT"
        return broken                         # any other key changed: breaking, fail safe

    before, after = _contract(old), _contract(new)
    keys = [k for k in _CONTRACT_ORDER if k in before or k in after]
    keys += sorted((set(before) | set(after)) - set(keys))
    pairs = [(k, _entries(before.get(k)), _entries(after.get(k))) for k in keys]
    pairs += [(k, _entries(old.get(k)), _entries(new.get(k))) for k in _DIFF_FIELDS]
    out = {}
    for key, was, now in pairs:
        removed, added = [e for e in was if e not in now], [e for e in now if e not in was]
        if removed or added:
            out[key] = {"gate": gate_of(key, removed), "removed": removed, "added": added}
    return out


def _deletion(old: dict, change: dict) -> dict:
    kind, consumers = old.get("kind"), change["consumers"]
    change["breaking"] = True
    change["provides"]["removed"] = _entries(_contract(old).get(_PROVIDES))
    if consumers:
        change["reasons"].append(("HARD", "node deleted -- consumed by " + ", ".join(consumers)))
    elif kind in OUTWARD_KINDS or _is_root(old):
        change["reasons"].append(("HARD", f"a {kind or 'root'} deleted"))
    elif change["protected"]:
        change["reasons"].append(("HARD", "a protected node is deleted (its consumers may "
                                         "sit outside the graph)"))
    else:
        change["reasons"].append(("SOFT", "node deleted -- no node depends on it"))
    return change


def _why(key: str) -> str:
    return {"depends_on": " (the drift gate checks it against the imports)",
            "status": " (the lifecycle gate checks it against the evidence)"}.get(key, "")


def _contract_diff(old: dict, new: dict, change: dict) -> None:
    reasons = change["reasons"]
    before, after = _contract(old), _contract(new)
    if before == after:
        return
    if _is_root(old):
        reasons.append(("HARD", "the system root's contract changed (root invariants reach "
                                "every spine)"))

    breaking: list[str] = []
    old_p, new_p = _entries(before.get(_PROVIDES)), _entries(after.get(_PROVIDES))
    change["provides"] = {"added": [p for p in new_p if p not in old_p],
                          "removed": [p for p in old_p if p not in new_p]}
    breaking += [f"provides removed or reworded: {p}" for p in change["provides"]["removed"]]
    if change["provides"]["added"]:
        # the entries themselves are in the report's diff
        reasons.append(("SOFT", f"provides added ({len(change['provides']['added'])})"))

    old_c, new_c = _entries(before.get(_CRITERIA)), _entries(after.get(_CRITERIA))
    change["criteria"] = {"added": [c for c in new_c if c not in old_c],
                          "removed": [c for c in old_c if c not in new_c]}
    if change["criteria"]["added"] or change["criteria"]["removed"]:
        reasons.append(("SOFT", "acceptance_criteria changed (test evidence for the old "
                                "criteria no longer proves the new ones)"))

    for key in sorted((set(before) | set(after)) - {_PROVIDES, _CRITERIA}):
        if sorted(_entries(before.get(key))) != sorted(_entries(after.get(key))):
            # tightened or widened cannot be read off the text: fail safe
            breaking.append(f"{key} changed")
    if not breaking:
        return

    change["breaking"] = True
    consumers = change["consumers"]
    kind = old.get("kind")
    if consumers:
        gate, who = "HARD", "consumed by " + ", ".join(consumers)
    elif kind in OUTWARD_KINDS:
        gate, who = "HARD", f"a {kind}'s consumers may sit outside the graph"
    elif change["protected"]:
        gate, who = "HARD", "declared protected (a boundary that reaches outside)"
    else:
        gate, who = "SOFT", "no node depends on it yet"
        # visibility, not a gate: the rule that keeps this SOFT cannot see a
        # consumer outside the graph. Say so, or the hole is silent (run 03).
        reasons.append(("NONE", "nothing depends on it and it is not declared protected: "
                                "if its consumers sit outside the graph, add "
                                f"`{PROTECTED_FIELD}: true`"))
    change["breaking_gate"] = gate      # what the diff marks a breaking key with
    for what in breaking:
        reasons.append((gate, f"{BREAKING}{what} -- {who}"))


def _waiver(old: dict | None, new: dict, reasons: list) -> None:
    before, after = (old or {}).get("waiver"), new.get("waiver")
    if before == after or not isinstance(after, dict):
        return
    if after.get("state") == "granted":
        reasons.append(("HARD", "a waiver grant was added or changed (only H grants)"))
    else:
        reasons.append(("NONE", "a waiver was requested (a request grants nothing)"))


def _finish(change: dict) -> dict:
    change["gate"] = max((g for g, _ in change["reasons"]), key=GATES.index, default="NONE")
    return change


# ---- impact ----------------------------------------------------------------
def handle(entry: str) -> str | None:
    """The name a consumer would write to use a `provides` entry: `createOrder`
    from 'createOrder(cart): Order', `/search` from 'GET /search', `Order` from
    'Order: type', `read_text` from 'svc.io.read_text(p)' (the last segment is
    what an import brings into scope). None for a prose promise -- nothing to
    look for."""
    m = _ROUTE.match(entry)
    if m:
        return m.group(1).split("?")[0]
    m = _LEAD.match(entry)
    return m.group(1).rsplit(".", 1)[-1] if m else None


def provided_names(meta: dict | None) -> set[str]:
    """The handles of everything `meta` provides NOW. A reworded entry that keeps
    its name -- `read_text(path) -> str` becoming `read_text(path) -> Text` --
    is still provided under that name; only a name missing from this set is gone."""
    return {h for h in (handle(e) for e in _entries(_contract(meta).get(_PROVIDES))) if h}


def impact(nodes: dict[str, dict], project_root: str | Path, change: dict) -> dict:
    """Who a change reaches, looked up in the CURRENT graph `nodes`. The
    consumers are the ones `classify` counted (its before-graph). Returns
    {consumers: [{node, status, mentions: [(handle, file)]}], unchecked:
    [removed entries with no handle], stale: [str]}."""
    nid = change["node"]
    root = Path(project_root)
    removed = change["provides"]["removed"]
    handles = {e: handle(e) for e in removed}
    out: dict = {"consumers": [], "unchecked": [e for e, h in handles.items() if not h],
                 "stale": []}
    if change["new_node"]:
        return out

    for consumer in change["consumers"]:
        node = nodes.get(consumer)
        if node is None:
            continue
        mentions: list[tuple[str, str]] = []
        files = [node["_path"], *code_evidence.resolve_node_files(node, root)] \
            if node.get("_path") else code_evidence.resolve_node_files(node, root)
        for name in sorted({h for h in handles.values() if h}):
            pattern = re.compile(re.escape(name) if name.startswith("/")
                                 else rf"(?<![\w$]){re.escape(name)}(?![\w$])")
            for f in files:
                if pattern.search(_read(f)):
                    mentions.append((name, _rel(f, root)))
        out["consumers"].append({"node": consumer, "status": node.get("status"),
                                 "mentions": mentions})

    contract_moved = change["breaking"] or any(change["criteria"].values())
    record = lifecycle.load_evidence(root).get(nid)
    if contract_moved and record:
        out["stale"].append(f"{nid}: test evidence ({record.get('status')}, "
                            f"{record.get('at')}) was recorded against the old contract")
    if contract_moved and nodes.get(nid, {}).get("status") == "verified":
        out["stale"].append(f"{nid} is 'verified' against the old contract")
    if change["breaking"]:
        for c in out["consumers"]:
            if c["status"] in ("implemented", "verified"):
                out["stale"].append(f"{c['node']} is '{c['status']}' against the old contract")
    return out


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(path: str, root: Path) -> str:
    p = Path(path).resolve()
    return str(p.relative_to(root.resolve())) if p.is_relative_to(root.resolve()) else str(p)


# ---- report ----------------------------------------------------------------
def summary(change: dict) -> str:
    """One line: 'change set util: HARD (breaking; 1 consumer)'."""
    notes = []
    if change["new_node"]:
        notes.append("new node")
    if change.get("deleted"):
        notes.append("deleted")
    if change["breaking"]:
        notes.append("breaking")
    return f"change set {change['node']}: {change['gate']}" + (
        f" ({', '.join(notes)})" if notes else "")


_PROVIDES_SHOWN = 8       # a new node's promises, in full up to here
_DIFF_SHOWN = 8           # a changed key's entries, in full up to here


def report(change: dict, reach: dict | None = None) -> str:
    """Plain-ASCII change set: the gate, every reason, and the impact."""
    lines = [summary(change)]
    order = sorted(change["reasons"], key=lambda r: -GATES.index(r[0]))
    lines += [f"  [{gate}] {why}" for gate, why in order] or ["  (no change)"]
    if change.get("purpose"):
        lines.append(f"purpose: {change['purpose']}")
    if change.get("diff"):
        lines.append("what changed (- before, + after; each part under its gate -- "
                     "the change takes the highest):")
        parts = sorted(change["diff"].items(), key=lambda kv: -GATES.index(kv[1]["gate"]))
        for key, moved in parts:
            lines.append(f"  [{moved['gate']}] {key}")
            entries = ([("-", e) for e in moved["removed"]]
                       + [("+", e) for e in moved["added"]])
            for sign, entry in entries[:_DIFF_SHOWN]:
                lines.append(textwrap.fill(entry, width=100, initial_indent=f"    {sign} ",
                                           subsequent_indent="      "))
            if len(entries) > _DIFF_SHOWN:
                lines.append(f"    ... and {len(entries) - _DIFF_SHOWN} more "
                             f"(the spec of {change['node']} has them all)")
    if change["new_node"]:
        # A new node has no "before" to diff against, so the reasons alone said
        # only THAT something arrived ("new container") -- never what it promises.
        # H decides a boundary by reading it, so the boundary goes in the report.
        promises = change["provides"]["added"]
        lines.append(f"it would provide ({len(promises)}):" if promises
                     else "it provides nothing yet (a boundary with no promise)")
        lines += [f"  - {p}" for p in promises[:_PROVIDES_SHOWN]]
        if len(promises) > _PROVIDES_SHOWN:
            lines.append(f"  ... and {len(promises) - _PROVIDES_SHOWN} more "
                         f"(the spec of {change['node']} has them all)")
    if change.get("protected"):
        lines.append(f"declared protected: a BREAKING change to {change['node']} "
                     "(or anything in its subtree) is H's. Additions, a status or "
                     "prose still clear as usual -- the zone raises the gate for what "
                     "breaks, it does not freeze the node")
    if reach is None:
        return "\n".join(lines)
    if change["breaking"] and not reach["consumers"]:
        lines.append(f"consumers (depends_on {change['node']}): none declared")
    if reach["consumers"]:
        lines.append(f"consumers (depends_on {change['node']}):")
        for c in reach["consumers"]:
            where = "; ".join(f"`{h}` in {f}" for h, f in c["mentions"])
            lines.append(f"  {c['node']} ({c['status'] or 'no status'})"
                         + (f"  mentions {where}" if where
                            else ("  -- no mention of what was removed found"
                                  if change["provides"]["removed"] else "")))
    if reach["unchecked"]:
        lines.append("removed entries with no name to search for (prose promise):")
        lines += [f"  {e}" for e in reach["unchecked"]]
    if reach["stale"]:
        lines.append("evidence recorded against the old contract:")
        lines += [f"  {s}" for s in reach["stale"]]
    return "\n".join(lines)


def assess(nodes: dict[str, dict], project_root: str | Path, node_id: str,
           text: str, before: dict[str, dict] | None = None) -> tuple[dict, dict] | None:
    """classify + impact for a proposed SPEC.md text; None if it does not parse.
    `before` is the graph to measure against -- the accepted state when one is
    tracked (engine.accepted) -- and defaults to the current graph."""
    new = parse(text)
    if new is None:
        return None
    change = classify(nodes if before is None else before, node_id, new)
    return change, impact(nodes, project_root, change)
