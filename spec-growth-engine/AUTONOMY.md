# Autonomy — three switches: the draft gate, the delegation, the run

> Part of the **Spec Growth Engine** method. This document defines **how much of
> the human's judgement may be delegated to an LLM deputy (H′)**, switch by
> switch, and what had to exist before each could be switched on.
> Canonical roles: [SPEC-GROWTH-ENGINE.md §3.1](SPEC-GROWTH-ENGINE.md) ·
> gate levels: [§3.9](SPEC-GROWTH-ENGINE.md) · who may change what:
> [GOVERNANCE.md](GOVERNANCE.md).

## 0. Why this exists

The gates (HARD / SOFT / AUTO / NONE) say *how consequential* a change is.
They do not say *who* is allowed to clear them. In a one-person project with an
agent doing most of the typing, "the human decides everything" is a bottleneck;
"the agent decides everything" is how architectures rot silently.

Autonomy is set between those two with three switches, because three different
things can be delegated. Each is explicit, and none moves on its own.

```text
gate level  = how much is at stake in this change        (property of the change)
autonomy    = how much of the deciding is delegated      (three switches, §2)
```

## 1. The invariant — true whatever the switches say

```text
The DETERMINISTIC FLOOR always runs and always BLOCKS.

  validate   structure, ownership, spine conformance
  drift      specs vs. real code (orphans, undeclared deps, missing globs)
  lifecycle  status vs. recorded test evidence (no fake completion)

H′ judges only what E CANNOT check: altitude, intent placement, testability,
reuse, intent fidelity. H′ NEVER overrides E. Turning a switch up delegates
judgement, it never lowers the floor.

Every H′ decision — cleared or escalated — is appended to .sge/autonomy.jsonl.
```

This is what makes the switches safe to turn: a wrong H′ decision can waste a
round, but it cannot merge a drifting or falsely-`verified` graph.

## 2. The three switches

```text
THE DRAFT GATE -- who clears a drafted SPEC.md before it is saved (a grade)
  D0  Assist       H clears every gate.                                (baseline)
  D1  LLM-review   H′ reviews P's drafts, surfaces findings; H decides. (advisory)
  D2  LLM-clear    H′ may clear SOFT gates by itself;
                   HARD + protected zones stay with H.

THE DELEGATION -- who accepts a PENDING HARD change on disk (on | off)
  off              H does, every one.                                  (default)
  on               H′ may accept the HARD changes H delegated: a breaking change
                   to a consumed component contract, once E finds it migrated.
                   Zones, containers, ARCHITECTURE stay with H.

THE RUN -- who authors node intent (off | on | unsupervised; an operating mode)
  off              H does, in the cockpit.
  on               the intent author I is an agent: it derives node intents
                   from H's goal and has P and C do the rest. H sets the goal,
                   the zones and the other two switches. What is above a node
                   waits for H: the run ends `asking`, H answers, a new run
                   builds on it.
  unsupervised     as on, and nobody waits: between rounds H′ answers the
                   decision requests in H's place and decides what the
                   delegation lets it. H reviews every answer afterwards.
                   Needs the delegation on.
```

Reading it as a sentence: at **D0** you decide, at **D1** you decide with a
second opinion, at **D2** you decide the consequential half; with the
**delegation on** you draw the boundaries and H′ decides the migrations inside
them; with a **run on** you say where you want to go; with a run
**unsupervised** you say where, and look afterwards at what was decided on the
way.

The delegation is not a grade above D2 but a yes/no to one question: may H′
accept a pending HARD change itself? A draft is not on disk and cannot be
migrated, so the question never arises for it -- which is why the slider ends at
D2 and the delegation is a switch of its own. A run is not a level at all: it is
how a project is operated, with the other two switches wherever H left them.

## 3. Switch by switch

### D0 — Assist

```text
H′            not involved.
H decides     every gate, as in a project without an LLM deputy.
Use when      the graph is young, or the domain is one you do not want
              a model forming opinions about yet.
```

The engine is still useful here: validate, drift and lifecycle run exactly as
at every other setting. D0 turns off the *deputy*, not the *tooling*.

### D1 — LLM-review (advisory)

```text
H′ does       read the drafted SPEC.md against the intent, the architecture and
              the capability registry, and report findings with a verdict
              (approve / revise / reject), a confidence, and a severity per finding.
H′ may NOT    save anything, or clear any gate.
H decides     everything, now with a second opinion in front of it.
Risk          none beyond a wasted read — nothing happens without a human click.
```

H′ deliberately does **not** re-check what E already enforces. Duplicated
checking would train you to skim the findings.

### D2 — LLM-clear (SOFT gates)

```text
H′ may clear  SOFT gates on its own — today: the DRAFT gate (accept a drafted
              SPEC.md), and only when the engine's change set for it is SOFT or
              below (§5a).
H′ may NOT    clear HARD gates, or touch anything in a protected zone.
Escalates to H on:
              - a HARD change set: breaking a consumed or outward contract, a new
                container or root, an id/kind/parent change, the root contract,
                a waiver grant (engine.changeset, checked before the verdict and
                again after every revise round)
              - a draft that does not parse, so cannot be classified
              - verdict "reject"
              - any finding of severity "blocker"
              - confidence below the threshold (0.6)
              - a declared protected zone hit (see §5b)
              - more than 2 revise rounds
              - the planner or the reviewer being unavailable
After clearing, the deterministic gate STILL runs. A blocked auto-save is
reported, never swallowed.
Risk          bounded: SOFT changes are reversible and locally scoped, and
              anything that blocks comes back to you anyway.
```

The revise loop is the useful part: on verdict `revise`, P applies the findings,
H′ re-reviews, at most twice — then it is your problem again, with the history
attached.

### The delegation — H′ accepts delegated HARD changes (on | off) — *built*

```text
H′ may        accept a PENDING HARD change (engine/accepted.py) when ALL hold:
  scope       it is a breaking change to a COMPONENT's contract, HARD only
              because accepted nodes in the graph consume it
              (engine.autonomy.delegable_scope). Never: a protected zone (5b), a
              container or the root, ARCHITECTURE.md, a new node, a deletion,
              an id/kind/parent change, a waiver grant -- those stay H's.
  migrated    E finds the node and every accepted consumer tested AFTER the
              change -- green, with tests attributed to each, and no consumer
              still naming an operation the node no longer provides at all
              (engine.migration.check). A reworded entry that keeps its name --
              a new signature -- is not removed: consumers keep calling it, and
              their tests after the change show whether they call it right.
              This is GOVERNANCE §7's "one transaction over D + its consumers",
              checked.
  brief       H′'s fresh brief recommends accept, at confidence >=
              AUTO_ACCEPT_CONF (the same fixed guard as D2 -- a guard, not a
              measurement).
H keeps       the zones and the switch itself; and every acceptance by H′ waits
              for H's review: confirm (accept) or OVERRULE (reject, with a
              reason) -- the node's accepted spec returns to what it was and the
              gate blocks until the node is restored (engine.accepted.overrule).
Where         `cli.py decide ROOT` -- an explicit step, never the gate, which
              stays offline and deterministic. The agent may run it; it cannot
              steer it: scope and migration are E's, the brief is a separate
              model call that sees the earlier brief on the node (so a cosmetic
              edit does not buy a fresh opinion blind).
Set by        H only: `cli.py delegate ROOT on` (<root>/.sge/autonomy.json).
              Default off.
```

**Why no statistics.** The delegation could be framed as a grant earned by a measured track
record: how often H′ matched H. That was built once and removed. With the
numbers such a record would realistically hold, it proves little (0 errors in
30 cases bounds the error rate only below ~10%), it measures whether H′ predicts
H rather than whether it is right, and it rewards an H who accepts everything.
It is instead a DELEGATION: H decides to delegate, and the delegation is bounded
by structure -- zones H declares, a migration E checks, a recommendation H′
must make, and an overrule H can always issue. The log is there to be READ.

**The limit that remains.** Green consumer tests prove only what those tests
exercise: an invariant tightened where no consumer test looks passes "migrated".
That is why migration is a precondition for H′'s judgement and never a
substitute for it, and why the zones exist.

### The run — an orchestrated run (off | on | unsupervised) — *built as an operating mode*

```text
Earlier draft   "H′ derives the intent itself from a stated goal". Built otherwise:
                not the judge, but a role of its own -- I, the intent author
                (GOVERNANCE §1). A judge that writes the intent it judges is no
                judge.
I (an agent)    turns H's goal (TASK.md) into a decomposition and a node-level
                intent per node -- and writes NO spec and NO code: it asks P
                (`cli.py draft | revise`) and C (`cli.py code`). It runs as a
                `codex exec` agent; its manual is ORCHESTRATOR.md.
P, C, H', E     as everywhere else. Each model-backed role has its own endpoint
                -- URL, key, model -- in cockpit/.env; the separation of I, P
                and C is what makes that possible.
H sets          the goal, the start state, the zones and the other two switches
                -- and keeps
                everything above node level: root, containers, ARCHITECTURE.md.
Started by      the cockpit's Start a run..., or `cli.py run ROOT
                [--unsupervised]` -- in any project directory
In rounds       cockpit/orchestrate.py: one `codex exec` session of I is one
                round; the rule after it is engine/iteration.py (below)
```

**Rounds.** One session ends when the model stops calling tools -- after a
slice, after a failure it gave up on, or because it believes it is done. The
prompt alone ("work until the task is done") made a run that stopped after one
slice look like a finished one. So a run goes in rounds, and after each one
the run itself checks:

```text
E     records the tests and runs the gate: the FLOOR
H'    on a green floor only: checks TASK.md -- every statement of what the
      system must do, what must always be true and what done means, however
      the task words them (SPEC-GROWTH-ENGINE.md 3.12) -- against what E
      computed: every node's spec, the tests, the pending HARD changes
      (agent/reviewer.check_goal). It names GAPS, one line each, WHAT is
      missing and never how to close it -- and, apart from them, what is
      WAITING: unmet only because it rests on a decision only H may make (an
      open request, a HARD change outside the delegation). A gap goes back to
      I; what waits does not, because I cannot close it. It does not see what
      I said about its own work, and it is asked about the gaps it named last
      round before it looks for new ones.
E     decides, deterministically (engine/iteration.py):

  the session failed                 stop    error
  a resumed round did no work        stop    stalled    I only talked: H decides
  the floor is red                   resume             with E's failures; H' is not asked
  floor green, H' names gaps         resume             with the gaps
  floor green, no gap, something     stop    asking     H answers; then a new run
    waits for H
  floor green, H' names no gap       stop    done
  floor green, H' unavailable        stop    unchecked  if I said DONE; else resume
  a resume past the round limit      stop    limit      the open gaps are H's to read

  I ended with BLOCKED: <why>        measured all the same. Green, no gap, and
                                     something waits for H: `asking` -- waiting
                                     for H is not being blocked (run 12). Any
                                     other case: `blocked`, and H reads why.
```

To resume is `codex exec resume <session>`: the SAME session, with its memory
of the run, told which round it is and what is missing. I ends its last message
with `DONE` or `BLOCKED: <reason>` (ORCHESTRATOR.md "When you stop"); `DONE` is
a claim, never the verdict. In the goal check H' can keep a run going, or let it
end on a green floor -- it accepts nothing there, and every run ends with H's
review. (Unsupervised, H' also decides in H's place, between rounds -- below.) A gap I thinks
wrong is not argued round after round: I says why and ends with `BLOCKED`, and
H decides; a resumed round that runs no command ends the run as stalled.
`MAX_ROUNDS` caps the cost; `MAX_ROUNDS=1` is a run without rounds.

A run breaks the rule that *agents author no intent*, for node-level intent
only; GOVERNANCE §6 states the exception and its bounds. It is an operating mode,
not a value anyone sets on a slider or in `.sge/autonomy.json`.

**Unsupervised.** A supervised run stops at the first thing only H may decide
that nothing else can go on without -- and in practice that is early: runs 09,
11 and 12 ended with 2, 9 and 6 questions for H. Unsupervised, H′ stands in for
H between rounds (engine/unsupervised.py):

```text
after every measured round, before the goal is checked:
  requests    H′ answers each open decision request -- accepts or rejects it AS
              WORDED, never rewords it (agent/reviewer.answer_request) -- and
              the answer is recorded as an ADR naming H′, the request removed
              (engine.inbox.decide_in_hs_place). Unsure (confidence below
              AUTO_ACCEPT_CONF) or unreachable: the request stays open for H.
  delegated   H′ decides the pending HARD changes inside the delegation, as
              `cli.py decide` would.
then E:
  an answer the work must follow     resume   a rejection, an acceptance for a
  (engine.unsupervised.rework)                node -- or any answer, when I said
                                              BLOCKED: it waited for exactly that
  otherwise                          the rule above, with what H′ left open
                                     counted as waiting
```

Every answer stays H's to review, and nothing new was built to make it so: the
ADR is a change to ARCHITECTURE.md, which is HARD and outside the delegation, so
it waits in H's pending list until H accepts it -- or rejects it, and the gate
blocks until the work is taken back. An accepted request for a node is not
merged into that node: it is prose. The ADR authorises the change, and I makes
it through P -- which is what lets an unsupervised run change a file H gave it,
and only that change.

This is the second exception to *agents author no intent* (GOVERNANCE §6), and
the only one above a node: H′ chooses among answers it did not write. It is why
unsupervised is a setting of its own, chosen per run, and why it needs the
delegation on -- otherwise every HARD change piles up for H, and the run stands
in for H everywhere except where it matters most. What stays H's even here:
TASK.md, the zones H declared, and every answer, afterwards.

**Limits.** Nothing but the manual keeps I from writing a spec or a file
itself: it runs with approvals and sandbox bypassed, and a shell can write
anything. The run's stream (`codex exec --json`) records every command and
every file change, which is where a breach would show. And the agent's node
intents are the one thing no gate checks -- H reads them in the specs P wrote
from them. The goal check is the reviewer's judgement, not a proof: it reads the specs
and the tests, not the behaviour, so a gap it misses is found by H or not at
all -- and a gap it invents costs a round, or ends the run as BLOCKED.

## 4. What is implemented today

Every claim below names the code that backs it, and `tests/test_docs_claims.py`
fails if a named symbol does not exist or a quoted constant disagrees. This
section is therefore checkable, not merely written down (see 8).

```text
claim                                       backed by
------------------------------------------- ---------------------------------
H' itself (the review)                      agent.reviewer.review_draft
D1: findings shown, human decides           app.Cockpit._review
D2: the decision, one step                  engine.autonomy.decide
D2: the bounded revise loop                 engine.autonomy.clear_draft
D2: applied in the cockpit                  app.Cockpit._d2_draft
D2: accept -> save                          app.Cockpit._d2_accept
D2: reject/low confidence/zone -> human     app.Cockpit._d2_escalate
D2: a HARD change set -> human              app.Cockpit._assess
which gate a SPEC.md change falls under     engine.changeset.classify
who the change reaches (5a)                 engine.changeset.impact
HARD change on manual Save -> confirm       app.Cockpit.save_spec
headless: changes vs. the accepted state    engine.accepted.changes
E accepts <= SOFT on a passing gate         engine.accepted.clear
H accepts a HARD change                     engine.accepted.accept
a pending HARD change holds `verified`      engine.accepted.issues
H rejects: the gate blocks, with the reason engine.accepted.reject
5c: H' briefs a pending HARD change         agent.reviewer.brief_hard_change
5c: the brief, bound to the change          engine.assist.prepare
5c: H decides; the log records the brief    engine.assist.decide
delegation: the scope H delegates          engine.autonomy.delegable_scope
delegation: the rule                        engine.autonomy.delegated_decide
delegation: migrated, E's precondition      engine.migration.check
delegation: the step, `cli.py decide`       engine.assist.delegated
delegation: read, old form included         engine.autonomy.delegated
delegation: switched by H                   engine.autonomy.set_delegation
delegation: H switches it in the cockpit    app.Cockpit._on_delegation
delegation: H overrules an acceptance by H' engine.accepted.overrule
headless test evidence, `cli.py test`       cli.cmd_test
one model per role: P / H'                  agent.llm.reviewer_model
run: P drafts a node for I                  cli.cmd_draft
run: P revises a spec for I                 cli.cmd_revise
run: C implements a node for I              cli.cmd_code
run: rounds -- the session, resumed         orchestrate.run
run: H' checks the goal against TASK.md     agent.reviewer.check_goal
run: the rule -- stop, or resume            engine.iteration.decide
run: started in the cockpit                 app.Cockpit.start_run
run: what it needs before it can start      orchestrate.blockers
run: its stream, one line per event         runlog.lines
run: what waits for H, apart from the gaps  engine.iteration.waiting
unsupervised: H' answers a request          agent.reviewer.answer_request
unsupervised: every open request answered   engine.unsupervised.answer
unsupervised: recorded as an ADR H reviews  engine.inbox.decide_in_hs_place
unsupervised: which answers send I back     engine.unsupervised.rework
unsupervised: H's place, between rounds     engine.unsupervised.stand_in
unsupervised: chosen when a run is started  app.RunDialog
declared protected zone (5b)                engine.changeset._protected_above
declared zone -> D2 escalates               engine.autonomy.decide
audit log                                   engine.lifecycle.log_autonomy
```

```text
constants (quoted here, checked against the code)
engine.autonomy.DRAFT_MAX = 2
engine.autonomy.AUTO_ACCEPT_CONF = 0.6
engine.autonomy.AUTO_MAX_ROUNDS = 2
engine.iteration.MAX_ROUNDS = 5
```

So: **the slider offers D0, D1, D2 (the draft gate); the delegation is a
switch per project, for pending HARD changes; a run is an operating mode
(Start a run... in the cockpit, or `cli.py run`), on or unsupervised, not a
level anyone sets.**

### The honest size of it

```text
The switches are read at few places, and their entire effect is:

  the slider (D0..D2)   at D2 a drafted SPEC.md is saved without you clicking
                        Save -- if the engine classifies the change as SOFT or
                        below -- and the deterministic gate still runs on it.
  the delegation        when on, `cli.py decide` -- or the same step between the
  (on | off)            rounds of an unsupervised run -- may accept a pending
                        HARD change inside delegable_scope that E found
                        migrated and H' recommends.
  the run               on, an agent authors node intent, in rounds;
  (off | on |           unsupervised, H' also answers its decision requests
   unsupervised)        between rounds, each as an ADR H reviews.

Everything else -- validate, drift, lifecycle, the change set, the accepted
state, the capability registry, the duplicate report, test evidence, the index,
the commit hook -- ignores both and behaves identically whatever they say.
```

### Headless: the accepted state

```text
An agent writes SPEC.md files and runs the gate. There is no Save to ask at, and
no slider: the gate applies the gate levels as GOVERNANCE §3 defines them --
SOFT is auto-approved when the policy checks pass, HARD waits. That is D2's
line, drawn by E instead of H'.

Measured against     .sge/accepted.json -- each node's spec as last accepted,
                     and ARCHITECTURE.md (glossary §3.9b)
E                    on a PASSING gate, accepts every change at SOFT or below
H                    accepts HARD: `cli.py accept ROOT ID`, or Save in the cockpit
                     (which measures against the same state, so a HARD change an
                     agent left pending is part of what H is asked about)
H' (delegation on)   accepts HARD inside delegable_scope: `cli.py decide ROOT` (§3)
pending HARD         blocks nothing -- the agent keeps working -- but the node and
                     the consumers of a broken contract cannot be `verified`, and
                     progress does not count them. `cli.py pending` lists them.
evidence             `cli.py test ROOT` records it headless, stamped with the
                     run's START -- what "migrated" is checked against
untracked            no file, no tracking: exactly the behaviour before it.
```

### Not wired to any switch

```text
duplicate consolidation   capability.duplicates is a REPORT (cockpit
                          "Capability > Duplicates", cli.py duplicates). It tells
                          a human to consolidate; H' never clears it, whatever
                          the switches say. An earlier version of this document
                          claimed D2 auto-cleared it. It never did.
```

The draft gate is stored in `cockpit.json` as `draft_gate` -- one setting for
the cockpit, not per project -- and capped by the slider at `DRAFT_MAX`. The
delegation lives in `<root>/.sge/autonomy.json` as `{"delegation": true | false,
"by", "at"}`.

## 5. What the delegation needed before it could be built

Three things were missing, in dependency order. All three are built, and so is
the delegation on top of them (§3).

### 5a. Change-set and consumer impact — *built* (`engine/changeset.py`)

```text
Problem   "breaking contract change" is a HARD gate, but nothing computed WHO
          breaks -- nor even WHETHER a change was HARD. D2 therefore auto-saved an
          approved draft that removed an operation its consumer calls, and one
          that created a new container: nothing but the keyword scan stood
          between an approved draft and the disk.
Built     classify: the gate a proposed SPEC.md falls under, with every reason.
            new container / root, id / kind / parent, root contract,
            waiver grant                                           -> HARD
            breaking contract change (provides removed or reworded,
            any other promise changed)   -> HARD if a node depends on it or the
                                            node is a container/system; else
                                            SOFT (nobody can break yet)
            provides only added, criteria, code globs, new component -> SOFT
            depends_on, status                                     -> AUTO
            design, prose, a waiver request                        -> NONE
          impact: the declared consumers, which of them MENTION a removed
            operation (spec + owned code), and which evidence was recorded
            against the old contract.
Wired     D2 escalates a HARD change set whatever H' said; Save asks H to
          confirm a HARD one with the report in front of it; Draft and Revise
          show the report. Same report whatever the switches say.
Limits    - "breaking" is read off TEXT and fails safe: an invariant cannot be
            told apart as tightened or widened, so any change to one breaks.
          - "which expectations the diff violates" is approximated by a name
            search. A consumer is listed whenever it DECLARES the dependency; a
            mention is extra evidence, no mention is not proof of safety.
          - held, not blocked: headless, a HARD change stays pending against
            the accepted state (§4) and keeps its nodes from `verified`; it is
            never refused. Stale evidence is named but not invalidated, and
            GOVERNANCE §7's "BLOCK until migrated" is not built.
```

### 5b. Protected zones, declared instead of guessed — *built* (`engine/changeset.py`)

```text
Problem   high-stakes detection was a keyword scan over the intent and the draft
          ("secret", "auth", "token", ...), matched on word boundaries
          (engine.autonomy.ZONE_PATTERNS). It failed in BOTH directions:
          - FALSE ALARM: "a spec authoring tool", "authentic", "tokenize" and
            "schematic" all escalated, and each false alarm skips D2 silently,
            making auto-clear rarer than the slider suggests.
          - MISS: a crypto or persistence component using none of these words.
          The deterministic gate had the same blind spot from the other side: a
          breaking contract change to a component that nothing in the graph
          depends on read SOFT, even when its real consumers sit OUTSIDE the
          graph. Run 03 hit it -- svc.cli's promise changed, no in-graph consumer
          existed, E accepted it, and H never saw it.
Built     `protected: true` in a SPEC.md marks a node -- and, because the walk
          goes up `parent`, its whole SUBTREE -- as H's to clear: a boundary
          whose consumers may sit outside the graph (a CLI, an API, a file
          format), or a high-stakes node (auth, persistence, payment).
          engine.changeset derives `change['protected']` from the spec and the
          BEFORE graph (a marking removed in the same edit still counts, fail
          safe), and two consumers read it:
            - a BREAKING contract change to a protected node is HARD, exactly
              like a container's (engine.changeset._contract_diff); deleting one
              is HARD too. So headless E no longer auto-accepts it.
            - at D2 the draft escalates to H (engine.autonomy.decide) whatever
              its gate: the decision the keyword scan was standing in for.
          Declaring protection is SOFT; REMOVING it is HARD -- a guard only ever
          tightens on its own.
Where     `changeset.classify` is the one place, so headless, Save, D2 and the
          briefs all see the same gate.
Limits    - this is a DECLARATION, not a detector: an undeclared outward
            component is still read SOFT. The change set no longer stays SILENT
            about it -- it says "nothing depends on it and it is not declared
            protected: if its consumers sit outside the graph, add
            `protected: true`" -- and acting on that is H's. The keyword scan's
            false alarms are gone; so is its accidental coverage.
          - `protected` states the CONSEQUENCE (a BREAKING change here is H's,
            in this node and everything below it -- additions, a status and
            prose clear as usual; the zone raises the gate, it does not freeze
            the node), not the
            reason. Why the node is protected -- outward surface, high stakes,
            or both -- belongs in its prose.
```

### 5c. Assisted-HARD as the intermediate step — *built* (`engine/assist.py`)

```text
Idea      before H′ CLEARS a HARD gate, let it PREPARE one: the change set, the
          affected consumers, the risks, the alternatives, the recommendation —
          and a single Approve / Reject for the human.
Value     the human keeps the decision and loses the homework. With the
          delegation on, the brief is also what H' acts on, inside the scope H
          delegated (§3).
Built     prepare   H' (agent.reviewer.brief_hard_change, injected) gets the
                    engine's facts -- change set, consumers, mentions, stale
                    evidence -- and both specs, and returns a brief:
                    recommendation (accept | reject), confidence, summary, risks,
                    alternatives. Bound to the change's FINGERPRINT (accepted +
                    current spec): once the node changes again it is STALE.
          decide    H accepts, or rejects WITH A REASON. The log records the
                    brief H had (recommendation, confidence) -- as a fact; nothing
                    counts it. Every brief is logged when it is prepared.
          reject    bound to the fingerprint, a HARD error: the gate BLOCKS with
                    H's reason until the node is restored or changed otherwise.
                    It is how H's "no" reaches an unattended agent.
Where     cockpit Requests window (Prepare / Accept change / Reject...), and
          cli.py prepare | pending | accept | reject. Every run ends with
          `prepare` (orchestrate.after), so the homework is done when H looks.
Limits    - H' sees specs and the change set, not the code: "does the consumer
            really use it" is the engine's name search, not a reading by H'.
          - a track record ("how often H' matched H") was built here once and
            removed: the delegation is H's act, not a measured grant (§3).
```

Order: **5a → 5c → 5b**, all done. 5a is pure computation and paid off
immediately; 5c builds directly on it; 5b replaced the keyword guard once a human
was no longer in the loop on every HARD gate -- and closed the headless hole
where an outward component with no in-graph consumer was auto-accepted.

## 6. Audit trail

```text
.sge/autonomy.jsonl    append-only, one JSON object per decision
                       H' at D2:
                       { at, node, draft_gate: 2, verdict, confidence, gate,
                         action: auto-saved | auto-saved-blocked | escalated,
                         revise_rounds (auto-saved), reason (escalated) }
                       gate = the change set's gate; null when the draft
                       did not parse, so could not be classified.
                       the accepted state (§4) and the delegation (§3):
                       { at, actor: E | H' | H, by, node, gate,
                         action: cleared (E) | accepted (H, H') | rejected (H)
                                 | overruled (H),
                         reason (rejected, overruled, H' delegated),
                         brief: {recommendation, confidence} | null }
                       { at, actor: H', by, action: briefed, node, fingerprint,
                         recommendation, confidence }
                       { at, actor: H, by, action: delegation,
                         delegation: true | false }
                       { at, actor: P, by: model, action: drafted | revised,
                         node, gate }                  (cli.py draft | revise)
                       { at, actor: C, by: command, action: coded, node, exit }
                       a run's rounds:
                       { at, actor: H', by: model, action: goal-checked, gaps,
                         waiting, closed }             (counts)
                       { at, actor: H', by: model, action: request-accepted |
                         request-rejected, node, target, proposal, confidence,
                         reason }                      (an unsupervised run)
                       { at, actor: E, action: round, mode: on | unsupervised,
                         round, claim, floor, gaps, next: resume | stop,
                         outcome: done | asking | blocked | stalled | error
                                  | unchecked | limit | null }
                       { at, actor: H, by, action: accepted-all, nodes }
```

Next to it, `.sge/intents.jsonl` is the GROWTH record: every intent a node was
drafted or revised from, with its author (I or H) and the planner's model --
the steps of which the specs are the result (engine/intents.py, `cli.py
intents`). H' reads a node's history when it prepares a HARD change on it.

One use: reading, after the fact, what was decided while you were not looking --
above all what H' accepted under the delegation, which waits for your confirmation or
overrule (`cli.py pending`, the Requests window), and, after an unsupervised run,
every request H' answered in your place: the ADRs it wrote wait in the same
list, as a pending change to ARCHITECTURE.md. The log is read, not scored:
nothing in the engine counts it.

## 7. Where it is set

```text
Cockpit slider  the DRAFT gate, D0..D2 (cockpit.json -> "draft_gate").
                It ENDS at D2: a draft is not on disk, so it cannot be migrated
Delegation      pending HARD changes, on | off: <root>/.sge/autonomy.json, set
                only by H -- `cli.py delegate ROOT on|off`, or the cockpit's
                own switch beside the slider (asked for once; revocable) --
                default off. A separate control because it is a separate
                decision: the slider says who clears the draft in front of you,
                this says who accepts a HARD change already on disk, in THIS
                project
CLI / gate      the gate applies SOFT auto-approve / HARD pending (§4) whatever
                the switches say and never calls a model; `decide` (delegation
                on), `prepare`, and for the intent author `draft`, `revise` and
                `code` are the steps that do
A run           off | on | unsupervised, chosen when it is started: the
                cockpit's Start a run..., or `cli.py run ROOT [--unsupervised]`.
                Unsupervised needs the delegation on. Which endpoint plays I,
                P, H', C is cockpit/.env (a value in the environment wins),
                recorded per run -- models and URLs, never keys -- in
                <root>/.sge/runs/NN.roles; the round limit (default
                engine.iteration.MAX_ROUNDS); how the run ended is the last
                lines of <root>/.sge/runs/NN.log
```

## 8. This document is not covered by the drift gate

Worth saying out loud, because it is the method's own blind spot.

```text
validate / drift / lifecycle compare SPEC.md intent against real code --
IN THE TARGET PROJECT. There is no spec graph over the METHOD itself, so
nothing watches these documents. The guard has no guard.
```

Consequence: a section here can be detailed, cite real function names, and still
be wrong in its central claim -- which is exactly what happened. Section 4 once
described an auto-clear for duplicate consolidation that was never built,
while correctly naming the draft-gate functions around it.
Precision about the parts is not evidence about the whole.

What exists instead, as a partial substitute:

```text
cockpit/tests/test_docs_claims.py
   - every code symbol named in 4 must resolve
   - every constant quoted in 4 must equal the value in app.py
   A renamed function or a changed threshold fails the test suite.
```

What it does NOT cover -- read 4 with this in mind:

```text
- a claim that names no symbol (prose is unchecked)
- a feature that exists but is not wired up the way the text implies:
  the symbol resolves, the sentence around it can still be false
- sections 3, 5, 6, 7, and every other method document
```

Trust 4 on names and numbers. Verify anything else against the code.
