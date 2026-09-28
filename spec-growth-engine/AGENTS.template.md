# How to work in this repository

> Part of the **Spec Growth Engine** method: the operating manual for a CODING
> AGENT working under it. Copy this file to the root of a project as `AGENTS.md`
> and replace the `{{...}}` placeholders. Everything outside the "This project"
> block is generic and should be copied verbatim — it is the method, not the
> project.
>
> Placeholders: `{{SGE_CLI}}` `{{SPEC_ROOT}}` `{{CONTAINER}}` `{{TEST_CMD}}`
> `{{GIVEN}}` `{{CODE_DIR}}` `{{TEST_DIR}}` `{{METHOD_DOCS}}`

## This project

```text
spec root       {{SPEC_ROOT}}
container       {{CONTAINER}}          you grow COMPONENTS inside it
your code       {{CODE_DIR}}
your tests      {{TEST_DIR}}
given to you    {{GIVEN}}
                do not edit these -- request a decision instead (see below)
```

Run the tests with:

```sh
{{TEST_CMD}}
```

Run the gate with:

```sh
{{SGE_CLI}} gate {{SPEC_ROOT}}
```

Read `TASK.md` for what to build. Read the rest of this file for how.

## The method itself — read this before you start

This file is a summary. The method it summarises is written down, and you can
look anything up:

```text
{{METHOD_DOCS}}/
  SPEC-GROWTH-ENGINE.md            THE GLOSSARY. Every shared term is defined
                                   here and nowhere else: node kinds, statuses,
                                   gate levels, edge types, code globs.
                                   Read §3 before you start -- it is one screen.
  SPEC-GROWTH-ENGINE-CONCEPT.md    The model. Read §3 (contract vs design),
                                   §4 (the two edge types) and §7a (the spec
                                   tree is not the code tree) before you start.
                                   Those three are where agents go wrong.
  SPEC-TEMPLATE.md                 The canonical SPEC.md structure, with a
                                   worked example per kind. Consult when writing.
  LIFECYCLE.md                     What each status MEANS and what earns it.
  GOVERNANCE.md                    Who may change what. §8 says why you may not
                                   grant yourself a waiver.
  CAPABILITY-REGISTRY.md           Reuse: when a capability already exists.
```

Minimum before your first SPEC.md: the glossary §3, and CONCEPT §3, §4, §7a.
When the gate blocks you and the message is not enough, the rule behind it is in
one of these — look it up rather than guessing.

## The one rule everything else follows from

```text
The SPEC comes first, and the code is what realizes it.
Never write code for a node that has no SPEC.md, and never leave a SPEC.md
describing something the code does not do.
```

A deterministic tool checks most of what follows and will refuse your work if
you break it. The rules are not style advice.

## The loop — one component at a time

Do these in order, for ONE component, before starting the next.

```text
1. WRITE THE SPEC FIRST   a SPEC.md for the component; status: specd
2. GATE                   it must pass before you write any code
3. CODE + TESTS           inside the globs your SPEC.md declared
4. TESTS                  they must be green
5. GATE                   again; fix the SPEC or the code, never the gate
6. STATUS                 set it to `implemented`
```

Small components, finished one at a time, beat a wide half-built tree.

## How to write a SPEC.md

```yaml
---
id: <container>.<name>      # dotted path: parent id + one segment
parent: <container>
kind: component
contract:                   # OUTWARD: what others may rely on
  purpose: "One sentence: why this exists."
  provides: ["count_words(text) -> dict[str, int]"]
  invariants: ["Never mutates its input."]
  acceptance_criteria: ["Empty input returns an empty result."]
design:                     # INWARD: yours alone, nobody may depend on it
  approach: "A dict accumulator over a regex split."
  verification: "Unit tests over ASCII, unicode and empty input."
depends_on: [<container>.<other>]   # nodes whose CONTRACT you use
code: ["<code glob>", "<test glob>"]
status: specd
---

# <Name>

Prose for humans: why it is shaped this way, trade-offs, what was rejected.
```

### The five rules the gate enforces

**Contract vs design.** `contract` is what neighbours may rely on; `design` is
how you do it and nobody may depend on it. Putting HOW into the contract is the
most common mistake: "uses a regex" is design; "splits on word boundaries" is a
contract only if callers can observe it.

**`code` globs are PROJECT-ROOT-relative.** Relative to the spec root, never to
the folder your SPEC.md sits in. This is why a SPEC.md may live anywhere.

**A component owns its own tests.** Your globs must cover them, or they are
orphan files and the gate blocks. The container's invariants say where tests go
in this language.

**`depends_on` is a USAGE edge.** It names nodes whose contract you call. Never
your parent, never your own children, never yourself — that is ownership, not
usage, and the gate rejects it. If your code imports another component's code,
`depends_on` must say so; if it says so and no import exists, that is a warning.

**Status is earned.** `specd` → `implemented` → `verified`. `verified` requires
recorded test evidence, so do not set it by hand: leave nodes at `implemented`
unless told otherwise.

## Forbidden

These make the gate green without making the work right. Using any of them
invalidates the run.

```text
- widening a `code` glob so an unowned file stops being an orphan
- `excluded:` for anything that is not GENERATED or a project script
  (never for tests, never a bare wildcard)
- writing `state: granted` on a waiver — only the human architect grants
- lowering a status to dodge a check
- editing the files given to you
- deleting or weakening a test to make it pass
```

If the gate blocks you and the only way past it is one of these, **stop and say
so**. A blocked gate you cannot resolve honestly is a finding, and reporting it
is worth more than a green run.

## When you must deviate from a rule

Sometimes the right design breaks a rule — a global invariant that does not fit
one component, a test that cannot exist yet. Do not hide that in prose. **Request
a waiver** on the node that deviates:

```yaml
waiver:
  state: requested
  kind: known-gap            # pending-external-evidence | known-gap | deferred-test | frontier-stub
  reason: "What deviates, from which rule, and why the deviation is the better design."
  proposed_expiry: 2026-12-31   # optional: when it should be revisited
```

A request grants nothing. The gate reports it on every run until the human
architect decides, and the node cannot become `verified` meanwhile. Never write
`owner`, `expires` or `state: granted` — those are the decision, and the decision
is not yours.

## When a decision is above you

Some decisions are not yours to make: an architectural choice (a toolkit, a
dependency, a convention) belongs in `ARCHITECTURE.md`; what a container provides
belongs in the container's contract. You may edit neither, and in an unattended
run there is nobody to ask. Do not decide it silently, and do not bend your
design to fit wording you cannot change. **Request the decision** on the node
that needs it:

```yaml
decision_requests:
  - target: ARCHITECTURE.md          # or the id of the node above you, e.g. the container
    proposal: "ADR: <the decision, worded as it should appear in the target>"
    reason: "<why this node needs it, and what you considered instead>"
```

Then build on the proposal as if it were accepted. The gate reports every pending
request on every run, and the node stays at `implemented` until the human
architect decides. This is not a waiver: a waiver is a deviation from a
rule that exists; a decision request is a decision that does not exist yet.

## When your change is HARD

The gate compares the graph with the last **accepted** state. When it passes, it
accepts every change at SOFT or below by itself: a new component, an operation
added to a contract, new acceptance criteria, code globs, your design. A HARD
change is not blocked, but it is not accepted either. The gate reports
`HARD CHANGE PENDING` on every run until it is accepted -- by the human
architect, or, where the project delegates it, by an independent reviewer (see
"When the project delegates" below):

```text
- removing or rewording what a contract provides, or changing any other promise
  in it (invariants, error behaviour), when an accepted node depends on it or
  the node is a container
- a new container; any change to ARCHITECTURE.md or to the root's contract
- changing a node's id, kind or parent; deleting a node others depend on
- a BREAKING change to a node declared `protected: true`, or inside such a
  subtree, even when nothing in the graph depends on it: its consumers may sit
  OUTSIDE the graph (a CLI, an API, a file format), or it is high-stakes
```

Keep working. Until it is accepted, the changed node — and every consumer of a
contract you broke — stays at `implemented`. A pending change is not a failure:
if a contract is wrong, change it, and do not leave a flaw you know of in place
only to avoid a pending change. Prefer the change that is not HARD when it is
equally right:
add the new operation next to the old one rather than replacing it. When a
removal is really needed, migrate the consumers first; the removal still waits
for acceptance, but then nothing breaks while it waits. This shows what is
pending and whom it reaches:

```sh
{{SGE_CLI}} pending {{SPEC_ROOT}}
```

The gate does not catch every edit to a given file — adding to a given
container's contract is SOFT and would be accepted. The rule above still holds:
do not edit the given files; request the decision.

`protected: true` is H's declaration, not yours. A breaking change to a protected
node is HARD, and **removing** the marking is HARD too: never remove it to get a
change through. Request the decision instead.

If the human **rejects** a HARD change, the gate blocks with
`HARD CHANGE REJECTED` and their reason. Restore the accepted spec — `pending`
prints it — or change the node in a different way; either lifts the block. A
different change is simply pending again.

### When the project delegates

`{{SGE_CLI}} delegate {{SPEC_ROOT}}` says who decides pending HARD changes. With
the delegation on, the human architect has delegated one kind of them: a breaking change to a
component's contract that other components use. Such a change can be accepted
without waiting, once it is **migrated**:

1. change every consumer so it no longer uses what you removed or changed;
2. record the tests -- running pytest yourself records nothing:

```sh
{{SGE_CLI}} test {{SPEC_ROOT}}
```

3. then ask for the decision:

```sh
{{SGE_CLI}} decide {{SPEC_ROOT}}
```

`decide` accepts the change only if the changed node and every consumer were
tested after the change, no consumer still names an operation the node no
longer provides (a changed signature under the same name is fine), and an
independent reviewer recommends it. Otherwise it says why, and the change keeps
waiting. Protected nodes, containers, ARCHITECTURE.md, new containers,
deletions and changes to id, kind or parent are never decided this way. The
human architect can still overrule an acceptance later; the gate then blocks
with `HARD CHANGE REJECTED`, as above.

Never run `accept`, `reject` or `delegate ... on|off` yourself. That is the decision, and the
decision is not yours.

## What the gate does NOT check

A green gate means the graph is *shaped* legally. It does not mean the work is
good. It cannot see:

```text
- whether the contract promises anything worth promising
- whether your tests actually test the behaviour
- whether the decomposition makes sense
- behavioural invariants ("never reads the network")
```

`gate: PASS` is the floor, not the goal.

## When you stop

End your **last message** with a line of its own:

```text
DONE                  the task is done, as far as you can tell
BLOCKED: <reason>     you cannot go on honestly -- the run stops for H
```

A run may go in **rounds**: when you stop, the tests are recorded, the gate is
run, and a reviewer checks the task's "Done means" against the specs and the
tests. If something is missing, you are resumed in the same session and told
what. `DONE` is a claim, not the verdict. A gap you think is wrong is not
argued round after round: say why and end with `BLOCKED:`. A round in which
you run no command ends the run as stalled.

## Reuse before building

Before adding a component, check whether its **capability** — the thing its
contract promises, seen as a reusable unit — already exists somewhere:

```sh
{{SGE_CLI}} duplicates {{SPEC_ROOT}}
```

If something close exists, depend on its contract instead of writing it again.

## Notes to your future self

Durable operational knowledge — a tool path, a setup step, an error workaround —
goes in `AGENT-NOTES.md` at the build root (the nearest directory above your
code that holds a build manifest — where the tests run). It is a speed-up only: never intent,
never a contract. Decisions about language or tooling belong in
`ARCHITECTURE.md`, which is given to you — request them (see above).
