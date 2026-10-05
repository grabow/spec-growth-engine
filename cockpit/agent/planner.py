"""Planner agent (role P): natural language + examples -> SPEC.md draft.

Runs on the planner's own endpoint (SGE_PLANNER_* in cockpit/.env, an
OpenAI-compatible API) with function calling for structured output. This
authors intent, so its output is ALWAYS shown to the human for review before it
becomes truth. The key is read from the environment / .env; never hardcode it
(and never commit .env).
"""
from __future__ import annotations


import frontmatter
import yaml

from .llm import _call_tool, _client, planner_model

SPEC_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_spec",
        "description": "Emit a minimal SPEC.md draft for exactly one node.",
        "parameters": {
            "type": "object",
            "required": ["contract"],
            "properties": {
                "contract": {
                    "type": "object",
                    "properties": {
                        "provides": {"type": "array", "items": {"type": "string"}},
                        "invariants": {"type": "array", "items": {"type": "string"}},
                        "error_behavior": {"type": "array", "items": {"type": "string"}},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "design": {
                    "type": "object",
                    "properties": {
                        "approach": {"type": "string"},
                        "verification": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "How the contract is proven: one line per check. "
                            "Derive from acceptance_criteria. Mark any check needing a live "
                            "credential or network as 'runs only when <VAR> is set, skipped "
                            "otherwise'. Avoid 'word: word' colons (YAML).",
                        },
                    },
                },
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "code": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Directory-scoped, non-recursive code globs (e.g. ['*.py']) "
                    "for code-owning nodes; empty for system/container.",
                },
                "decision_requests": {
                    "type": "array",
                    "description": "A decision ABOVE this node that it needs and cannot "
                    "make: an ARCHITECTURE.md invariant, or another node's contract. It "
                    "GRANTS nothing -- it asks H, and the node waits. Use it instead of "
                    "quietly assuming the decision in this contract.",
                    "items": {
                        "type": "object",
                        "required": ["target", "proposal", "reason"],
                        "properties": {
                            "target": {"type": "string",
                                       "description": "ARCHITECTURE.md, or the id of the "
                                       "node whose contract must change"},
                            "proposal": {"type": "string",
                                         "description": "the decision, worded as it should "
                                         "appear in the target"},
                            "reason": {"type": "string", "description": "why it is needed"},
                        },
                    },
                },
                "body": {"type": "string", "description": "Short prose for below the "
                         "frontmatter: what the node is for and why it is shaped this way, "
                         "as it is NOW -- a few sentences, no revision history."},
                "change_note": {"type": "string", "description": "Revise and compact only: "
                                "which promise this revision changes, merges or drops, and "
                                "why -- for the human who clears it. It is shown with the "
                                "change set and recorded with the intent; it is NOT written "
                                "into the spec."},
            },
        },
    },
}


# Say each thing once. Specs grew to a hundred lines for a WAV loader: the same
# "opens no file, no socket, no window" five times over, ARCHITECTURE.md restated
# per node, verification a second copy of the criteria, and the prose a log of
# every revision. Every draft, revise and compact is told the same.
_CONCISE = (
    "SAY EACH THING ONCE. A promise appears in one place: `provides` what it offers, "
    "`invariants` what always holds for THIS node, `error_behavior` how it fails, "
    "`acceptance_criteria` what the tests prove. Do NOT restate ARCHITECTURE.md or the "
    "ancestors' contracts (no network, no file writes, the layout ...): they reach every "
    "node anyway. `design.verification` only for HOW a criterion is checked where that is "
    "not obvious from the criterion -- never a second copy of the criteria; [] is fine. "
    "No notes about one machine or environment (a library build, a Python version): "
    "those belong in AGENT-NOTES.md. The prose (body) says what the node is for and why "
    "it is shaped this way, as it is NOW, in a few sentences -- no revision history.\n\n"
)


def _clean_deps(deps, node_id: str, parent_id: str | None) -> list[str]:
    """Safety net: depends_on must never include self or the parent (ownership,
    not usage), and must be de-duplicated while preserving order."""
    forbidden = {node_id, parent_id}
    out: list[str] = []
    for d in deps or []:
        if d and d not in forbidden and d not in out:
            out.append(d)
    return out


def _clean_waiver(data: dict) -> None:
    """Downgrade any `waiver` the planner drafted to a REQUEST, in place.

    GOVERNANCE §8: agents may request a deviation, only H grants one. The gate
    cannot see who typed a line, so the planner enforces its half at the
    authoring end: whatever it proposes arrives as `state: requested`, with the
    owner and expiry removed -- those are the grant, and the grant is H's.
    A deviation the planner needs is thereby recorded instead of hidden.
    """
    exc = data.get("waiver")
    if exc is None:
        return
    if not isinstance(exc, dict):
        data.pop("waiver", None)
        return
    request = {"state": "requested"}
    for key in ("kind", "reason"):
        if exc.get(key):
            request[key] = exc[key]
    proposed = exc.get("proposed_expiry") or exc.get("expires")
    if proposed:
        request["proposed_expiry"] = proposed
    data["waiver"] = request


def _clean_requests(value, targets: set[str] | None) -> list[dict]:
    """The decision requests the planner may record: shape checked, target checked,
    duplicates dropped.

    A request grants nothing, so there is no authority to downgrade (unlike a
    waiver) -- but there is a trap to avoid. `engine/decisions.issues` makes a
    request whose target is neither ARCHITECTURE.md nor an existing node a HARD
    error, and a HARD error blocks the gate; since only H (or H', answering in an
    unsupervised run) deletes a request, a
    target the planner invented would wall the graph in. So an entry whose target
    is not known is dropped here, where the caller still knows the node ids and a
    retry costs one revise.
    """
    out: list[dict] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        entry = {k: str(item.get(k, "")).strip() for k in ("target", "proposal", "reason")}
        if not all(entry.values()):
            continue
        if targets is not None and entry["target"] not in targets:
            continue
        if entry not in out:
            out.append(entry)
    return out


# Fields the planner never authors. A revise must carry them through untouched:
# they record decisions -- a granted waiver, an exclusion, a declared protected
# zone -- that belong to H, or questions waiting for H (decision requests), and
# the planner rebuilding the frontmatter used to erase them silently. Run 05
# died of exactly that: `protected: true` vanished on the first revise of
# svc.cli, the change set called it "protection removed" (correctly), and the
# intent author -- which may not edit a spec by hand -- asked P to restore it,
# which P could not, because every revise dropped it again. It ended BLOCKED.
_PRESERVED_ON_REVISE = ("waiver", "excluded", "protected")
# `decision_requests` is not in that list any more: it is both PRESERVED and
# AUTHORED now (see _merge_requests), which the loop below cannot express.


def _clean_code(code, kind: str) -> list[str]:
    """Only a component carries globs; keep non-empty strings, de-duplicated.
    `**` is allowed (root-relative package globs are intentionally recursive)."""
    if kind != "component":
        return []
    out: list[str] = []
    for c in code or []:
        if isinstance(c, str) and c and c not in out:
            out.append(c)
    return out


def _no_spec(finish: str | None) -> str:
    """Why a draft/revise came back without a spec, for 'Draft unavailable: ...'."""
    return f"the model answered without a spec (finish_reason={finish!r}). Try again."


def draft_spec(
    intent: str,
    node_id: str,
    parent_id: str | None,
    kind: str,
    neighbor_contracts: dict | None = None,
    architecture: str = "",
    model: str | None = None,
    capabilities: list[dict] | None = None,
    targets: set[str] | None = None,
) -> str:
    """Return a SPEC.md draft (YAML frontmatter + prose) as an ASCII string.

    `neighbor_contracts` are the ancestors' contracts (the Spine: the owning
    container's code layout is there); `capabilities` the registry
    (engine.capability.build_registry) -- what exists, so a draft can depend on
    it instead of re-promising it.
    Raises RuntimeError when no draft can be had -- no key, the provider refuses,
    the answer is cut off or carries no spec -- with the reason, for the caller
    to show."""
    client = _client()
    prompt = (
        f"Produce a minimal SPEC.md draft for node `{node_id}` "
        f"(kind {kind}, parent {parent_id}).\n"
        f"User intent (natural language + examples):\n{intent}\n\n"
        f"ANCESTOR CONTRACTS -- the Spine, root to parent; the owning container's code "
        f"layout is here (for consistency, do NOT change them):\n"
        f"{neighbor_contracts or {}}\n\n"
        f"EXISTING CAPABILITIES (reuse: if one already provides what the intent needs, "
        f"put its node in depends_on instead of promising it again):\n"
        f"{_capability_lines(capabilities)}\n\n"
        f"ARCHITECTURE.md (global invariants, incl. the implementation language):\n"
        f"{architecture or '(none)'}\n\n"
        "EDGE-TYPE RULES (critical, do not confuse the two):\n"
        f"- `parent` ({parent_id}) is an OWNERSHIP edge ('belongs to' / 'consists "
        "of'). It is NOT a dependency.\n"
        "- `depends_on` is the USAGE edge: ONLY other nodes whose PUBLIC CONTRACT "
        "this node actually calls. It must NEVER contain the parent, any ancestor, "
        "the node itself, or any child.\n"
        "- Never infer a dependency from containment; only from real usage. "
        "A leaf that uses nothing => depends_on: []. Dependencies must be acyclic.\n\n"
        "CODE OWNERSHIP (the CODE tree is SEPARATE from the SPEC tree):\n"
        "- Decide WHERE this node's code lives from the OWNING CONTAINER's code-layout "
        "invariants (shown in the ancestor contracts / Spine above) -- language and "
        "layout are per-container, not global. Set `code` to PROJECT-ROOT-RELATIVE globs "
        "pointing INTO that code tree; code is NOT placed next to the SPEC.md.\n"
        "- Derive the glob from that container convention + this node's id (e.g. a single "
        "Maven-module container `cli` -> component `cli.hello` owns "
        "['cli/src/main/java/app/hello/**', 'cli/src/test/java/app/hello/**']). Keep owners disjoint.\n"
        "- A `component` MUST own a non-empty glob -- NEVER leave code: [] "
        "for a code-owning node (that abdicates the layout decision to the coder).\n"
        "- Only `system`/`container` (pure decomposition) may set code: [] (a container "
        "may also own just its build manifest, e.g. ['cli/pom.xml']).\n\n"
        "VERIFICATION (design.verification): the INWARD 'how to verify', distinct from "
        "the OUTWARD acceptance_criteria 'what to prove' -- a line only where HOW a "
        "criterion is checked is not obvious from it, never a copy of it. Any check that "
        "needs a live credential or network MUST be marked 'runs only when <ENV_VAR> "
        "is set, skipped otherwise' (per the ARCHITECTURE.md testing invariant: tests "
        "pass offline). Do not use 'word: word' colons inside list items (YAML). For a "
        "pure system/container with no behaviour of its own, verification may be [].\n"
        "ABOVE YOU: a decision this node needs but may not make -- an ARCHITECTURE.md "
        "invariant, or a change to another node's contract -- goes in `decision_requests` "
        "(target, proposal worded as it should appear there, reason). It grants nothing "
        "and it asks H. Record it there instead of assuming it in this contract.\n\n"
        + _CONCISE +
        "CONTENT RULES: only the contract of THIS change; derive acceptance_criteria "
        "from the examples; do not pre-specify unrelated future components; keep it "
        "lean. Call the emit_spec function."
    )
    data, finish = _call_tool(client, SPEC_TOOL, prompt, model=model)
    if not data:
        raise RuntimeError(_no_spec(finish))
    _clean_waiver(data)  # the planner may request a deviation, never grant it

    frontmatter = {
        "id": node_id,
        "parent": parent_id,
        "kind": kind,
        "contract": data.get("contract", {}),
        "design": data.get("design", {}),
        "depends_on": _clean_deps(data.get("depends_on"), node_id, parent_id),
        "code": _clean_code(data.get("code"), kind),  # always present ([] if none)
        "status": "specd",
    }
    if data.get("waiver"):
        frontmatter["waiver"] = data["waiver"]  # already downgraded to a request
    requests = _clean_requests(data.get("decision_requests"), targets)
    if requests:
        frontmatter["decision_requests"] = requests  # asks H; grants nothing
    head = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).rstrip()
    body = data.get("body", "").strip()
    return f"---\n{head}\n---\n\n{body}\n"


def _capability_lines(capabilities: list[dict] | None) -> str:
    return "\n".join(f"- {c['node']}: {c.get('provides', [])}"
                     for c in capabilities or []) or "(none)"


def _keep_omitted(revised, current) -> dict:
    """Omission is not deletion. A key the model left out of a revised mapping
    (the contract, the design) comes back from the current spec: revise promises
    to keep what the request does not touch, and a real revise dropped `purpose`
    without being asked."""
    out = dict(revised) if isinstance(revised, dict) else {}
    for key, value in (current if isinstance(current, dict) else {}).items():
        out.setdefault(key, value)
    return out


def _merge_requests(new: list[dict], current) -> list[dict]:
    """The requests a revised spec carries: every one already there, verbatim and
    first, then whatever the planner adds. A pending question is H's to resolve --
    H changes the target and deletes the entry -- so a revise may raise one and
    must never drop one."""
    out = [r for r in (current if isinstance(current, list) else []) if isinstance(r, dict)]
    return out + [r for r in new if r not in out]


def revise_spec(
    current_spec: str,
    instruction: str,
    architecture: str = "",
    model: str | None = None,
    spine: dict | None = None,
    consumers: list[str] | None = None,
    targets: set[str] | None = None,
    with_note: bool = False,
) -> str | tuple[str, str]:
    """Return a REVISED SPEC.md: the model edits the CURRENT spec per `instruction`.
    With `with_note`, (spec, note): P's word on which promise it changed and why --
    shown with the change set and recorded with the intent, never written into the
    spec, whose prose describes the node as it is now.

    Unlike draft_spec (which regenerates from scratch and resets status to 'specd'),
    revise carries the existing spec in, preserves every field not explicitly changed,
    and keeps id / parent / kind / status. The result is still human-reviewed before
    it becomes truth. Raises RuntimeError like draft_spec.
    """
    client = _client()
    try:
        fm = dict(frontmatter.loads(current_spec).metadata)
    except Exception:
        fm = {}
    node_id = fm.get("id", "")
    parent_id = fm.get("parent")
    kind = fm.get("kind", "component")
    status = fm.get("status", "specd")  # PRESERVED (not reset)

    prompt = (
        f"Revise the SPEC.md of node `{node_id}` (kind {kind}, parent {parent_id}).\n"
        "Apply ONLY the requested change. PRESERVE every field you are not explicitly "
        "changing -- code globs, depends_on, design.approach, design.verification, "
        "invariants, error_behavior, and acceptance_criteria must come back unchanged "
        "unless the change requires touching them.\n\n"
        f"CURRENT SPEC.md:\n{current_spec}\n\n"
        f"REQUESTED CHANGE:\n{instruction}\n\n"
        f"ANCESTOR CONTRACTS -- the Spine; the owning container's code layout is here "
        f"(do NOT change them):\n{spine or {}}\n\n"
        f"CONSUMERS -- nodes whose depends_on names this one and rely on its contract:\n"
        f"{', '.join(consumers or []) or '(none)'}\n\n"
        "GROWTH: prefer an ADDITIVE change -- add a new operation next to an old one "
        "rather than rewording or removing it; add a promise rather than tighten one. "
        "Write an addition as a NEW `provides` entry of its own (a new field of a "
        "returned record gets its own line, e.g. 'Text.size: ...') and leave the "
        "existing entries word for word: the engine reads contracts as text, and a "
        "reworded entry counts as removed, so it would hold a pure addition as a "
        "breaking change. "
        "If the requested change cannot be additive, make it anyway and say in "
        "`change_note` which promise changes and why: the engine holds a breaking change "
        "for a decision, and its consumers must follow. That note is NOT part of the "
        "spec: keep the prose describing the node as it is now, and drop from it any "
        "earlier note about a revision.\n\n"
        f"ARCHITECTURE.md (global invariants):\n{architecture or '(none)'}\n\n"
        "ABOVE YOU: a decision this node needs but may not make -- an ARCHITECTURE.md "
        "invariant, or a change to another node's contract -- goes in `decision_requests` "
        "(target, proposal, reason). It grants nothing and it asks H; the requests already "
        "in the spec stay as they are, they are H's to resolve.\n\n"
        "RULES: `depends_on` is USAGE only (never parent/ancestor/self/child; acyclic). "
        "`code` globs are PROJECT-ROOT-RELATIVE and point into the code tree per the "
        "owning container's code-layout invariants in the Spine (code is separate from the "
        "spec tree); a code-owning component never has code: []. Mark "
        "live-credential/network checks as 'runs only when <ENV_VAR> is set, skipped "
        "otherwise'; no 'word: word' colons in list items (YAML).\n\n"
        + _CONCISE +
        "Return the COMPLETE updated spec via emit_spec."
    )
    data, finish = _call_tool(client, SPEC_TOOL, prompt, model=model)
    if not data:
        raise RuntimeError(_no_spec(finish))
    _clean_waiver(data)  # a revise may request one; an existing grant is kept below

    # Omission is not deletion, for the head fields too: a key the model left
    # out comes back from the current spec. `code` goes one further -- an EMPTY
    # list comes back as well, asked for or not: a node that owns code never
    # has code: [] (the prompt says so), and P emptied svc.cli's four globs in
    # run 05, which orphaned five files and blocked the gate. `depends_on` is
    # the one a revise may legitimately empty, so an explicit [] stands there.
    given = data.get("depends_on")
    code = _clean_code(data.get("code"), kind)
    head_meta = {
        "id": node_id,
        "parent": parent_id,
        "kind": kind,
        "contract": _keep_omitted(data.get("contract"), fm.get("contract")),
        "design": _keep_omitted(data.get("design"), fm.get("design")),
        "depends_on": _clean_deps(given, node_id, parent_id) if given is not None
        else list(fm.get("depends_on") or []),
        "code": code or _clean_code(fm.get("code"), kind),
        "status": status,  # carried through, unlike draft
    }
    requests = _merge_requests(_clean_requests(data.get("decision_requests"), targets),
                               fm.get("decision_requests"))
    if requests:
        head_meta["decision_requests"] = requests
    # The docstring promises every field not explicitly changed survives. It did
    # not: a granted waiver and an `excluded` list vanished on every revise.
    for key in _PRESERVED_ON_REVISE:
        if key in fm:
            head_meta[key] = fm[key]           # H's decision, verbatim
        elif key == "waiver" and data.get("waiver"):
            head_meta[key] = data["waiver"]  # a new proposal, as a request
    head = yaml.safe_dump(head_meta, sort_keys=False, allow_unicode=False).rstrip()
    body = data.get("body", "").strip()
    spec = f"---\n{head}\n---\n\n{body}\n"
    return (spec, str(data.get("change_note") or "").strip()) if with_note else spec


def compact_spec(current_spec: str, architecture: str = "", spine: dict | None = None,
                 model: str | None = None) -> tuple[str, str]:
    """The same spec in fewer words: (spec, note). Every promise stays -- a contract
    key P leaves out comes back, every `provides` name should survive (lost_promises
    says which did not) -- while what is said twice, what ARCHITECTURE.md and the
    ancestors already say, verification that copies the criteria, notes about one
    machine and revision history in the prose go. id, parent, kind, status,
    depends_on, code, requests and waivers are copied, never P's to change here.
    Nothing is saved: the result is a draft for H, like any revise."""
    client = _client()
    try:
        fm = dict(frontmatter.loads(current_spec).metadata)
    except Exception:
        fm = {}
    node_id = fm.get("id", "")
    prompt = (
        f"Compact the SPEC.md of node `{node_id}`: the SAME spec in fewer words.\n\n"
        f"CURRENT SPEC.md:\n{current_spec}\n\n"
        f"ANCESTOR CONTRACTS (they reach this node anyway):\n{spine or {}}\n\n"
        f"ARCHITECTURE.md (it reaches this node anyway):\n{architecture or '(none)'}\n\n"
        "KEEP every promise: every `provides` entry's NAME -- the thing a consumer calls "
        "or reads -- and every invariant, error and acceptance criterion that says "
        "something of its own. Keep every contract key; shorten its list, never drop it. "
        "Shortening a promise is fine; changing what it promises is not.\n"
        "REMOVE: what is said twice (merge it into one entry); what ARCHITECTURE.md or "
        "the ancestors already say; design.verification lines that only restate an "
        "acceptance criterion; notes about one machine or environment; revision "
        "history in the prose.\n\n"
        + _CONCISE +
        "In `change_note`: one or two sentences on what you merged or dropped, and why. "
        "Return the COMPLETE compacted spec via emit_spec."
    )
    data, finish = _call_tool(client, SPEC_TOOL, prompt, model=model)
    if not data:
        raise RuntimeError(_no_spec(finish))
    kind = fm.get("kind", "component")
    head_meta = {
        "id": node_id, "parent": fm.get("parent"), "kind": kind,
        "contract": _keep_omitted(data.get("contract"), fm.get("contract")),
        "design": _keep_omitted(data.get("design"), fm.get("design")),
        "depends_on": list(fm.get("depends_on") or []),
        "code": list(fm.get("code") or []),
        "status": fm.get("status", "specd"),
    }
    for key in ("decision_requests", *_PRESERVED_ON_REVISE):
        if key in fm:
            head_meta[key] = fm[key]           # not P's to touch in a compaction
    head = yaml.safe_dump(head_meta, sort_keys=False, allow_unicode=False).rstrip()
    body = data.get("body", "").strip()
    return f"---\n{head}\n---\n\n{body}\n", str(data.get("change_note") or "").strip()


def lost_promises(before: str, after: str) -> list[str]:
    """The `provides` names `before` had and `after` lacks -- what a compaction
    must never do, and the one loss a long -/+ list can hide."""
    from engine import changeset
    try:
        old = frontmatter.loads(before).metadata
        new = frontmatter.loads(after).metadata
    except Exception:
        return []
    return sorted(changeset.provided_names(old) - changeset.provided_names(new))


def one_line(prompt: str, model: str | None = None) -> str:
    """One sentence from P, for a caller that wants wording rather than a spec
    (groundwork.propose). No tool call: there is no structure to emit, and a
    tool would only add a way to fail. Raises RuntimeError like the rest of this
    module when the provider refuses; the caller decides what that means."""
    import openai
    client = _client()
    try:
        resp = client.chat.completions.create(
            model=model or planner_model(),
            messages=[{"role": "user", "content": prompt}],
        )
    except openai.APIError as exc:
        raise RuntimeError(f"the provider refused: {exc}") from exc
    text = (resp.choices[0].message.content or "").strip()
    return text.splitlines()[0].strip().strip('"') if text else ""


# ---- the goal of a run (TASK.md): P proposes, H decides -----------------------------

_GOAL_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_goal",
        "description": "Propose a fuller goal (TASK.md) for the person to edit.",
        "parameters": {
            "type": "object",
            "required": ["must_do", "always", "out_of_scope"],
            "properties": {
                "must_do": {"type": "array", "items": {"type": "string"},
                            "description": "one observable behaviour per line"},
                "always": {"type": "array", "items": {"type": "string"},
                           "description": "what holds across all behaviours"},
                "out_of_scope": {"type": "array", "items": {"type": "string"},
                                 "description": "what is deliberately not wanted"},
            },
        },
    },
}

_GOAL_GUIDE = (
    "You help a person state the GOAL of a software project (its TASK.md) before an "
    "agent builds it. Another model will check the finished system against this goal, "
    "statement by statement -- a statement it cannot check is worth nothing, and a "
    "behaviour nobody wrote down will not be built, or will be built by guessing. The "
    "person gave a few words. Propose a fuller goal. They will edit it and confirm it: "
    "it stays THEIR goal.\n"
    "- must_do: one line per behaviour a user can observe -- how it is started, what "
    "the user does (commands, keys, inputs), what the system does in response, its "
    "rules, how it ends, what it refuses. Concrete and checkable: numbers, keys, names, "
    "limits.\n"
    "- always: what holds across all behaviours -- above all that it can be TESTED "
    "offline and without a screen (the logic runs apart from any user interface and "
    "can be driven step by step), determinism (randomness from a seeded generator), "
    "what persists, how errors behave.\n"
    "- out_of_scope: what a reader might expect but is not wanted, so nobody grows it.\n"
    "Rules: keep every statement the person wrote, in their words. Say WHAT, never HOW: "
    "no components, modules, classes or files -- how it is built is not the goal. Where "
    "the words leave a choice open that shapes the whole system (a terminal or a window, "
    "a file or a database), choose the simplest one consistent with the architecture "
    "and the stack below, and name it in the line, so the person sees the choice. Never "
    "contradict an invariant of ARCHITECTURE.md. Keep it to what a first version needs, "
    "not everything conceivable. Call emit_goal."
)


def propose_goal(purpose: str, must_do: str, always: str = "", out_of_scope: str = "",
                 *, architecture: str = "", stack: str = "",
                 model: str | None = None) -> dict | None:
    """P's proposal for a fuller goal: {must_do, always, out_of_scope}, each a list
    of lines -- or None for an answer without a usable proposal. Raises
    RuntimeError when P is unavailable. It proposes; the person edits and decides
    (groundwork.suggest_goal, the cockpit's goal fields)."""
    from engine.assist import _items      # a list sent as a JSON string, as GLM does
    client = _client("planner")
    prompt = (
        f"{_GOAL_GUIDE}\n\n"
        f"WHAT IT IS:\n{purpose or '(not given)'}\n\n"
        f"WHAT IT MUST DO, as the person wrote it:\n{must_do or '(nothing yet)'}\n\n"
        f"WHAT MUST ALWAYS BE TRUE, as the person wrote it:\n{always or '(nothing yet)'}\n\n"
        f"OUT OF SCOPE, as the person wrote it:\n{out_of_scope or '(nothing yet)'}\n\n"
        f"ARCHITECTURE.md (invariants that hold everywhere):\n{architecture or '(none)'}\n\n"
        f"THE STACK:\n{stack or '(not chosen)'}"
    )
    data, _ = _call_tool(client, _GOAL_TOOL, prompt, model=model or planner_model())
    if not data:
        return None
    out = {key: [str(x).strip() for x in _items(data.get(key)) if str(x).strip()]
           for key in ("must_do", "always", "out_of_scope")}
    return out if out["must_do"] else None
