# SPEC.md Template (per kind)

> Part of the Spec Growth Engine doc set. Defines the **one canonical structure**
> of a `SPEC.md`. Shared vocabulary (status, kind, gate levels) is canonical in
> [SPEC-GROWTH-ENGINE.md §3](SPEC-GROWTH-ENGINE.md).

## 0. The rule

Every **node** is a **`SPEC.md`** — one file type, one parser.
The level is declared by the field **`kind`** and is also visible from the
**directory depth**. There is no separate `CONTAINER.md` / `COMPONENT.md`.

```text
ARCHITECTURE.md  -> CROSS-CUTTING, NOT a node: invariants, principles, quality
                    goals, ADRs. Applies ACROSS the whole tree (fed into every spine).
System     -> root SPEC.md   (kind: system)   structural apex: "consists of containers"
Container  -> SPEC.md         (kind: container)
Component  -> SPEC.md         (kind: component)
Code       -> NOT a node: the files a component's `code` globs own -- generated
              from its spec and measured against it (drift, test evidence)
```

`ARCHITECTURE.md` is the one artifact that is **not** a node: no `kind`, no
`children`, no ownership ("consists-of") edge. It stands *beside* the tree and
constrains all of it. Everything else is a structural node.

## 1. Shared skeleton (identical for every kind)

```yaml
---
id:         # dotted path: container.component.subcomponent  (null-segment for root)
parent:     # the containing node = id minus last segment; null for the root
kind:       # system | container | component
contract:   # OUTWARD — what the node promises. Meaning varies by kind (see §2).
            #   acceptance_criteria = WHAT must be proven.
design:     # INWARD  — how it is fulfilled. Meaning varies by kind. Two sub-keys:
            #   approach      = how it is built.
            #   verification  = how the contract is proven (one line per check,
            #                   derived from acceptance_criteria). A check needing a
            #                   live credential/network is marked "runs only when
            #                   <ENV_VAR> is set, skipped otherwise" (offline-green).
depends_on: # other nodes this uses, BY THEIR CONTRACT (never their design/code)
code:       # globs of owned files, PROJECT-ROOT-relative (not relative to this
            #                   SPEC.md); broad at the top, narrow at the bottom
protected:  # optional. `protected: true` = a BREAKING change here is H's (5b).
            #   Declare a node whose consumers may sit OUTSIDE the graph (a CLI, an
            #   API, a file format) or that is high-stakes (auth, persistence,
            #   payment). A subtree property: declaring it on a container covers its
            #   descendants. A BREAKING contract change to a protected node is HARD;
            #   declaring it is SOFT, removing it is HARD.
status:     # specd | in-slice | implemented | verified
---

# <Title>
Prose for humans: why it is shaped this way, trade-offs, decisions.
```

The skeleton never changes. Only the **content of `contract`/`design`** differs
by level — that is the field profile below.

## 2. Field profile per kind

```text
kind       contract holds...                          design holds...               code
---------------------------------------------------------------------------------------------
system     purpose, external_actors, external_systems, children (= containers),     usually
           project acceptance                           ref to ARCHITECTURE.md       empty/broad
           (GLOBAL invariants/ADRs live in ARCHITECTURE.md, not here)
container  external surface: API endpoints / events /  children (= components),      dir glob
           store interface (protocol level)            runtime/tech
component  concrete function/interface signatures,     internal approach,            file glob
           error_behavior, acceptance criteria         optional sub-components
```

Specs end at the component. A single file with a contract of its own (a state
machine, a parser, a security or idempotency guard) is a SUB-COMPONENT that owns
that one file (§3.4) -- there is no `code` kind.

Same term, different level → different role. Example: data storage is a
**global invariant in ARCHITECTURE.md** ("persistence = PostgreSQL products table"),
the data **container's contract** ("provides read/write access"), and a
**component's signature** ("search(kw): Product[]").

## 3. Templates per kind

### 3.0 ARCHITECTURE.md — cross-cutting (NOT a node)

Carries the rules that apply across the whole tree. No `kind`, no `children`, no
ownership edge. Fed into every node's spine as the global invariants.

```markdown
# Architecture (cross-cutting)

## Invariants (hold everywhere)
- Persistence = PostgreSQL, table `products`. No data hardcoded in source.
- No copying of Amazon images, no scraping.
- Secrets only via env, never in code.

## Quality goals
- ...

## Decisions (ADRs)
- ADR-0001: monorepo
- ADR-0002: provider pattern
```

### 3.1 system — the root `SPEC.md` (structural apex)

Slim: system context + the containers it consists of. **No global invariants
here** — those live in `ARCHITECTURE.md`; this node references it.

```yaml
---
id: app
parent: null
kind: system
contract:
  purpose: "Curated product finder; search returns matching products."
  external_actors: ["End user"]
  external_systems: ["Amazon API (phase 2)"]
  acceptance_criteria: ["Search works end-to-end, verified locally."]
design:
  children: [web, api, data]        # the containers it consists of
  constraints: "see ARCHITECTURE.md (cross-cutting invariants + ADRs)"
status: specd
---

# System context
What the system does and how it splits into containers.
```

### 3.2 container

```yaml
---
id: data
parent: app
kind: container
contract:
  provides: ["ProductStore: read/write product data"]
  invariants:
    - "Single source of product data is the database."
    - "Implementation language is Python, managed with uv (this container's stack)."
    - "Code layout -- component `data.<name>` owns `src/data/<name>/**`;
       globs are project-root-relative."
  acceptance_criteria: ["Store is reachable; CRUD works."]
design:
  approach: "PostgreSQL."
  children: [data.store, data.ingest]
depends_on: [shared.types]
code: ["src/data/**"]
status: specd
---

# Data container
```

### 3.3 component

```yaml
---
id: data.store
parent: data
kind: component
contract:
  provides:
    - "search(keyword): Product[]"
    - "get(id): Product | null"
  invariants: ["Reads from the DB, never from hardcoded data."]
  error_behavior: ["get(unknown id) -> null, no throw."]
  acceptance_criteria: ["search returns DB rows.", "Tests green."]
design:
  approach: "Prepared statements, LIKE on title+keywords."
depends_on: [shared.types]
code: ["src/data/store/**"]
status: specd
---

# Product store
```

### 3.4 a sub-component for one file

Only for a single file with a non-obvious contract (state machine, parser,
security/idempotency guard). It is a component like any other, with its own
`SPEC.md` -- a header inside the code file is NOT read -- and it owns just that
file. Its parent's broader glob (`src/api/checkout/**`) gives the file up by itself:
on one ownership line the most specific owner wins.

```yaml
---
id: api.checkout.statemachine
parent: api.checkout
kind: component
contract:
  purpose: Enforces legal checkout status transitions.
  provides: ["transition(from, event): Status"]
  invariants:
    - "pending -> confirmed allowed."
    - "confirmed -> failed rejected."
depends_on: [shared.types]
code: ["src/api/checkout/statemachine.ts"]
status: specd
---
```

## 4. Conventions

```text
- id      = dotted ownership path (container.component.subcomponent).
- parent  = id minus the last segment; null for the root.
- kind    = the level; always set explicitly.
- A SPEC.md lives in its node's directory (data/SPEC.md, data/store/SPEC.md).
- `code` globs are PROJECT-ROOT-relative, NOT relative to that directory. So
  `data/SPEC.md` owning `["src/data/**"]` means `<root>/src/data/**`. The spec
  tree and the code tree are independent layouts (see CONCEPT §7a).
- The code LAYOUT is picked once per container and written into that container's
  contract.invariants; the Spine carries it down, so a component's globs are
  derived from it. `code: []` on a code-owning component is a defect.
- A component owns ITS OWN TESTS: its globs must cover them, or they are orphans
  and the gate blocks. Where tests live is part of the container's layout
  invariant, because it differs per language (CONCEPT §7a).
- Code files get NO SPEC.md; only the rare tricky file gets an inline header.
- depends_on points to nodes by id; you may rely only on the target's contract.
- `protected: true` marks a node H clears regardless of the autonomy switches: a
  BREAKING contract change to it is HARD even when nothing in the graph depends
  on it (AUTONOMY.md 5b). Use it where the consumers may sit OUTSIDE the graph --
  a CLI, an API, a file format -- or where a mistake is expensive (auth,
  persistence, payment). It covers the node's whole subtree, so declaring it on
  a container is usually enough. Declaring it is SOFT; removing it is HARD.
```

## 5. Summary

```text
One file type (SPEC.md). One skeleton. kind declares the level.
Same fields everywhere; their CONTENT follows the per-kind profile.
That keeps every level consistent without forcing system content into
component-shaped fields.
```
