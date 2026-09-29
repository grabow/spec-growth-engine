# Spec Growth Engine - Cockpit · Status

_Re-entry / handoff document._

> **How to read this.** The sections marked CHECKED are verified by
> `tests/test_docs_claims.py` on every test run: every module listed must exist,
> every existing module must be listed, every CLI command must be mentioned, and
> no test count may be hardcoded. The same file also holds AUTONOMY.md §4 and the
> glossary §3.2c, and `tests/test_glossary_behaviour.py` checks those claims by
> constructing the situation rather than by looking up a symbol. Everything else is prose and can rot -- the previous version of this file
> quoted a test count that had tripled since it was written, and listed none of
> the eight modules built after it. Numbers that drift are therefore replaced by
> the command that produces them.

## What it is

A guided desktop cockpit (Tk) over a deterministic spec engine. The engine
authors **no intent** (it parses, indexes, assembles, validates); a planner agent
drafts SPEC.md from intent, a coding agent implements, an optional reviewer (H')
critiques the draft. ASCII-based; `.md` extensions stay but there is **no**
markdown rendering (plain `tk.Text`).

## Setup

```sh
cd cockpit                   # from the repository root
uv sync --group dev          # --group dev installs pytest
uv run python app.py [SPEC_ROOT]     # default ./example
uv run pytest -q             # the test count lives here, not in this file
```

- **Python 3.12**, pinned via `.python-version`. The GUI needs Tk: uv's CPython
  bundles it under the installation but Tcl looks inside the venv, so
  `app._locate_bundled_tcl()` points it at the right place before importing
  tkinter. Without that, `uv run python app.py` fails with "Can't find a
  usable init.tcl" while the libraries sit right there.
- Deps: `openai`, `python-dotenv`, `pyyaml`, `python-frontmatter`, `networkx`.
- **One endpoint per role**, in `cockpit/.env` (git-ignored; agent/llm.py,
  `.env.example`): `SGE_<ROLE>_BASE_URL`, `_API_KEY`, `_MODEL` for PLANNER,
  REVIEWER, INTENT, CODER -- the same three lines for every role, nothing falls
  back, no provider is built in -- and `_HARNESS` for I and C. P and H' are chat
  calls; I and C run on the harness `codex-cli`, the Codex CLI (`codex exec`,
  agent/codex_cli.py, role_agent.py), REQUIRED for them -- C also for the
  cockpit's Codex button. The key reaches only the process that needs it,
  never a command or a log. H' on P's model: the cockpit says the review is not
  independent.
- Non-secret settings in `cockpit.json` (git-ignored): last root,
  semantic matching, the draft gate D0-D2 (key `draft_gate`), graph view state.
  No model: which model plays a role is set in `.env` only.

## Modules — CHECKED

```text
engine/            deterministic, authors no intent
  parser.py        load SPEC.md + ARCHITECTURE.md; skip (and report) invalid YAML
  graph.py         ownership tree (parent) + dependency DAG (depends_on) + Spine + cycles
  context.py       Context(N): ARCHITECTURE + ancestor contracts (SHORT) + target (FULL)
                   + own code + dependency contracts
  validate.py      spec-side structure: orphan, undeclared dep, dep inside the ownership
                   line, missing contract, cycles; plus status/evidence (lifecycle)
                   and waiver issues (waivers)
  evidence.py      code evidence graph: TS/JS, Java/Kotlin, Dart, Python imports ->
                   owners; owns EXCLUDED_DIRS, the one build-output exclusion list
  drift.py         the drift gate: code edges vs declared depends_on; language-aware
                   orphans; reports its scan scope and declared exclusions
  nodes.py         CRUD: new_node / delete_node (recursive) / bootstrap_root
  capability.py    capability registry: find, duplicates, claims (horizontal reuse axis)
  attribution.py   which test files exercise which node (per-node, not per build root)
  lifecycle.py     status lifecycle: make `verified` EARNED; evidence store; autonomy log
  autonomy.py      the switches as code: the draft gate's D2 decision + revise loop
                   (the declared-zone check), the delegation's scope and rule, and
                   the delegation itself, on | off (planner and reviewer injected --
                   the engine calls no model)
  intents.py       the growth record: every intent a node was grown from, in order,
                   with its author (I or H) -- `.sge/intents.jsonl`, `cli.py intents`
  iteration.py     the rounds of a run: I's DONE/BLOCKED, the rule -- stop, or
                   resume with E's failures or the gaps H' names; what waits for H
                   is counted apart from the gaps, and a BLOCKED over a green floor
                   where only that is left ends `asking` -- and the facts H' checks
                   the goal by (specs, tests, pending changes)
  unsupervised.py  an unsupervised run: between rounds H' answers the decision
                   requests in H's place (an ADR naming H', which waits for H's
                   review as a HARD change to ARCHITECTURE.md) and decides what the
                   delegation lets it; `rework` says which answers send I back
  changeset.py     change set: which gate a SPEC.md change falls under (HARD/SOFT/AUTO/
                   NONE) + consumer impact: who depends on it, who mentions what was
                   removed, which evidence was recorded against the old contract;
                   declared protected zones (`protected: true`) become HARD on a
                   breaking change
  accepted.py      the accepted state (.sge/accepted.json) a headless change set is
                   measured against: E accepts <= SOFT on a passing gate, H accepts
                   HARD; a pending HARD change blocks nothing but keeps its nodes
                   (and a broken contract's consumers) from `verified`; a REJECTED
                   one blocks the gate with H's reason
  assist.py        assisted HARD (AUTONOMY 5c) and the delegation: H' briefs a
                   pending HARD change (injected), H accepts/rejects/confirms/
                   overrules; with the delegation on, `decide` lets H' accept what
                   is in scope and migrated
  migration.py     E's precondition for the delegation: the node and every accepted consumer
                   tested (green, attributed) after a breaking change, and no
                   consumer still naming an operation the node no longer provides
  waivers.py    typed/owned/time-boxed deviations; expiry blocks (GOVERNANCE §8)
  decisions.py     decision requests: asking H for decisions above the asker
  inbox.py         H's inbox: list pending waivers/decisions and resolve them on disk
  index.py         generate project.index.json (graph + capabilities + edges + evidence)
agent/
  llm.py           what every model-backed role shares: client, call, parsing -- and
                   one endpoint per role (URL, key, model); never logs a key
  codex_cli.py     a role (I, C) as a `codex exec` agent on its own endpoint: an
                   ad-hoc provider via -c, the key only in the child's environment
  planner.py       role P: intent -> SPEC.md draft; revise_spec for an existing node
  coder.py         role C: run the codex CLI at the build root, stream stdout
  reviewer.py      role H': critique a draft (verdict / confidence / findings);
                   brief a pending HARD change (recommendation, risks, alternatives);
                   check a run's goal against TASK.md (the gaps, WHAT not how)
  semantic.py      reranker + judge for the capability registry (the planner's model)
app.py             the Tk cockpit
appconfig.py       persistent non-secret settings (cockpit.json)
role_agent.py      start a role as a codex agent (`intent`, `coder`); --describe
                   prints who plays which role, never a key
groundwork.py      lay the floor of a NEW project: root, container + manifest from an
                   archetype, the invariants (four defaults + four questions), the
                   accepted state, the two manuals rendered for this project's paths,
                   and -- when a run is intended -- TASK.md from the method's template
                   (spec-growth-engine/TASK.template.md) and three answers -- which P
                   can expand into a fuller goal on request (suggest_goal; the person
                   edits and confirms it, also later: Edit Goal). It records
                   the answers (.sge/groundwork.json), so like() lays the same floor
                   in another directory. plan() shows, apply() writes; P only WORDS
orchestrate.py     run I in rounds, in any project: a session, E's floor, the goal check by H', then stop
                   or `codex exec resume` the same session with what is missing;
                   --unsupervised has H' stand in for H between rounds (needs the
                   delegation on); CoderWatch passes on what C is doing while I
                   waits on it; blockers() says what a run still needs
runlog.py          one readable line per event of a run's stream -- rendered once,
                   for the cockpit's Run window and the run's log (.sge/runs/NN.log)
cli.py             headless gate: validate | drift | gate | init (lay a floor; --like OLD) |
                   manuals (render them again) | run (an agent, in rounds) |
                   pending (H's inbox: waivers, decisions, HARD changes, delegated) | prepare |
                   decide | accept | reject | delegate | test | draft | revise | code | intents |
                   duplicates | index | install-hook
layouts.py         per-container code-layout conventions (archetypes) and the build
                   manifest each one seeds -- one decision, two spellings, one source
specfix.py         auto-repair the recurring SPEC.md YAML breakage (unquoted `word: word`)
testrun.py         run the project's tests at the build root -> test evidence
```

## Surface

```text
GUI menus   Project  Open · New Project (lays the floor) · Reload
            Node     Show Tree · New Node · Delete Node · Edit Arch · Save Arch
            Spec     Load Spec · Save Spec · Build Context · Codex · Run Tests ·
                     Start Run... (an agent writes the intent, in rounds)
            Validate Requests... · Validate · Drift · Generate Index · Install Git Hook
            Capability  Find Capability · Duplicates · Claim Capability
GUI extras  Requests (n): H's inbox -- grant/reject waivers, accept/resolve/reject
            decision requests, prepare/accept/reject pending HARD changes;
            nodes awaiting H are amber in the graph
            Draft ⟶ / Revise → · autonomy slider (D0..D2, the draft gate) ·
            the delegation switch beside it (per project, on | off) · node graph window
            (zoom, collapse, dependency edges) · Codex window with status bar
            Run window: one line per round (claim, floor, gaps, what it asks H),
            the cockpit re-reads the graph after every round, Draft, Revise,
            Save and the slider are locked while it writes, and the end says
            which outcome it was; Close hides the window, Build > Show Run
            Window brings it back
CLI         uv run python cli.py {validate|drift|gate|pending|prepare|decide|test|duplicates|index|install-hook} [ROOT]
            uv run python cli.py accept ROOT ID... | --all [--by NAME]
            uv run python cli.py reject ROOT ID... --reason TEXT [--by NAME]
            uv run python cli.py delegate ROOT [on|off] [--by NAME]
            uv run python cli.py draft ROOT ID --parent P --kind K --intent TEXT
            uv run python cli.py revise ROOT ID --change TEXT
            uv run python cli.py code ROOT ID [--instruction TEXT]
            uv run python cli.py intents ROOT [ID]
```

`gate` is the blocking one: it is what the installed pre-commit hook runs. Once a
project tracks an accepted state (`accept ROOT --all`), it is also the one checking
command that writes: a PASS accepts every change at SOFT or below. `pending` shows
the HARD changes waiting with their impact, delegable scope, migration and the H' brief;
`prepare` has H' write the briefs; `decide` (delegation on only) lets H' accept what is in
scope and migrated -- the two commands that need an API key, never the gate;
`accept` / `reject` are H deciding, confirming or overruling; `delegate` is H
delegating; `test` records evidence headless.

Both reports state what they looked at, not only what they found -- a silent
pass is otherwise indistinguishable from a scan that never ran:

```text
validate   waivers: 1 open (api.pay), next expiry 2026-12-31
drift      scan scope: .ts (declared)   .py (from build manifests)
           excluded:   2 file(s) via 1 declaration(s)
```

## The two failure modes it exists to catch

```text
drift            specs and code disagree        -> drift gate
fake completion  status claims more than is true -> lifecycle gate
```

Both are deterministic and block regardless of the autonomy switches.

## Design decisions (standing)

```text
1. ASCII-based; .md format stays, no markdown rendering.
2. Engine headless, GUI a thin shell.
3. `code:` is always present. system/container own only their build manifest;
   a code-owning component never has `code: []`.
4. `code` globs are PROJECT-ROOT-relative -- spec tree and code tree are
   independent layouts (CONCEPT §7a).
5. The code LAYOUT is a container decision, seeded from layouts.py into the
   container's contract.invariants and carried down the Spine; component globs
   are derived from it, not improvised. The container's BUILD MANIFEST comes
   from the same archetype and is declared as the container's own code.
6. depends_on is a USAGE edge; never parent/ancestor/descendant/self.
   A parent importing its descendant's code is a REALIZATION edge, exempt.
7. Build root = nearest ancestor directory with a build manifest, found from
   the node's CODE (not from its SPEC.md).
8. Evidence lives in .sge/ (local, git-ignored); status lives in SPEC.md
   (committed). See "Known limits" below -- this has a real consequence.
9. A component owns its OWN TESTS. A test is the evidence the contract holds,
   and attribution credits an owned test without any import analysis. Where the
   tests live is part of the container's layout invariant (it differs per
   language), which is why layouts.py states it per entry.
10. A deviation from any rule is an WAIVER: typed, owned, time-boxed. Past its
   expiry it BLOCKS, so a deviation must be renewed deliberately or resolved.
   An open waiver keeps a node off `verified` and out of the done count.
```

## Known limits (deliberate, and worth knowing)

```text
- Test evidence is recorded per BUILD ROOT. attribution.py additionally maps each
  test file to the nodes it exercises (by ownership or by import), and the gate
  WARNS when a `verified` node has no test attributed to it. It warns rather than
  blocks: attribution is static, so reflection, fixtures and subprocesses are
  invisible to it. Making `verified` provable needs runner coverage data.
  (LIFECYCLE.md §5a)
- Because evidence is local and status is committed, a fresh clone hard-fails
  every `verified` node until the tests are re-run. CI must RUN the tests before
  the gate; it cannot gate a bare checkout. (LIFECYCLE.md §5b)
- Protected zones are DECLARED (`protected: true`), not detected. An outward or
  high-stakes node nobody declared is still read SOFT; the change set names the
  gap, but acting on it is H's. (AUTONOMY.md §5b)
- The gate checks structure, ownership, imports and status evidence. It does NOT
  check behavioural invariants ("never parses .env") or build-system wiring
  (POM aggregation). Those need tests or human review.
- "Dependency bypasses contract" (importing another node's internal files) needs
  a public-surface marker that does not exist yet.
- Decision requests record questions above an agent's authority (ARCHITECTURE.md,
  a container's contract). The gate reports them and keeps the node off
  `verified`, but cannot see whether H changed the target before deleting the
  request -- the deletion is the resolution, git history the audit.
- Waivers have two states: anyone may REQUEST one (with a reason), only H
  GRANTS one (owner + expiry). The gate enforces the shape of both, but cannot
  see who wrote `state: granted`: the planner downgrades anything it drafts to a
  request, while for a coding agent editing YAML directly it is the manual's rule.
- There is deliberately no "not yet under spec" class: adopting a whole existing
  codebase is OUT OF SCOPE, because the contract would be written by reading the
  code and the gate would then compare the code to a restatement of itself.
  Growing a new part inside an existing repository needs none of that -- point
  the spec root at the subtree (CONCEPT §7b).
  `excluded` covers the permanent case (generated sources, project scripts,
  fixtures in the project's own language). It does NOT cover tests: a component
  owns its tests, and attribution credits it for them. (Glossary §3.2c)
- What `implemented` MEANS for a node owning no code is still unanswered. It is
  allowed and says little; the parent-may-not-be-ahead-of-its-children rule
  (LIFECYCLE §5-) only stops it from saying something untrue.
- The Requests-window tests run each GUI scenario in its own process
  (tests/gui_scenarios.py). Driven in-process under pytest the cockpit hung in
  Tk's update() after a Grant, while the same steps pass as a plain script; the
  cause was not isolated. A decision taken in that window is H's by convention --
  nothing mechanically ties a grant to a person.
- `kind` is a convention, not an enforced enum: `kind: banana` passes the gate.
  `status` by contrast has lifecycle.VALID_STATUS. (Glossary §3.2)
- The gate resists the two one-line ways to silence it (`excluded: ["**"]`,
  `code: ["**"]`), but it is not adversarially hardened in general. An agent
  graded on "gate: PASS" optimises the gate, not the spec -- so a green gate is
  evidence about the graph's SHAPE, never about whether the contracts are right.
- Bare/workspace-alias TS imports are not resolved (only relative specifiers).
- No rename/move of nodes. dependents_of is shown only inside a change set
  (Draft / Revise / Save), not as a view of its own.
- A HARD change is never BLOCKED, only held: it stays pending and keeps its nodes
  from `verified`. That is deliberate (an unattended agent must keep working), and
  it means a project that never looks at `pending` accumulates them.
- Untracked projects (no `.sge/accepted.json`) get no HARD tracking at all -- the
  gate behaves exactly as before. Opting in is `accept ROOT --all`.
- `accept` / `reject` / `delegate` are not tied to a person: an agent can run them.
  The manual forbids it and the audit log records `by`; same trust level as test
  evidence.
- "migrated" trusts green consumer tests: an invariant tightened where no consumer
  test looks passes it. It is a precondition for the judgement of H', not a proof.
- A protected node raises the gate only for a BREAKING change: adding to a GIVEN
  container's contract is still additive and SOFT, and E accepts it. The agent
  manual's "do not edit the given files" is still the rule.
```

## Autonomy

Three switches, all built. The D2 decision lives in
`engine/autonomy.py` (planner and reviewer injected), the cockpit only applies it.
Its entire effect is that an approved draft saves without a click -- provided the
engine classifies the change as SOFT or below (engine/changeset.py). A HARD
change set (breaking a consumed or outward contract, a new container, a
structure change, a root invariant, a waiver grant, or a declared protected node)
always goes to H.

Headless -- an agent writing SPEC.md files and running the gate -- the same
classification runs against the ACCEPTED state (engine/accepted.py): E accepts
what is SOFT or below on every passing gate, a HARD change stays pending until
`accept`. This is the substrate the delegation builds on: 5c has H' prepare the
pending HARD changes (built: engine/assist.py, the Requests window, `prepare`),
and the delegation (built) lets H' accept the ones H delegated: `delegate ROOT
on`, then `decide`. No statistics: it is H's act, bounded by zones, the migration
check by E and the overrule by H (AUTONOMY.md §3).
Canonical: [AUTONOMY.md](../spec-growth-engine/AUTONOMY.md), whose §4 is itself
checked by `tests/test_docs_claims.py`.

## Projects, and runs on them

A project lives in any directory. `New Project...` in the cockpit (or `cli.py
init ROOT ...`) lays its floor there -- root, container, invariants, the accepted
state, both manuals rendered for that directory, and TASK.md when a run is
intended -- and records the answers (`.sge/groundwork.json`). `New Project
Like...` (`init NEW --like OLD`) lays the same floor elsewhere: a second attempt
at a task is a new directory, not the first one reset. A run -- Start a run...,
or `cli.py run ROOT` -- records itself in the project (`.sge/runs/NN.jsonl`,
`.log`, `.roles`) and ends with the tests recorded, the delegated decisions made
and the briefs prepared. When the templates change, Refresh Manuals (`cli.py
manuals`) renders a project's copies again.

Runs 01-12 lived in `experiment/`, with their own scripts, tasks and protocol;
they are archived outside this repository (run-NN.tar.gz). What they were for
still holds for every run: the point is not whether the task gets finished. It
is which blocks were RIGHT (the method works) and which were WRONG (an engine
bug), and whether anything wrong reached a green gate.

## Open items (recommended order)

Each one is tagged with the layer it serves (README, SPEC-GROWTH-ENGINE 5):
**layer 1** keeps spec and code from diverging -- deterministic, enforceable;
**layer 2** is an agent-driven run, which uses layer 1 as its floor and its
witness. The rule this tag exists for: build in layer 2 only what a run needs or
what pays back into layer 1. Of the six findings the runs 05-10 produced, five
were layer-1 defects.

```text
1. [layer 1] FOLDER-RELATIVE GLOB HINT
   When a `code` glob matches nothing but WOULD match files if read relative to
   its own SPEC.md folder, say so. Catches the documented stumbling block
   (CONCEPT §7a) mechanically instead of as an orphan report pointing the wrong way.

2. [layer 1] DELEGATION GROUNDWORK
   (a) change-set + consumer impact: BUILT (engine/changeset.py).
   Headless HARD tracking against an accepted state: BUILT (engine/accepted.py).
   (b) declared zones: BUILT (`protected: true`, engine/changeset.py + engine/
   autonomy.py). Run 03's auto-accepted svc.cli change is the case that forced it.
   (c) assisted-HARD: BUILT (engine/assist.py) -- H' briefs, H decides.
   Delegation: BUILT -- H's act, not a measured grant: delegable_scope, the migration
   check by E (engine/migration.py), `cli.py decide`, the overrule by H.
   Run 04 exercised it (increment 3): two acceptances by H', svc.cli kept in
   its zone, and a false "not migrated" that was fixed (4bcf83f).
   Run: BUILT as an operating mode -- Start a run..., or `cli.py run ROOT`: the
   intent author I is an agent that asks P (draft/revise) and C (code), each
   with its own endpoint (cockpit/.env). I and C run as `codex exec`. Run 07
   carried increment 3 end to end: 8 revises, 3 codes, a green suite, and no
   file_change event in the whole stream -- I wrote no spec and no code itself.
   H' accepted four nodes under the delegation and left the protected one for H.

3. [layer 2] ITERATION: BUILT (orchestrate.py, engine/iteration.py), and startable
   from the cockpit (Build > Start Run..., app.Cockpit.start_run): it says what a
   run still needs before it begins, shows one line per round, and locks Draft and
   Revise while an agent writes the same files. A run goes in
   rounds: after each session of I, E checks the floor (test, gate) and, on a
   green floor, H' the goal (TASK.md against the specs and the tests); the rule
   resumes the same session (`codex exec resume`) with what is missing, or
   stops: done | asking | blocked | stalled | error | unchecked | limit
   (MAX_ROUNDS, default 5). `asking` is a green floor where nothing is missing
   but what waits for H: an open decision request, or what H' names as resting
   on a decision only H may make -- counted apart from the gaps, so it is never
   sent back to I (run 11 was, for a root it could not move). A BLOCKED is
   measured too, and ends `asking` when that is all it was (run 12).
   UNSUPERVISED (run: off | on | unsupervised): between rounds H' answers the
   decision requests in H's place and decides what the delegation lets it
   (engine/unsupervised.py); every answer is an ADR that waits for H's review.
   Not yet run on a real task. The slice loop INSIDE a session is the manual's ("How the graph
   grows"); the rounds catch the stop between. Run 07 ended `done` in one
   round; run 05 ended `blocked` -- the intent author reported an engine bug
   it could not work around honestly, which is what the outcome is for.

4. [layer 1] tsconfig path-alias resolution, for workspace imports (@...).

5. [layer 2] WHAT A RUN PROMISED, since you last looked. A new node's contract is a
   SOFT change, so E clears it on the first green gate and H never has to read
   it: run 09 added 447 lines of promises that way. The gate levels measure
   BREAKAGE, and what was never promised cannot break. A digest -- new nodes,
   new `provides` -- would make the volume visible without blocking a run.

6. [layer 2] WHAT H' COULD NOT CHECK. The goal check reports gaps; it does not
   report which sentence of "Done means" it could not judge from specs and
   tests. That number is a measure of the task's quality, produced by the work
   itself, and TASK.md is the one document nothing verifies (3.12).

7. [layer 1] A FLOOR WORTH READING. `bootstrap_root` writes "- TODO" where the
   invariants go. The four that both experiments used were near-identical, so
   they are a default, not a discovery -- seed them as real sentences (easier
   to delete than to invent), and warn while a TODO line is still in there.

8. [layer 2] TASK.md -> a drafted floor, by a model. Considered and NOT built: it
   would need a new role with its own endpoint and a second exception to
   GOVERNANCE 6 (agents author no intent), to save about six lines that a
   person edits in ten minutes -- and it would automate the part where a
   model's guess is least checkable. The questions it would ask, a run already
   asks better: run 09 raised two, run 10 five, each after hitting the need.
   Reopen only if a bare-floor run raises so many that the up-front version
   would clearly have been cheaper.
```

## History

The bug log, the Hello-World end-to-end run and the earlier refactors are in the
git history, which does not rot. `git log --oneline` in this repository is the
record; this file describes the CURRENT state only.
