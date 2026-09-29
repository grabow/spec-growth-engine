# Governance and Responsibility Matrix

> Part of the **Spec Growth Engine** method. This document defines **who may
> create or change what**, and **when a human gate is required**, across the
> spec graph. It is the governance half of the method: the growth rules say
> *how* the graph changes, this document says *who is allowed to change it and
> under which control*.

---

> ## ⚑ Core invariant — NO SILENT DRIFT
>
> Spec and code may **never diverge silently**. The drift validator + acceptance
> tests are a **blocking merge gate**: a commit where code and its spec disagree
> (or where acceptance criteria lack test evidence) **does not land** — "it works"
> is not sufficient to merge. Keeping them in sync is **not left to discipline**:
> the AI updates the affected spec in the *same* commit, and the human approves
> only the contract lines. This is the single property the whole engine exists to
> guarantee; everything below serves it. (Mechanics: §9.)

---

## 0. Why this exists

A spec graph driven by agents fails in two predictable ways:

1. **Drift into bureaucracy** — an agent invents boundaries and contracts with
   no review, producing inconsistent granularity and an explosion of meaningless
   spec/doc artifacts.
2. **Fake completion** — work is marked "done" while real gaps are hidden behind
   open-ended waivers (the classic `PENDING-EXTERNAL-EVIDENCE` rot).
3. **Silent drift** — code is changed directly, the spec is not updated, the
   program still works, so the change ships and spec and code diverge unnoticed.
   This is the most common and most corrosive failure.

This document prevents all three: by assigning, for every kind of change, a clear
**author**, **gate**, and **deriving authority**; by making completion impossible
while a waiver is open; and by making divergence un-mergeable (the core
invariant above, enforced in §9).

## 1. Roles

> Canonical definitions: [SPEC-GROWTH-ENGINE.md §3.1](SPEC-GROWTH-ENGINE.md).

Three questions, one table: what a role does, **who plays it** -- a person, a
model, or code -- and where that is set. A role is a job, not a person and not a
model: the same job is done by H at a keyboard or by an agent, and which model
holds a job is a choice you make in one file.

```text
role                what it does                      played by           in .env
------------------  --------------------------------  ------------------  --------------
H  Human architect  the goal; the boundaries, public  a PERSON, always.   --
                    contracts and root invariants;    No model stands in
                    the zones and the switches;       for H; H'
                    grants waivers; decides what is   deputises by
                    above I                           degree only
I  Intent author    a goal -> a decomposition and,    H typing in the     SGE_INTENT_*
                    per node, an intent: what it is   cockpit; in a run   (a run only)
                    for, what it must do, with        a codex exec agent
                    examples -- and HOW the graph
                    grows to meet the goal:
                    iteratively over slices,
                    decomposed as far as it is
                    KNOWN, what is guessed left
                    to the slice that needs it
                    (LIFECYCLE 6).
                    Writes NO spec and NO code -- it
                    asks P and C (cli.py draft |
                    revise | code)
P  Planner          an intent -> a SPEC.md:           a chat call         SGE_PLANNER_*
                    contracts, criteria, design; a
                    decomposition when asked
H' Reviewer,        judges what E cannot --           a chat call, NEVER  SGE_REVIEWER_*
   H's deputy       altitude, placement,              a person -- H is    (unset fields:
                    testability, reuse, intent        the person          P's)
                    fidelity: reviews P's drafts
                    (D1/D2), briefs a HARD change
                    (5c), accepts the ones H
                    delegated (delegation on),
                    checks a run's goal; in an
                    unsupervised run answers
                    decision requests in H's
                    place (§6). Authors no other
                    intent
C  Coder            implements ONE node inside its    a codex exec agent  SGE_CODER_*
                    context bundle; maintains its
                    design, declares its observed
                    deps
E  Engine           derives, validates, enforces the  CODE. It calls no   -- (and holds
                    gates, records; decides the       model, ever         no key)
                    rounds of a run. Authors NO
                    intent
```

**One endpoint per role.** Which model, at which provider, plays a role is a
choice, not a coincidence. Each model-backed role has its own OpenAI-compatible
endpoint -- URL, key, model -- in `cockpit/.env` (`cockpit/agent/llm.py`,
`cockpit/.env.example`):

```text
SGE_<ROLE>_BASE_URL    the provider's OpenAI-compatible URL
SGE_<ROLE>_API_KEY     the key
SGE_<ROLE>_MODEL       the model id at that provider
SGE_<ROLE>_REASONING_EFFORT
                       optional: how hard the model thinks (e.g. low | medium |
                       high), passed as written; unset, the provider's default
SGE_<ROLE>_HARNESS     I and C only: the agent CLI that runs them -- codex-cli,
                       the Codex CLI (github.com/openai/codex), required for both
<ROLE> = PLANNER | REVIEWER | INTENT | CODER

unset:  nothing falls back -- not to another role, not to a provider, not
        to the user's own ~/.codex/config.toml (I and C run with
        --ignore-user-config). A role without its three settings is not
        configured, and says which it lacks. Two roles on the same model
        repeat the same values.
wins:   a value already in the environment, so one run can override a role:
        SGE_CODER_MODEL=... uv run python cli.py run ROOT
```

A key is passed only to the process that needs it and never appears in a command
or a log -- for a codex agent only the NAME of the variable holding it is in the
command line. I and C run as `codex exec` (open source), so all four model-backed
roles speak the same kind of API.

Who plays what RIGHT NOW is a question for the tool, not for this document:

```sh
uv run python cockpit/role_agent.py --describe
```

It prints, per role, the runner, the model, the endpoint and where the key came
from -- never the key. A run records the same lines in
`<root>/.sge/runs/NN.roles`, next to the engine's commit.

P and H' may be the same model; then H' reviews what its own model wrote, and
the cockpit says so. Separating I, P and C is what makes the models separable at
all: an agent that writes intent, specs and code itself has one model for all
three -- which is what runs 01-04 were.

## 1a. Autonomy switches (who clears the SOFT/HARD gates)

> Canonical switches and prerequisites: [AUTONOMY.md](AUTONOMY.md).

```text
the draft gate   D0 Assist  ->  D1 LLM-review  ->  D2 LLM-clear   (a grade)
the delegation   off | on: may H' accept a pending HARD change?    (a switch)
the run          off | on | unsupervised: is the intent author an    (an operating mode)
                 agent -- and, while it runs, does H' answer for H?

The switches say WHO may clear a gate; the gate level (§3) says how much is at
stake. They are independent.

INVARIANT whatever the switches say: the DETERMINISTIC floor (validate/drift/lifecycle) always
runs and BLOCKS -- H' judges what E cannot, it never overrides E. Every H' decision
is logged for async audit (.sge/autonomy.jsonl).

Implemented today: all three -- D0-D2, the delegation, and the run as an operating
mode (an orchestrated run, where the intent author I is an agent; AUTONOMY.md §3).
D0-D2 (draft SOFT gate; D2 clears only what the change set,
engine/changeset.py, classifies as SOFT or below). Headless, the gate measures
changes against an accepted state: E accepts SOFT on a pass, HARD stays pending
for H (engine/accepted.py), prepared by H' and decided by H (engine/assist.py,
AUTONOMY 5c). The delegation is built: where H switches it on for a project, H'
may accept a breaking change to a consumed component contract once E finds it
migrated (`cli.py decide`); zones stay with H, and H can overrule every
acceptance. The run is built as an operating mode, not a value anyone sets: the intent
author is an agent, and the run goes in rounds -- E checks the floor, H' the
goal against TASK.md, and the agent is resumed with what is missing
(cockpit/orchestrate.py, engine/iteration.py). Unsupervised, H' also answers
the decision requests between rounds, in H's place, and decides what the
delegation lets it; every answer is an ADR that waits for H's review
(engine/unsupervised.py). It needs the delegation on.
```

## 2. Governing principle

```text
Authority follows blast radius and reversibility.

Outward surface (root invariants, structure, public contract)
   -> high blast radius, low reversibility  -> GATED
Inward surface (internal design, owned code)
   -> local, reversible                     -> AUTONOMOUS
```

This is the contract/design visibility rule (Parnas information hiding)
re-expressed as decision rights: the same boundary that hides design from
neighbors also separates "needs review" from "do it yourself".

## 3. Gate levels

> Canonical definitions: [SPEC-GROWTH-ENGINE.md §3.9](SPEC-GROWTH-ENGINE.md).

```text
HARD   Human approval required before merge.
       (root invariant, new container, breaking contract change)
SOFT   Agent may proceed; human review requested async.
       Auto-approved if all policy checks pass; reversible if rejected.
       (new component boundary, additive contract change)
AUTO   No human. Engine policy decides.
       (depends_on must match evidence, else blocked)
NONE   Fully autonomous.
       (internal design, code within owned globs)
```

## 4. Field-level authority (quick reference)

> Canonical terms: status §3.8 · gate levels §3.9 · node classes §3.2 ([SPEC-GROWTH-ENGINE.md](SPEC-GROWTH-ENGINE.md)).

```text
field                         author        gate      derived/verified by
---------------------------------------------------------------------------
id, kind, parent              P  -> H        HARD      E (propagates to spines)
contract.provides/invariants  P             see §7     E (vs evidence)
contract.error_behavior       P             see §7     E (contract tests)
acceptance_criteria           P / H         see §7     E (test evidence)
design.approach/constraints   C             NONE       E (no neighbor impact)
depends_on                    C             AUTO       E (vs import graph)
code (globs)                  P / H         SOFT       E (classifier; overlap=error)
status                        — (no author) —          E ONLY
project.index.json, evidence  — (no author) —          E ONLY (generated)
```

## 5. Operation-level authority (RACI)

```text
operation                      propose  author  gate              engine role
-----------------------------------------------------------------------------------------
Set root invariant             P / H    H       HARD              propagate to ALL spines
Add container                  P        H       HARD              scaffold, validate
Create component (boundary)    P        P       SOFT (H confirms  scaffold; granularity-
                                                 boundary is real) heuristic gate (§10)
Author component contract      P        P       SOFT (H reviews   record; mark consumers
  (initial)                                      public/shared)    none
Breaking contract change       P / C    P       HARD + change-set compute consumer impact;
                                                                  BLOCK until migrated
Additive contract change       C / P    owner   SOFT (auto if     verify backward-compat
                                                 consumer tests OK)
Change acceptance_criteria     P / H    P       follows contract  link to tests
Declare depends_on             C        C       AUTO              validate vs evidence
Internal design change         C        C       NONE              rebuild evidence
Code within owned globs        C        C       NONE              rebuild evidence
Mark node verified             —        —       —                 E ONLY (needs evidence)
```

In an UNSUPERVISED run a change above a node -- to the root, a container, a file
H gave -- can also be PROPOSED by a decision request and AUTHORISED by H', who
accepts it in H's place (§6, §8). It is still authored as the table says, and
its gate does not move: a container change stays HARD and waits for H, and so
does the ADR that authorised it.

## 6. Hard prohibitions

```text
Coding Agent (C) MUST NOT:
  - create a new node unilaterally
  - edit another node's spec
  - change its own node's PUBLIC contract without the contract-change gate (§7)
  - set status = verified

Planner Agent (P) MUST NOT:
  - write code
  - mark anything verified
  - bypass a HARD gate

Intent author (I), when it is an agent (a run, orchestrated):
  - MAY author NODE-level intent -- what a component is for and must do. That
    is what a run delegates, and the one exception to "agents author no intent";
    it is why a run is a switch of its own and not "more delegation"
  - MUST NOT author the goal, the root's or a container's intent,
    ARCHITECTURE.md or the zones: they stay H's (a change there is HARD, and
    never inside the delegable scope). One exception, in an unsupervised run:
    a change to the root or a container that H' ACCEPTED as a decision request
    -- exactly that change, through P, and it still waits for H as HARD
  - MUST NOT write a SPEC.md, source or test itself: P and C do, each with its
    own model. The tools a run grants make this the path of least resistance,
    not an impossibility -- the stream records what the agent did
  - MUST NOT accept, reject or switch the delegation

Reviewer (H'), in an UNSUPERVISED run:
  - MAY answer a decision request in H's place: accept or reject the proposal
    AS WORDED. That is the second exception to "agents author no intent", and
    the only one above a node: it is why an unsupervised run is a setting of
    its own, which H chooses, and needs the delegation on
  - MUST record every answer as an ADR in ARCHITECTURE.md that names H' as the
    one who gave it -- a change to that file is HARD and only H accepts it, so
    every answer waits for H's review, and a rejected one blocks the gate
  - MUST NOT reword a proposal or put its own in place of it, change TASK.md,
    declare or lift a zone, or accept a HARD change outside the delegation
  - leaves a request OPEN when it is unsure (below the fixed confidence guard):
    that request waits for H, as in a supervised run

Engine (E) MUST NOT:
  - author intent (contract, criteria, design)
  - it may only PROPOSE diffs ("undeclared import X->Y; add depends_on?")

Human (H) is the ONLY actor who may:
  - approve HARD gates -- or delegate ONE kind of them, by switching a
    project's delegation on: a breaking change to a consumed component
    contract that E found migrated, which H' may then accept (AUTONOMY.md §3). The delegation is H's
    act, the zones stay H's, and H can overrule every acceptance by H'.
  - grant waivers (§8)
  - set the autonomy switches (the draft gate, the delegation, a run -- and
    whether it runs unsupervised)
  - keep or take back every answer H' gave in an unsupervised run: accept the
    ADR to keep it, reject it to take it back
```

## 7. Contract-change protocol

```text
ADDITIVE  (new optional method, widened return, new event):
  -> SOFT gate
  -> Engine confirms backward-compatibility
  -> consumer contract-tests run; auto-approve if green

BREAKING  (removed/changed signature, tightened invariant):
  -> HARD gate + CHANGE-SET
  -> the change is ONE transaction spanning D + all direct consumers
     (commit only when all green)
  -> OR deprecate-then-migrate with contract versioning (v1 + v2 coexist,
     consumers migrate one at a time, v1 removed when no consumer remains)
  -> Engine BLOCKS merge while any consumer is red
```

The engine distinguishes additive from breaking automatically by diffing the
declared `contract.provides` surface; ambiguous cases default to **breaking**
(fail safe). Built in `engine/changeset.py`, with the consumer impact; it is
shown before Save and keeps D2 from clearing a HARD change. Headless the commit
gate diffs against the accepted state (`engine/accepted.py`) and HOLDS a breaking
change -- pending, the node and its consumers not `verified` -- without refusing
the commit. NOT built: the consumer contract-tests, and "BLOCK while any consumer
is red".

## 8. Waivers and escalation

> Canonical definition: [SPEC-GROWTH-ENGINE.md §3.10](SPEC-GROWTH-ENGINE.md).

```text
A waiver is TYPED and has a STATE. Requesting and granting are separate acts:

  waiver:                              waiver:
    state: requested                        state: granted
    kind: <one of the four>                 kind: <one of the four>
    reason: <why>                           owner: <a person>
    proposed_expiry: <date>   (optional)    expires: <date>
                                            reason: <text>

Rules:
  - ANYONE may request a deviation, agents included. Only H grants one.
  - A request grants nothing; it is reported on every `validate` until decided.
  - A node with any unresolved waiver is at most `implemented`, NEVER `verified`.
  - A node with any unresolved waiver does NOT count as done in progress metrics.
  - E surfaces requests and expiring/expired grants on every `spec validate`.
```

```text
ENFORCED (engine/waivers.py, on every `validate`): state and kind; a reason on
every request; owner and expiry on every grant; an expired grant is a HARD error;
any unresolved waiver blocks `verified` and is excluded from `progress.done`.

"Only H grants" is not a property of the file. For the planner it is enforced at
the authoring end -- agent/planner._clean_waiver downgrades anything it drafts
to a request. For a coding agent writing YAML directly it is the manual's rule.
```

Why agents may REQUEST: when they could not write a waiver at all, an agent
that needed a deviation made it anyway and hid it in prose (run 02). The rule
that was meant to keep deviations under H's control removed H's view of them.

### Decision requests — asking for what is above you

> Canonical definition: [SPEC-GROWTH-ENGINE.md §3.10a](SPEC-GROWTH-ENGINE.md).

```text
  decision_requests:
    - target: ARCHITECTURE.md | <node id above the asker>
      proposal: <the decision, as it should be written into the target>
      reason: <why it is needed>

Rules:
  - ANYONE may request a decision. Only the owner of the target makes it --
    H for ARCHITECTURE.md and for contracts at a HARD gate; in an unsupervised
    run H' in H's place (below), for H to review.
  - A request grants nothing and is reported on every `validate`.
  - A node with a pending request is at most `implemented`, and not done.
  - H resolves it by changing the target and deleting the request.
  - In an UNSUPERVISED run H' resolves it in H's place, between rounds: it
    accepts or rejects it as worded, records the answer as an ADR naming
    itself, and deletes the request (§6). H reviews every such ADR afterwards.
```

In the cockpit, H decides them in the **Requests** window (engine/inbox.py) --
and, once a project tracks an accepted state, its pending HARD changes too
(Prepare with H', Accept, Reject with a reason):
grant or reject a waiver; accept an ARCHITECTURE.md decision as a dated ADR, or
edit a node's contract and mark the request resolved; reject either, optionally
recorded as an ADR so it is not asked again.

"Ask instead" was the rule for decisions above an agent. Unattended there is
nobody to ask, so the rule produced silence: in run 02 an architectural choice
went unrecorded and a design was fitted to a contract nobody could update.

This is the explicit guard against `PENDING-EXTERNAL-EVIDENCE` rot: a waiver
can never masquerade as completion, it always carries an owner and an expiry,
and it is visible on every validation run. The expiry is what makes it a guard
rather than a label -- past its date it BLOCKS, so the deviation has to be
renewed deliberately or resolved.

## 9. Engine enforcement (mechanical)

```text
NO SILENT DRIFT — the core gate (see the invariant at the top):
- `spec validate` (drift validator) + acceptance tests run at EVERY merge/commit
  and are BLOCKING. A commit where the code's evidence diverges from its spec
  is rejected. "It works" is NOT sufficient to merge.
- Divergence examples that block the merge:
    * a public export/route/event not represented in the owning contract
    * a cross-owner import without a declared depends_on edge
    * an acceptance criterion without test evidence (and no open waiver)
    * a source file with no spec owner (orphan) or two owners (conflict)
- Sync is cheap, not heroic: when code changes, the AI updates the affected
  spec front matter in the SAME commit; the human approves only the contract
  lines. The loop is closed by tooling, not by remembering.

Other enforced rules:
- Gates are enforced at merge/commit:
    structural or contract diff WITHOUT an approval token -> rejected.
  As built, the approval token is the ACCEPTED STATE (glossary §3.9b), and a HARD
  diff without it is HELD, not rejected: the commit lands, the affected nodes
  cannot be `verified` until H accepts. Refusing would stop an unattended agent;
  holding keeps the change visible without stopping the work.
- status / index / evidence are engine-owned; an agent write to them -> rejected.
- Node creation passes the granularity heuristic (§10),
    else it stays inside the parent as design, not as a new node.
```

### Implementation: the commit gate (cockpit/cli.py + git pre-commit)

```text
The blocking gate is real and offline (no API key, deterministic):

  spec gate ROOT  ==  validate (intent graph) + drift (evidence vs depends_on)
                      exit 0 = PASS (commit proceeds), exit 1 = BLOCK (refused)

  spec install-hook ROOT
      writes .git/hooks/pre-commit -> `uv run --project <cockpit> cli.py gate ROOT`.
      An undeclared cross-node import (or any structural HARD error) refuses the
      commit until the spec gains the depends_on edge or the code drops the
      import. The fix lands in the SAME commit; no drift reaches history.

Today the gate covers: structure (orphan parent, ownership-line dep, undeclared/
missing-contract dep, cycles, invalid YAML, a SPEC.md with no id or a
duplicate one) + code drift (undeclared cross-owner
import, ownership conflict, orphan source file) + STATUS LIFECYCLE + HARD
changes against the accepted state (held as pending; on PASS, SOFT is accepted).
capability `duplicates` is advisory (never blocks).

NO FAKE COMPLETION (status lifecycle, cockpit/engine/lifecycle.py):
  A node marked `verified` MUST have a passing test-evidence record, else the gate
  is a HARD BLOCK. Evidence is written by Run Tests into <root>/.sge/evidence.json
  (test command + verdict + timestamp, per node sharing the build root); a FAIL
  record also blocks `verified`. `implemented`/`verified` component/code nodes that
  own no existing code raise a warning. Thus `verified` is EARNED, not claimed --
  the second failure mode (§0) is now mechanically prevented, like drift.
  (Test execution stays a separate, deterministic step; the gate only checks that
  the evidence EXISTS and is green -- it does not itself run tests, keeping it fast
  and offline.)

  project.index.json (cockpit/engine/index.py) is the generated, queryable snapshot
  -- spec graph + capabilities + ownership/dependency/code edges + per-node status
  and test evidence. Engine-owned, never hand-authored.
```

## 10. Open calibration points

Two parameters must be calibrated to the team's style before this is complete.
They are intentionally left as decisions, not defaults.

### 10.1 Granularity heuristic (controls node creation)

A new component node is justified only when **all** hold:

```text
- it owns >= N code units                         (N = TBD, e.g. 3)
- it exposes its own public surface (contract)    (not just internal helpers)
- it has >= 1 cross-owner consumer                (someone outside depends on it)
```

Otherwise the work stays inside the parent as `design`, not as a new node.
Tune `N` and the conditions to avoid both micro-node sprawl and oversized
components.

### 10.2 Soft-gate strength per zone

The SOFT gate for new components defaults to *async human review*. Define zones
where it is escalated to **HARD**:

```text
- below a security/auth container        -> HARD
- nodes touching persistence schema      -> HARD
- nodes exposing external-facing APIs    -> HARD
- everything else                        -> SOFT (default)
```

Adjust the zone list to match where mistakes are most expensive.

## 11. Summary

```text
The engine tooling scaffolds the FORM.
The Planner drafts the CONTENT.
The Human approves the CONSEQUENTIAL parts (boundary + contract + invariants).
The Coding Agent maintains its own node while implementing.
The engine tooling derives everything OBSERVABLE and enforces the gates.

No one authors the front matter alone — but for every field it is unambiguous
WHO may change it and UNDER WHICH gate.
```
