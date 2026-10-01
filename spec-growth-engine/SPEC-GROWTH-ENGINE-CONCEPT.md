> Part of the Spec Growth Engine doc set. Shared vocabulary is canonical in
> [SPEC-GROWTH-ENGINE.md §3](SPEC-GROWTH-ENGINE.md). Companion docs:
> [GOVERNANCE.md](GOVERNANCE.md) · [LIFECYCLE.md](LIFECYCLE.md) · [CAPABILITY-REGISTRY.md](CAPABILITY-REGISTRY.md).

# Spec Growth Engine: Agile Spec-Graph for Coding Agents

Spec Growth Engine is a development method. The cockpit and its deterministic
modules are tooling that make parts of this method executable and enforceable.

## 1. Core idea

We do not want architecture as one large text blob.
We want a navigable spec graph that grows with the application.

The system starts tiny, for example with "Hello World":

```text
Context: app
+-- Container: web
    +-- Component: hello
        +-- Code: hello handler/view
```

Then every new feature grows this graph incrementally.
This is not Big Design Up Front. It is just-in-time specification.

The rule is:

```text
Do not specify the whole system in advance.
Specify the boundary that the current change creates or touches.
```

## 2. C4 still matters

We keep the C4 levels:

```text
Context   -> system boundary and external actors
Container -> deployable/runtime units
Component -> internal modules/components
Code      -> implementation files -- NOT a node here: what a component's spec
             generates and is measured against
```

But these levels are allowed to grow over time.

Examples:

```text
New external actor        -> Context grows
New deployable process    -> Container level grows
New internal module       -> Component level grows
New implementation file   -> Code mapping grows
```

## 3. Every node has two views

Each node has a double nature:

```text
Node
+-- contract  // outward: what the node promises
+-- design    // inward: how the node fulfills it
```

Contract:

```text
- public responsibilities
- interfaces
- types
- invariants
- error behavior
- acceptance criteria
```

Design:

```text
- internal approach
- children
- internal relations
- code ownership
- implementation constraints
```

Important visibility rule:

```text
Neighbors may read only the contract.
The parent may know the child design because the child is part of the parent's internal design.
```

This is Parnas information hiding applied to agent context.

## 4. Two edge types

The architecture graph has two different edge types.

### Ownership edges: tree

Ownership describes containment/decomposition:

```text
Context
+-- Container
    +-- Component
        +-- Component (nested, as deep as it needs to)
            ... owns its code files through its `code` globs
```

Each node has exactly one parent, except the root.

Meaning ("consists of / realized by"):

```text
Child is part of the parent's design (the parent CONSISTS OF its children),
AND the children's contracts SUM to the parent's contract
(the parent's promise is delegated to, and fulfilled by, its children).
```

This is why a split is contract-preserving: decomposing a node into children does
not change its outward contract — the children's contracts still sum to it.

The Spine follows ownership edges.

> Cross-cutting architecture (invariants, principles, ADRs) is NOT an ownership
> edge and NOT a node. It lives in a transversal `ARCHITECTURE.md` and applies
> across the whole tree (fed into every Spine). So "the system consists of
> containers" is pure structure; the global rules sit *beside* the tree, not above it.

### Dependency edges: DAG

Dependencies describe usage:

```text
checkout -> cart
checkout -> payment
checkout -> order
```

A node may have many dependencies.
Dependencies should be acyclic at the architecture level.

Meaning:

```text
N may use D's contract.
N may not use D's design or internal code.
```

Dependency context is one hop only.

## 5. The Spine

The Spine is the ownership path from root to the current node N:

```text
root -> ... -> parent -> N
```

It answers:

```text
Why does N exist?
Which higher-level promise does N support?
Which root invariant must N preserve?
```

The Spine is not the full parent specs.
It is a narrow chain of contracts, responsibilities, and relevant acceptance criteria.

Context for node N:

```text
Context(N) =
  RootInvariants
  + SpineContracts(root -> N)
  + N.fullSpec
  + Contracts(dependencies(N))
  + OwnCode(N)
```

Do not load:

```text
- sibling components
- dependency designs
- dependency code
- transitive dependencies
- whole-repository grep results
```

## 6. The context assembler

We need a context assembler over the graph.

Its job:

```text
Input:
  target node N

Output:
  deterministic context bundle for the coding agent
```

The coding agent should not decide by free search what to read.
The assembler gives the allowed context.

If the bundle is insufficient, the problem is reported as:

```text
- missing contract
- missing dependency edge
- missing ownership mapping
- unclear acceptance criterion
- stale spec/code alignment
```

The default fix is not "read more files".
The default fix is "repair the spec graph or contract".

## 7. Avoid file explosion

Do not create a separate spec file for every source file.

Default:

```text
One SPEC.md per node (system, container, component). Not per source file.
The field `kind` declares the level; code is owned by a component's globs and
is never a node of its own. See SPEC-TEMPLATE.md.
```

Files inside the component inherit the component spec.

File-level metadata is allowed only when a file has a non-obvious contract:

```text
- state machine
- policy
- adapter
- parser
- scheduler
- security boundary
- idempotency guard
```

Then use inline front matter in the code, not sidecar files.

Example:

```text
---
role: Enforces legal checkout status transitions.
contract:
  - Allows pending -> confirmed.
  - Rejects confirmed -> failed.
constraints:
  - Pure logic only.
depends_on:
  - CheckoutStatus
---
```

Rule of thumb:

```text
Components have specs.
Files have optional headers.
Functions have types and tests.
```

## 7a. The spec tree is NOT the code tree

Two rules that readers reliably trip over, because both look like something
else at first glance.

### `code` globs are PROJECT-ROOT-relative

```text
A node's `code` globs resolve against the PROJECT ROOT -- never against the
folder its own SPEC.md happens to sit in.
```

So this is consistent, and only because of that rule:

```text
data/SPEC.md          id: data     code: ["src/data/**"]
                                          ^ src/data/**, NOT data/src/data/**
```

The spec graph and the source tree are two independent layouts over the same
project. The ownership path (`data.store`) says where a node sits in the
ARCHITECTURE; the `code` glob says which files realize it. Nothing forces the
two to mirror each other -- a spec tree may live entirely in `spec/`, and the
code it owns entirely in `src/`, `apps/`, or a Maven `src/main/java` layout.

If globs were folder-relative, moving a SPEC.md would silently re-point its
ownership, and the spec layout would be dictated by the build tool's layout.
Root-relative globs make spec location a free choice.

### The code layout is a CONTAINER decision, not the coder's

A container is the technology boundary: one language, one build tool, one code
layout. That layout is written down as `contract.invariants` ON THE CONTAINER,
and the Spine carries it to every component below:

```text
container `cli` picks a layout convention (e.g. Java/Maven single module)
   -> seeded into cli's contract.invariants, with {container} -> cli
   -> "component `cli.<name>` owns cli/src/main/java/**/<name>/** ..."
   -> the Spine carries the container's invariants down
   -> the planner DERIVES each component's globs from it
```

### A component owns its own tests

```text
A test file that no node owns is an ORPHAN, and orphans block the gate. So the
component's globs must cover its tests -- which means the container's layout
invariant has to say where this language puts them.
```

Reproduced on an ordinary project with nothing brownfield about it: one
component owning `src/store/**`, one test at `tests/test_store.py`, and

```text
HARD errors: 1
  [x] orphan code (no spec owner): tests/test_store.py
```

This is not a case for excluding tests -- it is the opposite. A test is the
evidence that the contract holds, and per-node test attribution
(`engine/attribution.py`) uses ownership as its first route: a node that owns
its tests gets credit for them without any import analysis. Excluding them would
throw away both the check and the credit.

Where the tests sit is language- and project-specific (`src/test/java/**` for
Maven, co-located `foo.test.tsx` in React, inline `#[cfg(test)]` plus
`tests/*.rs` in Rust, a flat `tests/test_*.py` or a per-component `tests/<name>/`
in Python), which is precisely why it belongs to the container's layout decision
rather than to a global rule.

Consequences worth stating explicitly:

```text
- The layout is an explicit SPEC decision, made once, at container creation.
  It is not improvised per component by whoever writes the code.
- A system may be POLYGLOT: each container picks its own layout, so the
  convention cannot live at the root (ARCHITECTURE.md) -- it lives per container.
- A component's `code` is then DERIVED, not invented; `code: []` on a
  code-owning component is a defect, not a shortcut.
- Changing the layout is a contract change on the container, and it
  invalidates the derived globs of everything below it.
```

The engine stays language-agnostic: it never parses the layout, it only carries
the invariant prose down the Spine and checks the resulting globs against the
files that actually exist.

## 7b. Running inside a repository you do not own

The method grows a spec graph. Most repositories already contain code that no
graph describes. Two different situations get called "brownfield", and only one
of them is a problem.

### Coexistence — supported, and it needs nothing

```text
The SPEC ROOT is the SCAN ROOT. Point it at the subtree you are growing, and
code elsewhere in the repository is invisible to validate, drift and the gate.
```

```text
repo/
  legacy/              <- 11 files, no specs          ignored
  apps/newthing/       <- SPEC ROOT: grown by the method
    SPEC.md
    thing/SPEC.md
    src/thing.py
```

Measured: with the root at `apps/newthing`, `gate: pass`; with the root at the
repository root, `HARD errors: 11 -> gate: BLOCK`. Nothing about the legacy code
changed -- only what the engine was asked to look at.

This is the normal way to use the method in an existing system: the part you
grow is greenfield, the host repository is not, and the two do not interact
until you declare a dependency. Its limit is structural: it works while the new
code has a subtree of its own. Interleaved in one directory, a sub-root cannot
separate them.

### Adoption — bringing existing code under the graph

Pointing the root at a whole existing codebase reports every file as an orphan
and blocks. That is a real gap, but before closing it, note what adoption does
to the gate:

```text
The drift gate compares INTENT against EVIDENCE. Its value is proportional to
the INDEPENDENCE of the two.

Greenfield  intent exists first, code follows       -> the comparison means something
Adoption    the contract is written BY READING the code
                                                    -> the gate compares the code to a
                                                       restatement of itself; it passes
                                                       by construction
```

A contract reconstructed from code also restates that code's mistakes, and the
gate then faithfully protects the wrong thing. A C4 tree derived from the
existing directory layout declares the inherited structure to be the
architecture, which for old code is usually accidental rather than designed.

There is one case where adoption earns its cost, and it is the inverse one:

```text
When the contract states what the code SHOULD do rather than what it does, the
gate reports the gap immediately -- and that gap IS the work list.
That is modernisation, not documentation. It presupposes that someone has
already decided to restructure the system.
```

So: coexistence is the supported answer; adoption is worth its machinery only
when a restructuring is already intended.

## 8. The index must be generated

Do not manually maintain a global project.index.json.
That would create too much bookkeeping.

Humans and agents edit local sources of truth:

```text
- SPEC.md
- code
- short front matter
```

The framework generates:

```text
- project.index.json
- ownership edges
- code mappings
- dependency graph
- missing-contract warnings
```

Minimal framework commands could be:

```text
spec add component api.payment --parent api
spec depends api.checkout api.payment
spec index
spec validate
spec context api.checkout
```

The index is an artifact, not a hand-written document.

## 9. Agile growth rules

These rules run whenever we add or change something.

### Rule 1: Behavior rule

If a change adds observable behavior:

```text
1. Update the contract of the affected node.
2. Add or update acceptance criteria.
3. Add or update code and tests.
```

### Rule 2: Decomposition rule

If a node becomes internally structured or too large:

```text
1. Add the new child to the parent's design.
2. Create a minimal spec for the child if it is a real architectural boundary.
3. Add the ownership edge.
4. Map the child to its owned code.
```

### Rule 3: Dependency rule

If node N uses node D:

```text
1. Declare dependency N -> D.
2. Ensure D has a contract.
3. Allow N to read only D's contract.
4. Forbid N from reading D's design or internal code.
```

### Rule 4: Boundary rule

If a public promise changes:

```text
1. Update the contract.
2. Add or update acceptance criteria.
3. Find direct consumers.
4. Run or add contract/consumer tests.
```

### Rule 5: Internal design rule

If only the internal implementation changes:

```text
1. Update the node's design only if the design change is durable and meaningful.
2. Keep the contract unchanged.
3. Do not update neighbor specs.
4. Keep tests aligned with externally observable behavior.
```

### Rule 6: C4 promotion rule

If the change affects a higher C4 level:

```text
1. Update the highest affected node.
2. Add only the minimal new contract/design needed for the current change.
3. Do not pre-specify unrelated future components.
```

Examples:

```text
New user role       -> update Context
New worker process  -> update Context design and add Container
New auth component  -> update Container design and add Component
New state machine   -> update Component design and optional code-unit header
```

## 10. Bidirectional control

One-way generation is not enough.

We need:

```text
Specs -> Intent Graph
Code  -> Evidence Graph
Intent Graph <-> Evidence Graph validation
```

Intent Graph:

```text
- what the architecture claims
- nodes
- contracts
- ownership edges
- declared dependencies
- expected public surfaces
```

Evidence Graph:

```text
- what the code actually does
- files/modules/symbols
- imports
- exports
- calls
- routes
- tests
```

The system maps code to spec nodes:

```text
owner(code_node) -> spec_node
```

Then every code edge is projected to a spec edge:

```text
code edge: A.ts -> B.ts

owner(A.ts) = X
owner(B.ts) = Y

if X == Y:
  internal design edge

if X != Y:
  requires declared dependency X -> Y
```

## 11. Drift validation rules

The validator checks:

```text
1. Every relevant source file has exactly one spec owner.
   (Code globs are PROJECT-ROOT-relative: a spec node's location is independent of
   where its code lives; a node may own files anywhere, in several places.)
2. Every declared code file exists.
3. Every cross-owner import has a declared dependency edge -- EXCEPT edges along the
   ownership line: a parent (ancestor) using its descendant's code is REALIZATION
   ("the parent is realized by its children"), not a dependency, and is allowed
   without (indeed, may not have) a declared edge.
4. Cross-owner imports may use only the target's public surface.
5. No node may import another node's internal/private files.
6. Every dependency target must expose a contract.
7. Public exports/routes/events should be represented in the owning contract.
8. Acceptance criteria should have test evidence or an explicit waiver.
```

Hard errors:

```text
- orphan code
- undeclared dependency
- dependency bypasses contract
- ownership conflict
- missing dependency contract
```

Warnings:

```text
- declared dependency with no code evidence
- public export not mentioned in contract
- contract behavior without test evidence
- design mentions child but no code/spec evidence exists
```

## 12. What supporting tooling should implement

Tooling for the Spec Growth Engine method should provide:

```text
1. Spec parser
   Reads SPEC.md and front matter.

2. Code analyzer
   Builds the code evidence graph from files, imports, exports, calls, routes, tests.
   Import-edge detection is per language and resolves only to owned source files
   (edges to external/library code are ignored):
     - TS/JS  : relative specifiers + require()/dynamic import()
     - Java   : fully-qualified `import a.b.C;` + wildcard `import a.b.*;`
     - Kotlin : `import a.b.Name` resolved via package + top-level declarations
     - Dart   : relative/`part` directives + `package:<name>/...` -> lib/...
     - Python : `import a.b`, `from a.b import c`, relative `from .m import x`

3. Index generator
   Generates project.index.json from local specs and code evidence.

4. Drift validator
   Compares intended architecture with observed code structure.

5. Test runner
   Runs the node's project tests at its build root (the nearest ancestor with a
   build manifest: pom.xml / pyproject.toml / Cargo.toml / package.json /
   pubspec.yaml / Gradle). A passing run is the *test evidence* that acceptance
   criteria need and that gates `implemented -> verified` (see LIFECYCLE.md §5).
   It only selects and launches the project's own test command; it authors nothing.

6. Context assembler
   Builds the allowed agent context for node N.

7. Capability registry (horizontal reuse axis)
   A generated, searchable view over all `provides` contracts so the same
   capability is found and reused instead of re-implemented in another branch.
   Search-before-build heuristic, a duplicate detector (contract + signature +
   shared-external-dependency signals), and intent-level claims that catch
   concurrent-capability-creation. See CAPABILITY-REGISTRY.md.

8. GUI / IDE panel
   Shows current node, contract, design, dependencies, impact, drift, and context preview.
```

> **AGENT-NOTES.md (execution accelerator, NOT intent).** A coding agent may keep a
> transversal `AGENT-NOTES.md` at each build root with operational learnings (tool
> paths, setup steps, error workarounds) so repeated runs are faster. It is a
> *speed-up only*: NOT a spec node, NOT gated, NOT part of drift/ownership (the
> engine ignores it). Durable toolchain decisions (language, build tool) are
> intent and belong in `ARCHITECTURE.md`; only ephemeral exec know-how lives in
> `AGENT-NOTES.md`. It is irrelevant to the architecture and may be git-ignored.

## 13. Minimal GUI views

For agile work, do not start with a huge architecture workbench.
Start with node-first views:

```text
1. Current Node
   contract, acceptance criteria, design, code ownership

2. Context Bundle Preview
   what the coding agent will receive

3. Impact View
   who depends on this node's contract

4. Drift View
   where code and specs disagree
```

The raw spec files do not need to be pleasant to browse manually.
They must be:

```text
- machine-readable
- human-reviewable
- diff-friendly
- GUI-navigable
```

## 14. Development workflow

For each feature:

```text
1. Select the story or change.
2. Identify the affected node N, or create it.
3. Run the growth rules.
4. Update the minimal affected specs.
5. Generate the index.
6. Build Context(N).
7. Let the coding agent implement within that bundle.
8. Analyze code and rebuild the evidence graph.
9. Run drift validation.
10. Fix code or specs until intent and evidence align.
```

The graph grows with working software.

## 15. Main principle

The goal is not more documentation.

The goal is controlled context for coding agents:

```text
Small enough to fit.
Rich enough to preserve architectural meaning.
Strict enough to prevent hidden coupling.
Agile enough to grow one slice at a time.
```

Final summary:

```text
C4 gives zoom levels.
Contract/design gives encapsulation.
Ownership tree gives the Spine.
Dependency DAG gives one-hop integration context.
The context assembler limits what agents read.
The drift validator keeps specs and code aligned.
The growth rules keep the system agile.
```
