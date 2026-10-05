# Spec Growth Engine — Index & Canonical Glossary

> Entry point for the Spec Growth Engine method. Spec Growth Engine is a
> development process, not a single program. This file is the **single source of
> truth** for shared vocabulary (status, gate levels, shared nodes, roles).
> Every other document **references** these definitions instead of repeating them.
> If a term drifts, fix it here.

## 1. Document set

```text
SPEC-GROWTH-ENGINE-CONCEPT.md  — spec graph, C4 levels, contract/design,
                                 ownership tree + dependency DAG, Spine,
                                 context assembler, drift validation.
GOVERNANCE.md            — who may change what, under which gate.
LIFECYCLE.md             — vertical-slice growth + node status lifecycle.
CAPABILITY-REGISTRY.md   — horizontal reuse axis (anti-duplication).
AUTONOMY.md              — how much deciding is delegated to H' (three switches).
AGENTS.template.md       — operating manual for a coding agent working
                           under the method; rendered per project as AGENTS.md.
ORCHESTRATOR.template.md — manual for the intent author of a run; rendered per
                           project as ORCHESTRATOR.md.
TASK.template.md         — the shape of a run's goal and the method's standard
                           "Done means"; filled per project as TASK.md.
SPEC-TEMPLATE.md         — canonical SPEC.md structure + field profile per kind.
SPEC-GROWTH-ENGINE.md    — THIS file: index + canonical glossary.
```

| Concern | Owned by |
|---|---|
| Core model (graph, C4, Spine, assembler, drift) | `SPEC-GROWTH-ENGINE-CONCEPT.md` |
| Who changes what, gates, waivers | `GOVERNANCE.md` |
| Growth order, slices, status meaning | `LIFECYCLE.md` |
| Reuse, duplicate detection, capabilities | `CAPABILITY-REGISTRY.md` |
| Autonomy switches (draft gate D0..D2, delegation, run), what each delegates | `AUTONOMY.md` |
| How a coding agent works under the method | `AGENTS.template.md` |
| SPEC.md structure + per-kind templates | `SPEC-TEMPLATE.md` |
| Shared vocabulary (this glossary) | **this file** |

## 2. Core model in one screen

```text
The method treats architecture as a navigable SPEC GRAPH that grows with the
application.

C4 levels:        Context -> Container -> Component -> Code   (all SPEC.md + kind)
Cross-cutting:    ARCHITECTURE.md — invariants/principles/ADRs; NOT a node, applies to all
Two edge types:   ownership = TREE ("consists of")  |  dependency = DAG ("uses contract")
Two node views:   contract (outward)               |  design (inward)
Two context axes:
   VERTICAL   Spine + neighbors  -> "what must I conform to?"  (conformance)
   HORIZONTAL Capability Registry -> "what already exists?"    (reuse)

Grown by: deliberate invariants up front + agile vertical slices (hardest-first).
Kept honest by: a drift validator comparing intent (specs) to evidence (code).
```

## 3. Canonical glossary

### 3.1 Roles  *(elaborated in GOVERNANCE.md §1)*
```text
H  Human Architect   the goal, the zones, the switches; approves consequential changes;
                     grants waivers
I  Intent author     goal -> decomposition + an intent per node, and HOW the graph
                     grows to meet the goal: iteratively over slices, decomposed as
                     far as it is KNOWN, what is guessed left to the slice that
                     needs it (LIFECYCLE.md §6). H in the
                     cockpit; an agent in a run, which then asks P and C instead of
                     writing itself
P  Planner Agent     intent -> SPEC.md: drafts contracts/criteria/design
C  Coding Agent      implements one node; maintains its design + declared deps
H' Reviewer          judges what E cannot: reviews drafts, prepares HARD changes,
                     accepts the ones H delegated, checks a run's goal; in an
                     unsupervised run answers decision requests in H's place.
                     A model call, never a person -- that is H
E  Engine            derives, validates, enforces gates; authors NO intent
```
Each model-backed role (I, P, H', C) has its own model setting (GOVERNANCE §1).

### 3.2 Node kinds — CANONICAL  *(templates in SPEC-TEMPLATE.md)*
```text
system | container | component
   C4 calls the top level "System Context"; the node kind is `system`.
   Every node is one SPEC.md; `kind` declares the level.
   Specs end at the COMPONENT, and a component nests as deep as it needs to
   (core.rules.angle under core.rules). C4's fourth level, Code, is not a
   node: it is what is generated from a spec and measured against it -- drift,
   test evidence. Code without a spec is an orphan; a file with a contract of
   its own is a component that owns that one file.
   On one ownership line the most specific owner wins: a sub-component carves
   its files out of its parent's glob, which needs no narrowing by hand
   (engine/evidence.ownership_map). Owners NOT on one line conflict -- HARD.
```

```text
NOT ENFORCED. Nothing validates that `kind` holds one of these three values:
`kind: banana` parses and passes the gate. The three-value list in app.py
(KINDS) is a GUI combobox, not a rule. The change set reads an unknown kind --
`banana`, or the former `code` -- as HARD, fail safe. Contrast `status`, which HAS an
enforced enum (lifecycle.VALID_STATUS -> WARN on an unknown value).
So this line is a CONVENTION that the tooling relies on but does not check.
```

### 3.2a Code globs — CANONICAL  *(elaborated in SPEC-GROWTH-ENGINE-CONCEPT.md §7a)*
```text
A node's `code` globs resolve against the PROJECT ROOT, never against the folder
its SPEC.md sits in. Spec tree and code tree are independent layouts over the
same project: the id says where a node sits in the architecture, the glob says
which files realize it. Moving a SPEC.md therefore never re-points ownership -- which is what lets a
node be RENAMED (engine/nodes.rename_node) by moving its SPEC.md files alone.
```

### 3.2b Container code layout — CANONICAL  *(elaborated in CONCEPT §7a)*
```text
The container is the technology boundary: language + build tool + code layout.
The layout is written as contract.invariants ON THE CONTAINER (chosen once, at
creation) and carried down by the Spine, so a component's `code` globs are
DERIVED from it rather than improvised. A system may be polyglot -- each
container picks its own, which is why this cannot live in ARCHITECTURE.md.
```

### 3.2c File classification — CANONICAL  *(enforced in engine/drift.run)*

How a source file relates to the spec graph. Each class below is labelled
`BUILT` or `NOT BUILT`; no count is restated here, because a hand-maintained
derived number is wrong on average rather than occasionally -- this one said
"two" when three were built, then "three" when four were.

```text
BUILT
  owned    the file matches one node's `code` globs -- or several on one
           ownership line, and the most specific of them owns it
           -> engine/evidence.ownership_map
  orphan   an in-scope file no node owns          -> HARD  (drift.run)
  conflict the same file owned by >1 node NOT on  -> HARD  (drift.run)
           one ownership line -- on one line the most
           specific owner takes it (evidence.ownership_map)

  A `code` glob names the files that REALIZE a node, never the graph itself:
  claiming a SPEC.md or ARCHITECTURE.md is HARD. That is also what makes
  `code: ["**"]` detectable -- a glob broad enough to leave no file unowned
  sweeps up the spec tree with it. Claiming AGENT-NOTES.md (the coder's scratch
  memory) is a mistake rather than over-claiming, so it WARNs.
```

```text
BUILT
  excluded  a node declares PROJECT-ROOT-relative globs for files deliberately
            outside the graph: generated sources, project scripts, fixtures in
            the project's own language.
            -> engine/evidence.excluded_map, applied in drift.run

            Exclusion REMOVES, it never grants: an excluded file gets no owner,
            so it carries no contract and takes part in no import edge.
            A file both owned and excluded -> WARN, ownership wins.
            A glob matching nothing        -> WARN (a typo stops meaning
                                              anything, silently, otherwise).
            A glob of nothing but wildcards ("**", "*", "**/*") -> HARD. An
                                              exclusion must say WHICH files are
                                              outside the graph; one line would
                                              otherwise switch off the orphan
                                              check, which is a HARD check.
            More excluded than owned       -> WARN.
            Every report counts them ("excluded: 2 file(s) via 1 declaration(s)")
            because exclusions are permanent: unseen, the field becomes the quiet
            way to make the gate stop complaining.

  Two hardcoded exclusions remain, for things no project should have to declare:
    evidence.EXCLUDED_DIRS   build output and vendored trees: node_modules,
                             dist, build, out, bin, target, .git, .venv, venv,
                             __pycache__, .pytest_cache, .idea, .gradle,
                             .dart_tool, .sge
    drift._IGNORE_FILES      SPEC.md, ARCHITECTURE.md, AGENT-NOTES.md

  EXCLUDED_DIRS is applied when GLOBS ARE RESOLVED, so build output is never
  owned. The property that forces this: a node's ownership must not change
  because its tests were run -- `src/foo/**` starts matching
  `src/foo/__pycache__/*.pyc` the moment they are. Spec files are deliberately
  NOT in that list: claiming one is an authoring mistake, not an accident of
  timing, so it stays visible and is reported above.
```

```text
NOT a case for `excluded`: TESTS. A component owns its own tests -- a test is
the evidence the contract holds, and attribution credits an owned test without
any import analysis (CONCEPT §7a). Excluding tests throws away both.
```

```text
OUT OF SCOPE -- not-yet-specified (adopting a whole existing codebase)
  There is deliberately no "this file is not under spec YET" class. Adoption
  would write the contract BY READING the code, so the drift gate would compare
  the code against a restatement of itself and pass by construction -- it would
  protect the wrong thing. Not built because it is not wanted, not a backlog
  item (CONCEPT §7b).

  The supported way to run inside a repository you do not own is the SUB-ROOT:
  the spec root is the scan root, so pointing it at the subtree you are growing
  hides the rest.

  Consequence worth knowing: "you forgot to declare this import" and "this
  module is not migrated yet" report as the same HARD orphan. In scope there is
  no second case -- an unowned file is always a defect.
```

`shared` is NOT a file class -- it is a property of a NODE, described in 3.6.

### 3.3 Contract vs Design  *(elaborated in SPEC-GROWTH-ENGINE-CONCEPT.md §3)*
```text
contract  OUTWARD — what the node promises. Neighbors may read ONLY this.
          provides, interfaces, types, invariants, error_behavior, acceptance_criteria
design    INWARD  — how it is fulfilled. Only the node's implementer + its parent.
          approach, children, internal relations, code ownership, constraints
```

### 3.4 Edges: ownership vs dependency  *(elaborated in SPEC-GROWTH-ENGINE-CONCEPT.md §4)*
```text
ownership (TREE)  "consists of / realized by"; exactly one parent; the children's
                  contracts SUM to the parent's contract; defines the Spine.
dependency (DAG)  usage; "N may use D's CONTRACT, never D's design/code";
                  acyclic at the architecture level; one-hop context only.
NOTE: cross-cutting architecture (ARCHITECTURE.md) is NEITHER edge — a transversal
      layer (invariants/ADRs) that applies across all nodes, not a node (see 3.11).
```

### 3.5 Spine  *(elaborated in SPEC-GROWTH-ENGINE-CONCEPT.md §5)*
```text
The ownership path root -> ... -> parent -> N.
The minimal "whole" a leaf needs: root invariants + each ancestor's contract/role.
Vertical axis. Narrow by design. NOT the dependency edges.
```

### 3.6 Capability  *(elaborated in CAPABILITY-REGISTRY.md)*
```text
A node's `provides` contract viewed as a reusable unit, with a stable id
(e.g. cap:pdf-to-text). Lives in the SHARED layer. Exactly ONE providing node;
two providers = a duplicate. Found by query (the Registry), not by reading.
```

```text
SHARED is a property of the NODE, not a class of file: a node is shared if it
sets `shared: true` or has `shared` as a segment of its id (a.shared.log).
-> engine/capability.build_registry
It is computed for the REGISTRY view only. It changes nothing about ownership,
drift or the gate -- a shared node owns its files like any other node.
```

### 3.7 Vertical slice  *(elaborated in LIFECYCLE.md)*
```text
A thin path through the tree (Context->...->Code) + needed dependency edges,
implemented FOR REAL end-to-end. The unit of growth. Real on its active path;
fakes only at the frontier; hardest slice first.
```

### 3.8 Status enum — CANONICAL  *(lifecycle in LIFECYCLE.md §5)*
```text
specd  ->  in-slice  ->  implemented  ->  verified

specd        contract + acceptance criteria exist; no real code
             (a frontier stub also sits here, flagged by a frontier-stub
              waiver; 3.10 blocks it from reaching implemented/verified)
in-slice     a live slice is building this node's REAL behavior (transient)
implemented  real code exists, satisfies contract, local tests pass
verified     a real slice exercised it end-to-end; criteria have test evidence;
             NO open waivers
```
A node's status may not be ahead of its children: `verified` with an unverified
child is a HARD error, anything else ahead of a child is a WARN (LIFECYCLE §5-).

There is no `faked` status. Fakes exist only as `frontier-stub` waivers,
which keep a node at `specd` and block `verified`.

### 3.9 Gate levels — CANONICAL  *(applied in GOVERNANCE.md §3, §5)*
```text
HARD  human approval required before merge
SOFT  agent may proceed; async human review; auto-approve if policy checks pass
AUTO  no human; engine policy decides
NONE  fully autonomous
```

### 3.9a Autonomy switches — CANONICAL  *(elaborated in AUTONOMY.md)*
```text
the draft gate (a grade; the cockpit slider) -- who clears a drafted SPEC.md
  D0 Assist       H clears every gate (baseline)
  D1 LLM-review   H' reviews P's drafts, surfaces findings; H decides (advisory)
  D2 LLM-clear    H' may clear SOFT gates; HARD + protected zones stay with H
the delegation (on | off, per project) -- who accepts a pending HARD change
  on              H' may accept the HARD changes H delegated: a breaking change
                  to a consumed component contract, once E finds it migrated;
                  zones stay with H, who can overrule
the run (off | on | unsupervised; an operating mode, not a level) -- who authors
node intent
  on              I is an agent: it derives node intents from H's goal and
                  has P and C do the rest; H sets goal, zones, switches.
                  What is above a node waits for H
  unsupervised    as on, and H' answers what is above a node between rounds,
                  in H's place -- each answer an ADR that waits for H's review;
                  needs the delegation on
```
Orthogonal to the gate level (3.9): the gate says how much is at stake, the
switches say who may clear it. The deterministic floor blocks whatever they say.

A node marked `protected: true` (SPEC-TEMPLATE §1) is H's whatever the switches say: a
BREAKING contract change to it is HARD, because its consumers may sit OUTSIDE the
graph (a CLI, an API, a file format) or because it is high-stakes (auth,
persistence, payment). A subtree property -- declaring it on a container covers
its descendants (AUTONOMY.md §5b).

### 3.9b Accepted state — CANONICAL  *(mechanics in AUTONOMY.md §4)*
```text
The last state of each node's spec -- and of ARCHITECTURE.md -- that someone with
the authority accepted. A change is measured against it when there is no Save to
measure against (an agent writing files). -> engine/accepted.py, .sge/accepted.json

  accepted by   E on a passing gate: every change at SOFT or below -- the gate
                  (engine/gate.py) runs as `cli.py gate`, the git hook, the
                  cockpit's Validate > Gate, and inside a goal check and every
                  round of a run; the cockpit's report shows each change it
                  cleared, with its diff
                H' at D2: the SOFT drafts it cleared
                H' (delegation on): a pending HARD change inside the scope H delegated,
                  migrated -- waits for H to confirm or overrule
                H: anything, HARD included (cli.py accept, cockpit Save)
  pending       a HARD change nobody accepted. Blocks nothing; its node, and the
                consumers of a broken contract, are at most `implemented`.
  brief         H' preparing a pending change (recommendation, risks,
                alternatives); advisory, bound to the change (AUTONOMY 5c)
  rejected      H decided against this exact change, with a reason: a HARD error,
                the gate blocks until the node is restored or changed otherwise.
```
Opt-in: a project without the file tracks nothing, and `accept ROOT --all` starts.

### 3.10 Waiver — CANONICAL  *(rules in GOVERNANCE.md §8)*

*Formerly "exception". Renamed because the word collides with programming
exceptions, and the collision was total in the case that motivated the model:
ARCHITECTURE.md required "errors are raised as exceptions", a component
deliberately raised none, and that deviation needed "an exception". A waiver is
the established engineering term for a formal, time-boxed permission to deviate
from a requirement. A leftover `exception:` field is a HARD error, not ignored.*

```text
typed (pending-external-evidence | known-gap | deferred-test | frontier-stub),
and in one of two states:

  requested   a deviation someone -- an agent included -- needs, with a reason.
              Grants nothing. Visible on every run until H decides.
  granted     a deviation H has accepted: owned by a person, time-boxed.

A node with any unresolved waiver, requested or granted, is at most
`implemented`, NEVER `verified`, and does not count as done.
```

Requesting and granting are separate acts because run 02 showed what one act
does: an agent that had to deviate from a global invariant, and was not allowed
to write a waiver, deviated anyway and described it in prose — no owner, no
expiry, invisible to the gate. Forbidding the record did not prevent the
deviation. A request records it; a grant accepts it.

```text
ENFORCED by engine/waivers.issues, run on every `validate`:
  state        missing or unknown -- never implied         -> HARD
  typed        kind not one of the four                    -> HARD
  requested    no reason                                   -> HARD
               otherwise reported, awaiting H              -> WARN
  owned        a GRANT with no owner                       -> HARD
  time-boxed   a GRANT with no expiry, or an unparseable one -> HARD
  expired      a GRANT past its date                       -> HARD
  expiring     within 14 days                              -> WARN
  not done     `verified` with any unresolved waiver    -> HARD
  frontier     frontier-stub at implemented/verified       -> HARD
Both states appear in the validate header on every run. project.index.json
excludes every unresolved waiver from `progress.done`.
```

A missing `state` is an error rather than a default. Reading it as `granted`
would make the permissive value the one you get by writing nothing.

```text
NOT enforced by the gate: that a GRANT came from H. Authorship is not a property
of the file. It is enforced at the authoring end for the planner:
agent/planner._clean_waiver downgrades anything it drafts to `requested` and
removes owner and expiry, in both `draft` and `revise`; a revise also keeps an
existing grant verbatim. For a coding agent editing YAML directly, "only H
grants" is a rule of the manual, not of the gate.
```

### 3.10a Decision request — CANONICAL  *(rules in GOVERNANCE.md §8)*
```text
A question for H about a decision ABOVE the asker's authority: an architectural
decision (target: ARCHITECTURE.md) or a change to a node the asker may not grow
itself -- the root, a container, anything H gave (target: that node's id).
NOT a node the asker grows: between two of its own nodes the instrument is a
revise, not a question. Recorded on the node that needs the decision, with
target, proposal and reason. Grants nothing. A node with a pending request is
at most `implemented` and does not count as done.

H resolves it by changing the target and deleting the request. A rejection is a
deletion too, optionally recorded as an ADR. In an UNSUPERVISED run H' resolves
it in H's place, between rounds: it accepts or rejects it as worded, records the
answer as an ADR naming itself -- a change to ARCHITECTURE.md, so HARD, and H's
to accept or take back -- and deletes the request (AUTONOMY.md §3).

  decision_requests:
    - target: ARCHITECTURE.md | <node id>
      proposal: <the decision, worded as it should appear in the target>
      reason: <why it is needed>
```

Not a waiver: a waiver is a deviation from a rule that EXISTS; a decision
request is a decision that does not exist yet. Choosing a GUI toolkit from the
standard library breaks no rule — it is simply undecided.

Why it exists: in an unattended run "ask instead" has nobody to ask. Run 02's
agent needed a toolkit decision and a wider container contract, could edit
neither, recorded the toolkit choice nowhere, and bent its design to fit the
wording of the container contract it was not allowed to change.

```text
ENFORCED by engine/decisions.issues, run on every `validate`:
  shape      target, proposal and reason present            -> HARD
  target     ARCHITECTURE.md or an existing node, not itself -> HARD
  visible    each pending request, and the header line       -> WARN
  not done   `verified` while a request is pending           -> HARD
NOT enforced: that H changed the target before deleting the request. The deletion
is the resolution; git history is the audit.
```

### 3.11 Cross-cutting architecture (`ARCHITECTURE.md`)  *(template in SPEC-TEMPLATE.md §3.0)*
```text
Transversal constraints that apply across the WHOLE tree: global invariants,
principles, quality goals, decisions (ADRs). NOT a node: no kind, no children,
no "consists-of" edge. Fed into every node's spine as the global invariants.
Local (node-specific) invariants stay in that node's own contract.
```

### 3.12 The goal (`TASK.md`) — CANONICAL, for a RUN and the goal check

```text
The goal, in prose, written by H: what is wanted, and how "done" would be
recognised. It is the INTENT AUTHOR, written down -- needed exactly when a
machine plays that role and cannot ask H at the moment an intent is written.
```

A person working the cockpit needs none: the goal is in their head and leaves
it one node at a time, as the intent they type. An orchestrated run (AUTONOMY.md,
the run) needs one, because `codex exec` runs unattended and has nobody to ask.
So does the GOAL CHECK -- H' judging the project against it, without a run --
for whoever wants to know whether the goal is met.

```text
lives      NEXT TO the spec root, never inside it. No node, no frontmatter.
           The gate does not know it: no drift check, no evidence, no accepted
           state -- it is the run's yardstick, not part of the graph.
read by    I, to grow the graph; H', to check the goal after a round
           (agent/reviewer.check_goal) -- or when H asks, with no run and no
           agent: the goal check (orchestrate.check; the cockpit's Build >
           Check Goal, `cli.py check ROOT`), E's floor first, H' on a green
           one; H, to change what is wanted
kinds of   three, and a task states them however it likes -- often under
statement  headings like "What it must do", "What must hold", "Done means",
           sometimes as plain prose with no headings at all:
             what it must DO           per command or behaviour, with examples
             what must ALWAYS be true  spanning all of them
             what DONE means           the state the work must reach
measured   by TWO instances, and the kinds say which. What DONE means is mostly
by         what E checks anyway -- tests recorded and green, a passing gate, a
           status that was earned -- and carries the one line E cannot check:
           that every behaviour has a test that would FAIL if it broke. That
           line and the other two kinds are what H' judges: does the graph
           cover them? A vague sentence does not make the check lenient; it
           makes it empty.
not        a specification. A behaviour written here binds nothing; the same
           sentence in a contract is enforced. Wishes here, facts there.
```

It is the one document in the chain that nothing verifies: code is measured
against tests, tests against acceptance criteria, specs against code -- and the
task against the graph by E for what E can count and by H' for the rest, at the
end of a round or when H asks for the goal check. Change it and nothing flags
which specs now contradict it; the next goal check is where that surfaces.

## 4. Single-source-of-truth rule

```text
- The status enum (3.8), gate levels (3.9), autonomy switches (3.9a), waiver
  model (3.10), roles (3.1), node kinds (3.2), code-glob resolution (3.2a),
  container code layout (3.2b), file classes (3.2c), decision requests
  (3.10a) and the goal (3.12) are defined HERE and nowhere else.
- Other documents must REFERENCE these (e.g. "status — see SPEC-GROWTH-ENGINE
  §3.8"), not restate them.
- If a definition changes, it changes here; the references stay valid.
```

This is the same discipline the engine enforces on code (one owner, no
duplication) applied to the documentation set itself.

## 5. Two layers, and which one a document belongs to

Everything here serves one of two purposes. Telling them apart answers most
questions about where a rule, a file or a feature belongs.

```text
LAYER 1   spec-code divergence -- the engine
          artefacts   SPEC.md, ARCHITECTURE.md, .sge/
          actors      E and H; P, H' and C as helpers
          switches    D0-D2 (who clears a DRAFT), the delegation on | off (who
                      accepts a pending HARD change)
          nature      DETERMINISTIC and enforceable, or it does not belong here
          needs       no TASK.md, no agent, no run: a person and the cockpit
                      are a complete use of it

LAYER 2   agent-driven development -- a run
          artefacts   TASK.md (3.12), the rendered manuals, the run records
          actors      I as an agent; H' checking the goal; the round rule
          switch      the run, which is not a level but an operating mode: what
                      is delegated is the AUTHORSHIP of intent, not a gate
          nature      JUDGEMENT is allowed here, because layer 1 measures the
                      result afterwards
          needs       layer 1 -- as its floor and as its witness
```

The claim the second layer rests on: **an autonomous run is worth only as much
as the deterministic instance that measures it afterwards.** An agent that says
DONE proves nothing; a gate that blocks, a test that is recorded and a change
set that says what moved are what make the claim checkable.

The first layer does not need the second. The second cannot exist without the
first.

## 6. Reading order

```text
1. SPEC-GROWTH-ENGINE-CONCEPT.md       the model                        layer 1
2. LIFECYCLE.md                        how it grows (slices, status)    layer 1
3. GOVERNANCE.md                       who changes what, gates, waivers layer 1
4. CAPABILITY-REGISTRY.md              how reuse is kept under control  layer 1
5. SPEC-TEMPLATE.md                    how to write a SPEC.md (per kind) layer 1
6. AUTONOMY.md                         how much is delegated -- D0-D2, the
                                       delegation, and the run as an
                                       operating mode                    both
6a. AGENTS.template.md                 hand this to a coding agent      layer 2
6b. ORCHESTRATOR.template.md           hand this to an intent author    layer 2
6c. TASK.template.md                   what a run's goal looks like     layer 2
7. SPEC-GROWTH-ENGINE.md (this file)   look up any shared term
```
