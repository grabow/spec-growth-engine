# Vertical-Slice Growth & Node Lifecycle

> Part of the **Spec Growth Engine** method. This document defines the
> *orchestration policy*: in which order the spec graph is grown and implemented.
> The tooling substrate (context assembler, drift validator, governance) is
> unchanged — only the sequencing changes.

## 0. Why this exists

Two opposite strategies both fail:

```text
Breadth-first skeleton (fake all nodes, fill later)
   -> hard problems hide in the fakes, surface only at the end -> late crash

Pure agile (start small, just extend, no architectural floor)
   -> the architecture erodes; a needed boundary (e.g. a database) never
      appears because no feature happened to force it -> silent under-architecture
```

The second one is not hypothetical: it is exactly how a curated-product-finder
ended up with a 312-line hardcoded array instead of a database — it grew
incrementally and nothing ever forced persistence.

Vertical-Slice Growth keeps the agility of small increments **and** the floor of
a deliberate architecture, so it avoids both failure modes.

## 1. Principle

```text
The unit of growth is a VERTICAL SLICE that is functional end-to-end.
Not a node. Not a fake skeleton. A thin, real, working increment.
```

A slice cuts a thin path through the C4 ownership tree
(`Context -> Container -> Component -> Code`) plus the dependency edges it needs,
and implements that path **for real**, to the depth the slice requires.

## 2. The two-layer rule

```text
Layer 1  INVARIANTS — deliberate, up front, NOT just-in-time
         root invariants + key container boundaries:
         persistence, security, external integrations, error taxonomy, data model.

Layer 2  FEATURES — agile, just-in-time
         everything else grows as functional vertical slices.
```

The invariants are the **guardrail**; the slices are the **steps**.
Because "persistence = real store" is a Layer-1 invariant, slice #1 already runs
through the real store — the database cannot be "forgotten", and the drift
validator enforces it.

> This is the one place the engine is **not** JIT. Architecture floor first,
> features incremental.

## 3. The three growth rules

### Rule 1 — Invariants up front, features agile
Seed root invariants and key container boundaries at project inception, before
any feature. Everything below that is decomposed as far as it is KNOWN, and
implemented per slice; what would have to be guessed waits for the slice that
needs it.

### Rule 2 — Real along the path; fakes only at the frontier
```text
The CURRENT slice's active path must be fully REAL to call the slice done.
A fake (test double) is allowed ONLY for a dependency the current slice does
NOT exercise — i.e. one that belongs to a LATER slice — and only at the edge.

Forbidden: faking anything on the current slice's active path.
A fake is a frontier marker, never a deferred hard problem.
```
Frontier stubs are tracked as **waivers** (`kind: frontier-stub`, see
GOVERNANCE.md §8) naming the future slice that will replace them. A node that is
only a frontier stub stays `specd` — it can never be mistaken for done.

### Rule 3 — Hardest-first
```text
Order slices so the architecture-defining / highest-risk one comes FIRST.
Slice #1 is a tracer bullet through the riskiest integration
(real DB, real external API, real concurrency) — not the easy CRUD.
```
Hit the hard unknowns when the system is smallest and cheapest to change.
"Hardest" = touches a new container boundary, an external system, persistence,
concurrency, or the contract most consumers will depend on.

## 4. What a vertical slice is (concretely)

A slice:
```text
- touches or creates the nodes on a thin path through the tree
- implements them for REAL (no fakes on the active path)
- grows the spec graph minimally along the way (JIT spec, governance gates apply)
- ends as a verified, working, demoable increment of real value
```

Example (curated product finder), slice #1:
```text
"Search one keyword returns real products from a real SQLite table,
 rendered in the real UI."

forces real (minimal):
  shared-types        Product
  data.schema         products table DDL
  data.store-impl     reads from SQLite (NOT an array)   <- the Layer-1 invariant
  api.search          GET /api/search over the store
  web                 one page that renders the result
```
No fakes on this path. The hardest part (real persistence) is in slice #1.

## 5. Node lifecycle (status)

> Canonical status enum: [SPEC-GROWTH-ENGINE.md §3.8](SPEC-GROWTH-ENGINE.md). This section explains the per-status meaning.

```text
specd  ->  in-slice  ->  implemented  ->  verified
```

```text
specd        contract + acceptance criteria exist; no real code.
             (a frontier stub also sits here, flagged by a frontier-stub waiver)
in-slice     a live slice is actively building this node's REAL behavior. (transient)
implemented  real code exists, satisfies the contract, local tests pass.
verified     a real slice has exercised it end-to-end;
             acceptance criteria have test evidence; NO open waivers.
             (both halves enforced -- SPEC-GROWTH-ENGINE.md §3.10, §5a)
```

There is deliberately **no `faked` stage**. A node is never "done with fake
data". Fakes exist only as frontier-stub waivers, which keep the node at
`specd` and block `verified` (GOVERNANCE.md §8). This closes the exact loophole
that let a fake (`MOCK_PRODUCTS`) once pass as complete.

```text
ENFORCED (SPEC-GROWTH-ENGINE.md §3.10): a `frontier-stub` waiver is a HARD
error at `implemented` or `verified`, so a deliberate fake cannot present itself
as built even when the build root it sits under goes green. This is the second
leg under `verified`, independent of the build-root granularity of §5a.
```

### 5-. A node is realized by its children too

```text
A node's status may not be AHEAD of its children.

  `verified` with a child that is not verified   -> HARD
  any other status ahead of a child              -> WARN
```

Status describes whether a node is done, and a node with children is not done
while they are not. Without this rule a node owning no code — a system, or a
container owning only its build manifest — reaches `verified` on evidence
recorded for its build root while every child is still `specd`, and the gate
passes. That is fake completion one level up, and the evidence rule alone cannot
see it: the evidence is real, it just is not about that node.

Only `verified` blocks. Growing a graph means adding `specd` children
constantly, so a parent that is merely `implemented` gets a warning — demoting
it on every new child would block normal work. And the rule is one-directional:
a parent BEHIND its children is cautious, not false.

What this still does not answer: what `implemented` should mean for a node that
owns no code at all. Today it is allowed and means little. The rule above at
least stops it from meaning something untrue.

### 5a. How coarse the evidence actually is

The `verified` rule reads as "this node is tested". What the tooling enforces is
weaker, and the gap is where fake completion can still slip through.

```text
A test run records evidence for EVERY node that shares the BUILD ROOT it ran in
(cockpit: `covered` = all nodes whose build root is the tested one).

So the recorded fact is not
    "this node is tested"
but
    "something under this build root went green".
```

A node with no test of its own becomes eligible for `verified` as soon as any
green run happens under the same build root. The granularity of evidence is the
**build root**, not the node.

```text
Blocked by the gate     verified with NO evidence record
                        verified with a FAILING evidence record
NOT blocked             verified whose build root went green for other reasons
```

**Per-node attribution narrows this** (`engine/attribution.py`). Each test file
is attributed to the nodes it actually exercises, by two deterministic routes:

```text
OWNED    the test file falls under a node's own `code` globs
         (a Maven component owning src/test/java/**/<name>/**)
IMPORTS  the test file imports a file some node owns -- reusing the evidence
         import graph, which keeps an edge whenever the TARGET is owned
```

The evidence record then carries both facts: `build_root` (what the run covered)
and `tests` (what attributes to this node). A `verified` node that no test
attributes to is reported:

```text
WARN: status 'verified' but no test attributes to <id>
      (its evidence covers the build root, not this node)
```

It is a **WARN, not a HARD error**, and that is deliberate: attribution is
static, so a test reaching a node through reflection, a fixture, a subprocess or
an unresolvable import style is invisible to it. Blocking on a heuristic would
break the rule that the deterministic floor is correct, not merely strict.

Two consequences of the same honesty:

```text
- If attribution finds nothing for ANY node, the scanner is blind in this
  project (unknown language, tests outside the tree). It then reports NOTHING
  rather than declaring every node untested -- "unknown" is not "failing".
- A WARN does not stop a false `verified`. It makes it visible. Closing the
  hole entirely needs coverage data from the test runner itself, which is
  runner-specific and not part of the engine.
```

### 5b. Evidence is local; status is committed

```text
status              lives in SPEC.md          -> COMMITTED
test evidence       lives in .sge/evidence.json -> local, git-ignored
```

These two disagree by construction on a fresh clone:

```text
clone the repo  ->  no .sge/  ->  every `verified` node has no evidence record
                ->  HARD: "status 'verified' without test evidence"
                ->  the gate blocks until someone re-runs the tests locally
```

The gate outcome therefore depends on **uncommitted local state**, and CI cannot
reproduce it without running the test suite first. That is defensible -- evidence
should be something you produced, not something you inherited from a commit --
but it has a consequence worth planning for:

```text
CI must RUN the tests before running the gate; it cannot gate a bare checkout.
A pre-commit hook gates the machine that has the evidence, which is why the
hook works and a naive CI job does not.
```

If evidence were committed instead, `verified` would become a claim that
travels, i.e. exactly the fake completion the status rule exists to prevent.
The local-only choice is deliberate; the CI consequence is the price.

## 6. The slice workflow

> **Whose decision this is.** The workflow below is the INTENT AUTHOR's, role I
> (GOVERNANCE.md §1): H typing in the cockpit, or an agent in an orchestrated
> run -- the same job, either way. H grows the GOAL (the increments, the root,
> the containers -- in an unsupervised run H' may authorise a change to the root
> or a container that a decision request asked for, and H reviews it
> afterwards); I grows the GRAPH below them to meet it; P formalizes one
> step at a time; C implements it. The engine checks the RESULT of each step
> and never the order: which slice comes next, and how deep its path goes, is
> a judgement no gate can make. An agent reads it as its manual's "How the
> graph grows" (ORCHESTRATOR.md); a person reads it here.
>
> ```text
> outside   ITERATIVE over slices     one slice after another, each a working,
>                                     demoable increment, until the goal is met
> inside    RECURSIVE, but only       decompose as far as you KNOW the answer;
>           as far as you know        what you would have to GUESS waits for the
>                                     slice that needs it. Implement only along
>                                     the slice's path -- every node on it real
> ```

For each slice:
```text
1. Pick the next slice — hardest-first; smallest functional increment of REAL value.
2. Identify its thin path through the tree + the dependency edges it needs.
3. Grow specs minimally for new nodes on the path (governance gates apply).
4. Implement the path FOR REAL, node by node, each in its context bundle.
   No fakes on the active path; frontier stubs only off-path, as waivers.
5. Build the evidence graph; run drift validation on the slice.
6. Run the project's tests at the build root (mvn / uv / cargo / gradle / npm /
   flutter — chosen by the manifest; see CONCEPT §12 "Test runner"). A passing run
   is the test evidence the acceptance criteria require.
7. Verify the slice end-to-end (real, demoable); mark traversed nodes `verified`
   only when their acceptance criteria have that passing test evidence.
8. Repeat.
```

The graph grows with **working software**, one real slice at a time.

## 7. Contrast with breadth-first skeleton

```text
                      breadth-first skeleton        vertical-slice growth
risk                  hidden in fakes, late crash   hit per slice, hardest-first
each increment        non-functional                functional, demoable
architecture floor    faked structure up front      seeded invariants + per-slice drift
fakes                 everywhere, then filled        frontier only, off active path
"done" can be faked   yes (the trap)                 no (status + waivers forbid it)
```

The line runs between GUESSED and KNOWN structure, not between early and late.
A decomposition that is known -- because the goal fixes it, or a container's
contract does -- may be drafted at once; drafting it later would only add steps
and end in the same graph. What makes a skeleton a trap is structure nobody
could justify yet, made to look finished by fakes. The engine judges the result,
never the order: an early node that no slice ever needed stays `specd`, and a
fake on an active path is a waiver that holds its node back from `verified`.

## 8. Relationship to the rest of the engine

```text
- Substrate UNCHANGED: context assembler, drift validator, governance, growth rules.
- Only the ORCHESTRATION POLICY changes:
      unit of growth      = vertical slice (story), not a node
      implementation      = real along the path, fakes only at the frontier
      ordering            = hardest-first
- Ties:
      Layer-1 invariants  -> root nodes of the spec graph
      frontier stubs      -> GOVERNANCE.md §8 waivers
      status gating       -> GOVERNANCE.md §8/§9 (verified needs real evidence;
                            no silent drift)
```

## 9. Summary

```text
Architecture floor first. Features as small, real, working slices.
Hardest slice first. Fakes only at the frontier, never on the active path.
A node is verified only when a real slice has run through it.

Agility without erosion, increments without a late crash.
```
