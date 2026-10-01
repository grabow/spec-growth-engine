# Spec Growth Engine - Cockpit

The cockpit is the runnable tool for the Spec Growth Engine method. It provides
a guided desktop UI and CLI over deterministic checks for SPEC.md graphs. The
method itself lives in `../spec-growth-engine/`.

ASCII-based; `.md` file extensions are kept, but no markdown rendering is used
(plain `tk.Text`).

## Layout

```
engine/    deterministic tool core (authors NO intent)
  parser.py    load SPEC.md nodes + ARCHITECTURE.md
  graph.py     ownership tree (parent) + dependency DAG (depends_on) + Spine
  context.py   Context(N): ARCHITECTURE + Spine + node + dep-contracts + own code
  validate.py  structural checks (spec-side intent graph)
  evidence.py  code evidence graph (TS/JS/Java/Kotlin/Dart/Python imports -> owner nodes)
  drift.py     drift gate: code edges vs declared depends_on (no silent drift)
  lifecycle.py status lifecycle: `verified` requires test evidence (no fake completion)
  changeset.py change set: the gate a SPEC.md change falls under + consumer impact
  accepted.py  the accepted state a headless change set is measured against
  assist.py    assisted HARD: H' briefs a pending HARD change, H decides, log keeps score
  autonomy.py  the switches as code: the D2 decision, the delegation and its rule
  index.py     generate project.index.json (graph + capabilities + edges + evidence)
  capability.py  registry view + search + duplicate detector + claims (reuse axis)
  nodes.py     node CRUD: create / delete SPEC.md, sync parent.children
agent/     AI roles (separate from the engine), one model setting per role
  llm.py       shared LLM plumbing + one endpoint per role (URL, key, model)
  codex_cli.py I and C as `codex exec` agents on their own endpoints
  semantic.py  optional re-ranker + duplicate judge on the planner's model (injected)
  reviewer.py  role H': advisory review of a Draft at the SOFT gate (D1), the
               brief of a HARD change, and a run's goal check (the model: SGE_REVIEWER_*)
  planner.py   role P: intent -> SPEC.md draft (Draft) AND spec + change -> revised
               spec preserving untouched fields + status (Revise); human-reviewed
  coder.py     role C: shells out to a coding-agent CLI on the context bundle
app.py     Tk cockpit: target picker + intent input + guidance + view/editor
cli.py     headless blocking gate (validate/drift/gate) + git pre-commit installer
layouts.py per-container code-layout conventions + build manifests (seeded per container)
specfix.py auto-repair the recurring SPEC.md YAML breakage on save
example/   a tiny demo spec graph (checkout / payment / data)
```

## Run

Python 3.12 (pinned via `.python-version`) and [uv](https://docs.astral.sh/uv/).
For the coder C and for agent runs also the **Codex CLI**
([github.com/openai/codex](https://github.com/openai/codex), the `codex`
command: `npm install -g @openai/codex`; a version that knows
`--ignore-user-config` -- 0.155 does) -- see
[Models, endpoints and keys](#models-endpoints-and-keys-cockpitenv).

```sh
cd cockpit            # from the repository root
uv sync --group dev   # --group dev installs pytest; without it the tests cannot run
uv run python app.py            # uses ./example
uv run python app.py /path/to/your/spec/root
```

## Eighteen ways to run a project, and when each one asks you

Two choices, and they are independent. **How the floor is laid**: through the
`New Project...` dialog, which asks, or bare -- a root and a thin
`ARCHITECTURE.md` you fill in yourself. **Who works, and who clears what**: the
three switches -- the draft gate D0-D2, the delegation, and the run (off, on or
unsupervised), which is what hands the AUTHORSHIP of intent to an agent. Every
floor combines with every setting it can have, so here they are, all of them,
with the one thing that actually differs day to day -- when you are asked, and
whether it is BEFORE the tool acts or AFTER it has.

```text
floor   draft gate  delegation  run           you are asked ...                     and it needs
------  ----------  ----------  ------------  ------------------------------------  ----------------------
guided  D0          off         off           BEFORE every save: you press it.      P, for Draft
                                              Every HARD change waits for you.
guided  D0          on          off           same as with the delegation off --    P, for Draft
                                              every HARD change asks you when it
                                              is saved, so H' has nothing left to
                                              accept. The delegation works in a
                                              run (see below).
guided  D1          off         off           BEFORE every save, with what H'       P, H'
                                              found in front of it. Every HARD
                                              change waits for you.
guided  D1          on          off           same as with the delegation off --    P, H'
                                              every HARD change asks you when it
                                              is saved, so H' has nothing left to
                                              accept. The delegation works in a
                                              run (see below).
guided  D2          off         off           AFTER a SOFT draft saved itself (the  P, H'
                                              log, the change set) -- and BEFORE a
                                              HARD one, which escalates and waits
                                              for you.
guided  D2          on          off           same as with the delegation off --    P, H'
                                              every HARD change asks you when it
                                              is saved, so H' has nothing left to
                                              accept. The delegation works in a
                                              run (see below).
guided  -           off         on            AFTER each round: its decision        all four roles
                                              requests and its HARD changes, in
                                              Requests. NEVER before it acts -- a
                                              run is unattended by definition.
guided  -           on          on            as above, and AFTER H' accepted a     all four roles
                                              migrated breaking change: confirm or
                                              overrule. Still NEVER before it
                                              acts.
guided  -           on          unsupervised  AFTER the run, never during it: what  all four roles; the
                                              H' decided in your place -- the       delegation on
                                              requests it answered (as ADRs), the
                                              HARD changes it accepted -- to keep
                                              or take back. Yours still: TASK.md,
                                              the zones you declared.
bare    D0          off         off           as above                              P + the invariants are
                                                                                    yours
bare    D0          on          off           as above                              P + the invariants
bare    D1          off         off           as above                              P, H' + the invariants
bare    D1          on          off           as above                              P, H' + the invariants
bare    D2          off         off           as above                              P, H' + the invariants
bare    D2          on          off           as above                              P, H' + the invariants
bare    -           off         on            as above                              all four + the
                                                                                    invariants, TASK.md and
                                                                                    the manuals (`cli.py
                                                                                    init --does ...`)
bare    -           on          on            as above                              as above
bare    -           on          unsupervised  as above                              as above, and the
                                                                                    delegation on
```

**What D0, D1 and D2 mean.** In one sentence: **the slider decides who clears a
spec draft -- you alone, you with a second opinion, or, for a small (SOFT)
change, H' itself.**

In more words: you write what a node is for -- the intent -- and the planner P (a language model, set in `cockpit/.env`; the **Draft ⟶** button
asks it) turns it into a SPEC.md: a draft. The draft gate says who looks at that
draft before it is saved. (SOFT means the change adds something and breaks
nothing -- a new component, a new operation, a new criterion. HARD means it
changes something others already rely on, or something above a node, such as a
container.)

```text
D0  you alone        You read the draft and press Save, or you don't. Nobody
                     else looks at it.
D1  you, with a      Before you decide, H' -- a second model, the reviewer --
    second opinion   reads the draft and lists what it finds: a contract that
    (the default)    says HOW instead of WHAT, a criterion no test could check,
                     a capability that already exists elsewhere. You still
                     press Save yourself.
D2  H' saves the     H' may save the draft by itself, but only a SOFT one it
    small things     is sure of. If it wants changes, P revises the draft (at
                     most twice) first. Everything else comes to you, as at
                     D1: a HARD change, a protected node, a draft H' rejects or
                     is unsure about.
```

Start with D1. Choose D0 when you want to judge every draft alone, D2 once
H''s findings have proved right on small changes. Whatever you choose, every
saved spec goes through the same deterministic gate -- the slider decides who
reads the draft, never what the gate lets through.

The slider applies only to drafts P wrote. A spec you write yourself, in the
editor, is saved like D0 -- you decide, and the gate checks it.

**Why the delegation does nothing without a run.** In the cockpit a HARD change
always asks you before it is saved -- at D0, D1 and D2 alike -- so nothing is
left waiting that H' could accept. The delegation matters when someone ELSE
changes the specs: an agent, in a run. (Or a spec edited outside the cockpit --
then `cli.py decide` lets H' take its share.)

**Who clears a change, and where.** It is tempting to read the switches as one
ladder -- if H' may accept a HARD change, surely it may accept a SOFT one, so the
delegation should imply D2. It does not, because the two switches act on
different changes in different places:

```text
                in the cockpit (you draft)            in a run (an agent writes)
--------------  ------------------------------------  ------------------------------------
a SOFT change   the slider: D0 you, D1 you after H'   E, on a passing gate -- wherever
                reviewed it, D2 H'                    the slider stands
a HARD change   you, always, when you save            you -- or, with the delegation on,
                                                      H' for ONE narrow kind: a breaking
                                                      change to a consumed component
                                                      contract that E found migrated
```

In a run, SOFT changes are cleared anyway -- by E, not by D2. In the cockpit the
delegation has nothing to act on. And the slider plays no part in a run, on or
unsupervised: the agent drafts through the command line, which no slider
reaches. What H' judges differs too: at D1 and D2 the QUALITY of a draft (what,
not how; testable criteria; reuse), under the delegation whether a broken
promise has been MIGRATED.

**Asked before in the cockpit, after in a run.** In the cockpit you are asked
first: Save asks before a HARD change is written, and D1/D2 review a draft
before it is saved -- all of it before any code. A run is unattended, so it
cannot ask at the moment a question comes up; it goes on credit, and you decide
at the end:

```text
                asked before the code            asked after it (a run)
--------------  -------------------------------  ---------------------------------
you approve     you waited; the run stood still  nothing lost
you reject      no code was built in vain        the work built on it is taken
                                                 back -- the gate holds it until
                                                 then, the change set shows what
you have to be  there, during the run            there at the end
```

A run that asks early is not offered, on purpose: it would make you the run's
clock, and that is what working in the cockpit already is. What you want decided
before any code, decide before the run -- in TASK.md, or as an invariant or ADR
in ARCHITECTURE.md (AUTONOMY.md, "Asked after, not before").

**And a row the table cannot show, because it needs nothing:** write the SPEC.md
files yourself, in an editor or with Load Spec, and the whole first layer still
works -- the gate, drift, test evidence, the change set, the accepted state, a
`verified` that has to be earned. No key, no endpoint, no model. What the "needs"
column names is what the HELP costs; the engine itself costs nothing.

**The floor does not change how a switch behaves** -- it changes what exists when
you start. A guided floor arrives with the container, its build manifest, the
invariants you answered for, the accepted state and the two manuals; a bare one
is a root and `- TODO`, and everything a switch measures against is yours to write
first. For a run that matters most: it needs TASK.md and the manuals, and on a
bare floor nobody has written them.

**The switches are not one ladder**, which is why the column says what each does and not which is higher:

```text
D0-D2       the SLIDER: who clears a DRAFT -- you, you after H' reviewed it, or
            H' itself for a SOFT one. A draft is not on disk yet, so D2 is the
            ceiling.
delegation  on | off, per project, on top of whatever the slider says: who
            accepts a pending HARD change. When on, H' may, inside its scope,
            once E finds the consumers migrated. Set with `cli.py delegate ROOT
            on` or the switch beside the slider.
run         off | on | unsupervised, and not a level at all: an operating
            mode. What is delegated is the AUTHORSHIP of intent, not a gate --
            and H holds the boundaries either way. On, what is above a node
            waits for you and the run ends `asking`; unsupervised, H' answers it
            between rounds in your place, and you review every answer after the
            run. Unsupervised needs the delegation on -- which is why the table
            has no row for it with the delegation off.
```

So the draft gate only matters while you draft in the cockpit: a run drafts
through `cli.py draft`, which no slider reaches -- there E accepts what is SOFT
on a passing gate, which is why a run's rows say `-`. The delegation matters
wherever a pending HARD change waits, in a run as much as at your desk.

The switches themselves, with their limits, are in
[../spec-growth-engine/AUTONOMY.md](../spec-growth-engine/AUTONOMY.md).

### Starting a run

`Build > Start Run...`. The dialog asks for four things -- the goal (`TASK.md`
by default), how many rounds it may take, whether the run is on or
unsupervised (offered only while the delegation is on), and the first prompt,
which is filled in and rarely worth changing: it says to read `ORCHESTRATOR.md`, that the task
is in `TASK.md`, and how to end. What the task IS belongs in `TASK.md`, which is
what H' checks the result against; a prompt that repeats it sets a second goal
nobody measures.

Before it starts, the dialog says what is missing -- the goal, the two manuals,
an endpoint for one of the four roles, `codex` on PATH -- and stays shut while
anything is (`orchestrate.blockers`). A run that begins without them fails
slowly, and the failure reads like the agent's.

```text
while it runs   one line per event in the Run window, the same the log shows
                (`runlog.py`) -- and while C implements a node, which can take
                minutes, its latest line every few seconds (`C <node> ...`), so a
                working run does not look like a stalled one; after every round
                the cockpit re-reads the graph, so the tree and the Requests
                count follow along
                Close only HIDES the window -- the run goes on, and
                Build > Show Run Window brings it back, during the run and
                after it (a new run replaces it); the same lines are in
                .sge/runs/NN.log, for `tail -f`
                Draft, Revise and Save are OFF: an agent is writing those
                files. The slider is greyed out too, "(a run drafts without
                it)": a run's drafts never pass it, and a change you can
                not see take effect should not be settable
when it ends    the outcome in plain words -- done | asking | blocked | stalled |
                limit | unchecked | error -- and why, and for `asking`, the
                Requests window opens, because that is where the question is.
                A run that crashes ends too, as `error`: the reason, where it
                was raised and the traceback go into the window AND into
                .sge/runs/NN.log -- not only to stderr
                Unsupervised, it also says how many things H' decided in your
                place, and opens Requests for those too: each is an ADR in
                ARCHITECTURE.md, a pending change you accept to keep it or
                reject to take it back
```

Closing the window does not stop the run; nothing in the cockpit does. That is
deliberate for now: killing `codex` in the middle of a `code` call leaves a node
half-written, and there is no honest way to say what state it is in. Let it
reach its round limit, or stop it where you started it.

The same run, headless: `uv run python cli.py run ROOT [--unsupervised]
[--max-rounds N]` prints the same lines as the window. Either way the run is
recorded in the project -- `ROOT/.sge/runs/NN.jsonl` (the stream), `NN.log`
(the lines, to follow with `tail -f`), `NN.roles` (who played which role) --
and when it is over, E records the tests, H' decides what the delegation lets
it and briefs what is left.

## Headless gate (CLI + git pre-commit hook)

The GUI is for authoring; `cli.py` is the *blocking gate*. It runs the
deterministic checks (offline, no API key) and exits non-zero so a commit that
drifts spec from code is refused.

```sh
uv run python cli.py validate [ROOT]     # spec-side structure (intent graph)
uv run python cli.py drift    [ROOT]     # code drift (evidence vs depends_on)
uv run python cli.py gate     [ROOT]     # validate + drift = the commit gate
uv run python cli.py pending  [ROOT]     # H's inbox, as the Requests window lists it
uv run python cli.py prepare  [ROOT]     # H' briefs each pending HARD change (API key)
uv run python cli.py decide   [ROOT]     # delegation on: H' decides the HARD changes it may (API key)
uv run python cli.py test     [ROOT]     # run the tests, record them as evidence
uv run python cli.py delegate ROOT [on|off] [--by NAME] # H: who decides pending HARD
uv run python cli.py draft    ROOT ID --parent P --kind K --intent TEXT  # P drafts a node
uv run python cli.py revise   ROOT ID --change TEXT                      # P revises a spec
uv run python cli.py code     ROOT ID [--instruction TEXT]               # C implements
uv run python cli.py accept   ROOT ID... | --all [--by NAME]         # H accepts
uv run python cli.py reject   ROOT ID... --reason TEXT [--by NAME]  # H rejects
uv run python cli.py duplicates [ROOT]   # capability duplicate scan (advisory)
uv run python cli.py index    [ROOT]     # generate project.index.json
uv run python cli.py init     ROOT --id ID --container NAME | --like OLD  # lay a floor
uv run python cli.py manuals  ROOT       # render AGENTS.md / ORCHESTRATOR.md again
uv run python cli.py run      ROOT [--unsupervised] [--max-rounds N]  # an agent, in rounds
uv run python cli.py install-hook [ROOT] [--force]   # wire .git/hooks/pre-commit
```

`install-hook` writes a `pre-commit` hook into the nearest `.git` repo that runs
`cli.py gate ROOT` via `uv run --project <cockpit>`. An undeclared cross-node
import (or any structural HARD error) then blocks the commit until the spec
gains the `depends_on` edge or the code drops the import -- no silent drift
reaches history. (Also available in the GUI: Validate > Install Git Hook.)
The gate is offline; `duplicates` is advisory and never blocks.

**HARD changes without a Save click.** An agent writes SPEC.md files and runs the
gate, so there is no moment to ask anyone. Once a project tracks an **accepted
state** (`accept ROOT --all` records the current graph in `.sge/accepted.json`),
the gate measures every node against it:

```text
change at SOFT or below    accepted by E on a passing gate (logged, actor E)
HARD change                PENDING: the gate still passes, but the node -- and
                           the consumers of a broken contract -- cannot be
                           `verified` until H runs `accept ROOT ID`
```

`pending ROOT` lists what waits, with the same consumer impact the cockpit shows.

**Assisted HARD.** `prepare ROOT` has H' (a separate model call -- not the agent
reviewing itself) write a brief for each pending HARD change: what changes, the
risks, non-breaking alternatives, and a recommendation with a confidence. The
brief is bound to that exact change and goes stale if the node changes again.
H decides -- `accept`, or `reject --reason` -- and the log records the brief H
had. A REJECTED change blocks the gate with H's reason until the node is
restored (`pending` prints the accepted spec) or changed differently.

**Delegation: H delegates, H' decides inside the boundary.** `delegate ROOT on` (H only)
lets `decide ROOT` accept a pending HARD change when it is a breaking change to
a component contract that nodes in the graph consume, E finds it **migrated**
(the node and every consumer tested after the change, no consumer still naming
an operation the node no longer provides -- `test ROOT` records that evidence
headless), and the brief
from H' recommends it. Protected zones, containers, ARCHITECTURE.md, new nodes,
deletions and structure changes are never decided this way. Every acceptance
by H' waits in `pending` and the Requests window for H: `accept` confirms it,
`reject --reason` overrules it (the node's accepted spec goes back, the gate
blocks until it is restored). Nothing counts how often H' was right: it is a
delegation, bounded by structure (AUTONOMY.md §3). The gate never calls a
model; `prepare` and `decide` are the only commands that do.
After every run, E records the tests, and H' decides what the delegation lets it
and briefs what is left (`orchestrate.after`) -- so the homework is done when you
look.
In the cockpit, Save measures against the same accepted state and records what
you saved; a D2 auto-save records H' as the one who accepted it. Without the
file nothing is tracked and everything behaves as before.

Picking a node in the **Target node** box loads its `SPEC.md` into the editor.
If the editor holds a spec nobody saved -- a draft, a revision, a hand edit --
the cockpit asks first; say no, and the draft stays, with the target back on the
node it belongs to.

The GUI also has a graphical view of the SPEC graph. Use the **Tree...** button
next to the target selector or **Node > Show Tree**. Clicking a node selects it
as the target, double-clicking loads that node's `SPEC.md`.

It shows **both edge types**, because with more than one container the ownership
tree alone hides what matters:

```text
--------  solid    ownership ("consists of")  - the C4 tree, y = depth
....>     dashed   depends_on ("uses contract") - the DAG, lifted to the nearest
                   VISIBLE box, so a collapsed container still shows its coupling
red box   a node whose `parent` is not in the graph. It gets laid out at root
          level, where it would otherwise pass for a second system.
+n / -    collapse badge; n = descendants hidden behind this box
```

Subtrees **below container level are collapsed on open**, because the layout is
~230px per LEAF: three containers with four components each are ~3100px wide
(about 3.5 screens) expanded, ~1060px collapsed. **Expand All** / **Collapse
All** are in the button row.

Zoom is `40%`..`250%`: the **-** / **+** buttons, **Fit** (scales the current
graph into the window, never magnifying past 100%), **100%**, or
`Ctrl`/`Cmd`+wheel. Plain wheel scrolls, `Shift`+wheel scrolls sideways. Below
`70%` the `kind | status` line is dropped and long ids are ellipsised, so the
boxes stay readable. Fit bottoms out at `40%`; a very wide graph needs
collapsing, not more zoom.

Collapse state and zoom are **remembered per spec root** in `cockpit.json`
(`graph_view`, most recent 20 roots) and restored the next time you open that
project. Switching roots loads that root's own state; ids that no longer exist
are dropped on load.

**Requests (n)** — the button next to *Tree...* (also *Validate > Requests...*)
is the channel back to agents. An agent that needs a deviation writes a waiver
with `state: requested`; one that needs a decision above it writes a
`decision_requests` entry. Both land here, and the count on the button is
visible as soon as a project opens:

```text
waiver                   Grant...   owner + expiry, becomes state: granted
                         Reject     the node has to meet the rule
decision -> ARCHITECTURE Accept     recorded as a dated ADR, request removed
decision -> a node       Open target  edit that contract yourself, Save,
                         Resolved     then mark it resolved
any decision             Reject     optionally recorded as an ADR
HARD change (pending)    Prepare (H')  H' writes the brief shown in the window
                         Accept change recorded as accepted; H' agreement logged
                         Reject...  with a reason; the gate blocks on it
```

A decision targeting a node is never applied automatically: the proposal is
prose, and merging it into a contract is the judgement being asked for. Every
action checks the request still says what the list showed -- if an agent or an
editor changed the file meanwhile, it refuses rather than deciding the wrong one.
After *Validate*, the guidance says how many requests await you instead of just
"validated", and nodes waiting on H are outlined amber in the graph.

## Models, endpoints and keys (`cockpit/.env`)

Four roles call a model, and each has its OWN endpoint, so which model at which
provider plays which role is your choice:

```text
role        what it does                         called as          needed for
----------  -----------------------------------  -----------------  -------------------------
planner  P  intent -> SPEC.md (Draft, Revise)    a chat call        drafting with a model;
                                                                    semantic matching
reviewer H' reviews drafts, briefs HARD changes, a chat call        D1/D2, briefs, delegation,
            checks a run's goal                                     runs
intent   I  the agent that authors a run         an agent, on the   runs
                                                 Codex CLI
coder    C  implements a node from its SPEC.md   an agent, on the   the Codex button,
                                                 Codex CLI          `cli.py code`, runs
```

Nothing else needs a model: the gate, drift, test evidence, the change set and
specs written by hand work with no key at all.

**Where.** Copy `cockpit/.env.example` to `cockpit/.env` and fill in the roles
you use -- or, to run every role on DeepSeek, copy `cockpit/.env.deepseek.example`,
which is complete except for the keys: put yours in place of each `sk-...`. The file is git-ignored; the example is tracked and holds no values.
The cockpit, `cli.py` and every run read it from there, and only there -- no
model is set anywhere else. A variable already set in the environment wins, so
one command can override a role: `SGE_CODER_MODEL=... uv run python cli.py run ROOT`.

**How.** Every role is set the same way, by three lines -- an OpenAI-compatible
endpoint (any provider that speaks that API, or a local server), its key, and
the model as that provider names it. The two agents take a fourth: the
HARNESS, the agent CLI that runs them. Every role may take one more, optional:
the REASONING_EFFORT, how hard the model thinks (e.g. `low | medium | high`, what
the provider accepts), passed as written -- to the chat call for P and H', to
the Codex CLI (`model_reasoning_effort`) for I and C. Unset, the provider's own
default holds.

```sh
SGE_PLANNER_BASE_URL=https://...
SGE_PLANNER_API_KEY=...
SGE_PLANNER_MODEL=<model id>       # the same three lines for REVIEWER
SGE_PLANNER_REASONING_EFFORT=high  # optional, for every role

SGE_CODER_BASE_URL=https://...
SGE_CODER_API_KEY=...
SGE_CODER_MODEL=<model id>
SGE_CODER_REASONING_EFFORT=high
SGE_CODER_HARNESS=codex-cli        # the same lines for INTENT
```

One order in every block: BASE_URL, API_KEY, MODEL, REASONING_EFFORT, and
HARNESS for the two agents.

**Nothing falls back.** A role without its three lines is not configured -- not
borrowed from another role, not defaulted to a provider -- and whatever asks for
it says which settings are missing. Two roles on the same model repeat the same
values. For the reviewer that works, but then H' reviews what its own model
wrote, and every review says so: another model makes the review independent.

**The two agents, on the Codex CLI.** The one harness there is, `codex-cli`, is
the Codex CLI ([github.com/openai/codex](https://github.com/openai/codex)) --
REQUIRED for I and C: install it with `npm install -g @openai/codex`, so that the
`codex` command is on PATH -- a version that knows `--ignore-user-config`
(0.155 does). Both run as `codex exec`, pointed at their endpoint on the command
line, with `--ignore-user-config`: your own `~/.codex/config.toml` is not
loaded, so a service tier, a reasoning effort, a model catalog or a notify hook
set there does not reach I or C -- `cockpit/.env` is the whole configuration,
the same on every machine. The key reaches codex only through its environment,
never the command (which is logged). One warning remains for models Codex has
no metadata for (most that are not OpenAI's): "Model metadata for `...` not
found. Defaulting to fallback metadata" -- Codex then assumes general defaults,
e.g. for the context window; the run goes on. The cockpit's **Codex** button, `cli.py code` and every run start C the
same way; without `codex` on PATH, Start a run... and `cli.py run` say so before
anything starts. The cockpit, the gate, drafting and reviews need no Codex CLI.

**Check it.** `uv run python role_agent.py --describe` prints, per role, how it
runs, the model and the endpoint, and which variable its key came from -- never
the key. A run records the same lines in `ROOT/.sge/runs/NN.roles`. Start a
run... and `cli.py run` refuse to start while a role a run needs is not
configured, and say which. The cockpit itself starts and loads nodes without
any key; Draft ⟶ reports a missing setting instead of failing.

### Persistent settings (`cockpit.json`, git-ignored)

Non-secret settings persist in `cockpit.json`: `last_root`, `semantic_match`
(capability matching with the planner's model), and `draft_gate` (0..2; the Autonomy slider for the
DRAFT gate; 1 = advisory H' draft review, 2 = H' auto-clears the SOFT draft gate;
no-op without an API key). The delegation is not a slider setting: it concerns
pending HARD changes and is switched per project with `cli.py delegate`. On launch the cockpit reopens the
**last working directory** (override with an explicit path argument).
Keys and models stay in `.env`, never in `cockpit.json`.

## Choosing where the spec graph lives

**How the graph grows is yours to decide.** In the cockpit you are the INTENT
AUTHOR (role I): you say what each node is for, the planner writes the spec, the
coder writes the code. Grow it the way the method says -- iteratively, one
working vertical slice at a time, decomposing as far as you know and leaving what
you would have to guess for the slice that needs it; every node on a slice's path
is real. The workflow, and why a guessed skeleton of fakes -- not early drafting --
is the failure it avoids, is
[../spec-growth-engine/LIFECYCLE.md](../spec-growth-engine/LIFECYCLE.md) §6-§7.
An agent in an orchestrated run gets the same rule as its manual (ORCHESTRATOR.md);
no gate can check it, because which slice comes next is a judgement.

**Inside an existing repository**, point the root at the subtree you are growing
(`Open dir...`, or `uv run python app.py /repo/apps/newthing`). The spec root is
the scan root, so code elsewhere in the repository is invisible to validate,
drift and the gate -- no configuration, no exclusion list. Pointing the root at
a whole existing codebase instead is the *adoption* case: every unowned file is
an orphan and the gate blocks. See CONCEPT §7b for why that is a deliberate
distinction and not an oversight.


The cockpit **tool** lives in this directory; your **spec graph** (the SPEC.md
nodes) can live anywhere. Pick the target directory in any of three ways:

- CLI argument: `uv run python app.py /path/to/your/project`
- **Open dir...** - switch the spec root at runtime (directory picker).
- **New project...** - lay the FLOOR of a fresh project in an empty directory: the
  root, a container with its code layout and build manifest, the invariants, the
  accepted state, and the manuals (see the menu section below). It is the only way
  in: there is no bare-bootstrap entry any more, because a root plus an
  `ARCHITECTURE.md` of TODOs is the floor this step exists to replace. Leave every
  question blank and you get exactly that, deliberately.

Engine API:

```python
from engine import nodes
nodes.bootstrap_root("/path/to/project", system_id="app", purpose="An online shop.")
```

A directory with no root `SPEC.md` has zero nodes; use **New project...** first.

## Node management (you own the nodes)

Nodes are not fixed in the engine - they are your SPEC.md files, created and
deleted from the cockpit:

- **New project...** - lays the FLOOR of a new project in one window and
  then opens the cockpit on it: the root node, one container with the code layout
  and the build manifest of the archetype you pick, the invariants, and the
  accepted state that every later change is measured against. The invariants are
  the point of the dialog: four defaults to keep or drop, then four questions the
  defaults cannot know (persistence, concurrency, network at run time, anything
  else). An answered question becomes ONE invariant line -- worded by the planner
  when it has an endpoint, and by you otherwise; nothing is written before you
  have seen what it would write. It also renders `ORCHESTRATOR.md` and `AGENTS.md`
  with THIS project's paths (the values all follow from the graph: the container
  is the one node of that kind, its stack is its manifest's name, the test command
  is what `test` would run) and reports which role has an endpoint. Tick **"An
  AGENT will build this"** and it also asks the three things a goal states --
  what it must do, what must always be true, what is out of scope -- and writes
  `TASK.md` from them -- through the method's template
  (`spec-growth-engine/TASK.template.md`), with its own "Done means" filled in,
  because that part is the same in every project and not a newcomer's to invent
  (3.12). A few words are not a goal a run can be checked against: **Suggest
  with P** has the planner turn them into a fuller one -- observable behaviours,
  what must always hold (above all: testable without a screen), what is out of
  scope -- in the fields, for you to edit; nothing is written until you lay the
  floor, and it stays your goal. A person working the cockpit leaves the box
  unticked: their goal is in their head. It stops there: components and starting a run are the steps after
  it. The directory may be anywhere, and need not exist yet. Headless: `cli.py
  init ROOT --id ID --container NAME [--archetype KEY] [--invariant LINE]...`.
- **New Project Like...** - lays the floor another project was laid with, in a
  new directory: the answers it recorded (`.sge/groundwork.json`) and its
  `TASK.md` as it reads now. A second attempt at the same task is a new
  directory, not the first one reset. Headless: `cli.py init NEW --like OLD`.
- **Edit Goal (TASK.md)...** (Build menu) - the goal of this project in an
  editor, with the same **Suggest with P**: the planner proposes a fuller goal
  from what is there, in the editor, and only Save writes it. For a goal that
  turned out too thin -- before a run, not after it.
- **Check Goal (TASK.md)** (Build menu) - does the project meet its goal, as it
  stands? E runs the tests and the gate, and on a green floor H' checks the
  result against `TASK.md` -- what a run's last round says, without the run: no
  agent, no session, nothing changed but the recorded test evidence. The verdict
  goes to Guidance: **done** (green, no gap, nothing waits for you), **gaps**
  (with the list), **asking** (something waits in Requests -- a pending HARD
  change counts too), **red** (the failing tests and gate errors; H' is not
  asked) or **unchecked** (H' not reachable). The use: after you worked through
  the Requests, or changed something by hand. Headless: `cli.py check ROOT`.
- **Refresh Manuals** - renders `AGENTS.md` and `ORCHESTRATOR.md` again from the
  method's templates, after they changed. The copies are generated: an edit to
  them belongs in the template. Headless: `cli.py manuals ROOT`.
- **New node** - opens a dialog: pick the **parent** (any existing node), a
  **segment** (the last id part), and a **kind** (`component` / `container` /
  `system`). There is no `code` kind: specs end at the component, which nests as
  deep as it needs to -- a file with a contract of its own is a sub-component
  owning that file, and its parent's glob gives the file up by itself (on one
  ownership line the most specific owner wins). The engine creates `<parent_dir>/<segment>/SPEC.md` as an
  empty skeleton and adds it to the parent's `design.children`. The id is
  `<segment>` under the system root, otherwise `<parent_id>.<segment>`.
  For a **container** you also pick a **Code layout** convention (`layouts.py`:
  Java/Maven, Python/uv, Node, Rust, or freeform); it seeds that container's
  `contract.invariants` with its language + code-layout (the C4 tech boundary).
  A system can be polyglot -- each container picks its own; the Spine carries the
  convention down to that container's components. The same archetype also seeds
  the **build manifest** (`pyproject.toml`, `Cargo.toml`, `package.json`,
  `pom.xml`) and declares it as the container's `code`: the layout line says in
  prose where the package root is, the manifest says it again in the build tool's
  language, and seeding both from one entry is what keeps the two spellings of
  one decision in step. It is a FIRST file, never overwritten if one is already
  there, and C owns it from its first run -- it sits in the container's own `code`
  glob, so an agent run may change it through `code`, and it does NOT belong in the
  list of files given to such a run. Without a manifest there is no build root, and
  without a build root nothing records test evidence. Freeform seeds neither. Then
  fill it via **Draft ⟶**.
- **Delete node** - removes the node's SPEC.md (and its now-empty directory) and
  drops it from the parent's `children`. A node with children is refused unless
  you confirm a **recursive** delete (subtree, post-order). Any nodes that still
  `depends_on` the deleted one are reported as a warning.

Equivalent engine API (used by the GUI):

```python
from engine import parser, nodes
n = parser.load_nodes("example")
nid, path = nodes.new_node("api", "discount", "component", n)   # -> api.discount
removed, dependents = nodes.delete_node("api.discount", n)       # recursive=True for subtrees
```

## Workflow (maps to the paper)

1. **New node** (or pick an existing target); describe the intent (language + examples).
2. **Draft ⟶** - planner drafts the SPEC.md from scratch (the Intent box); review
   the contract lines. Resets status to `specd`. The planner derives `code` globs from
   the **owning container's** code-layout invariants (carried down the Spine; code tree
   separate from the spec tree) and never leaves `code: []` for a code-owning component
   -- so the build layout is an explicit spec decision, not improvised by the coder.
   At **draft gate D1 or D2** (the **Autonomy slider**, default D1) an
   **advisory H' review** (role: the architect's deputy) runs right after and shows
   findings in Guidance -- altitude (contract = WHAT not HOW), intent placement,
   testable acceptance, depends_on/`code` sanity, reuse, and intent fidelity.
   - **D1 (advisory):** findings shown; *you* decide Save.
   - **D2 (auto-clear SOFT):** H' clears the draft gate itself -- `approve` -> auto-save;
     `revise` -> the Planner applies the findings and H' re-reviews (max 2 rounds);
     `reject`/low-confidence/**declared protected zone** (`protected: true`, or a
     node inside such a subtree) -> escalate to you. So does any draft whose
     **change set** is HARD (see Save), whatever H' said: D2 clears SOFT gates
     only. Every decision is logged to `.sge/autonomy.jsonl`.
   In all cases the deterministic gates (validate/drift/lifecycle) remain the hard
   floor and run regardless -- H' never overrides them (an auto-save that the gate
   blocks is reported as such). Without an API key the review silently does nothing.
   The Autonomy slider is the DRAFT gate and offers D0, D1, D2 -- it ends there,
   because a draft is not on disk and cannot be migrated. **The delegation is per
   project**, on or off, and has its own switch beside the slider (or `cli.py
   delegate ROOT on`): it lets H' accept a pending HARD change inside its scope,
   is asked for once, is written to `.sge/autonomy.json` with who set it, and can
   be revoked or overruled at any time. A run is an operating mode
   (Start a run..., or `cli.py run ROOT`), not a slider value. Such a run
   goes in rounds (`orchestrate.py`): when the agent stops, E checks the floor and
   H' the goal against TASK.md, and the agent is resumed with what is missing.
   Levels and their limits: [../spec-growth-engine/AUTONOMY.md](../spec-growth-engine/AUTONOMY.md).
   **Draft over an existing spec?** Drafting REGENERATES, so pressing it on a node
   that already says something -- above all a container whose code-layout invariants
   the archetype seeded -- would replace what is there. The cockpit asks once, with
   Revise as the safe answer; a fresh skeleton (`provides: []`) is drafted without a
   question, because nothing would be lost. `cli.py draft` refuses an existing node
   outright and points at `revise`.

   **Revise →** - for an EXISTING node: the current SPEC.md is transported in and
   the planner applies the change request (Intent box) in place, preserving untouched
   fields (code globs, depends_on, design.verification, ...) AND the node's status.
   Use Draft for a fresh node, Revise to evolve one. (Or **Load SPEC** to edit by hand.)
3. **Save** - write the reviewed spec, reindex. The frontmatter is
   auto-repaired for the one recurring YAML breakage (an unquoted `word: word`
   colon or leading backtick in a scalar): the offending line is quoted, reported in
   Guidance (transparent, never silent). The SAME healing runs **on load/reload**
   (Open, Reload, gate actions, after Codex) over any SPEC.md edited externally, so a
   node never silently vanishes from the tree; files it cannot auto-fix are reported
   as broken/hidden. See `specfix.py`. The parser and the CLI **gate stay strict** --
   they BLOCK on invalid YAML (no silent drift into a commit); healing is an
   authoring-time convenience in the cockpit only. They block, too, on a SPEC.md
   that parses but is no node -- one with no `id`, or an `id` another SPEC.md
   already has: either would drop out of the graph without a word, and the code
   it claims would look orphaned with the cause nowhere.
   Before writing, Save computes the **change set** (`engine/changeset.py`): which
   gate the change falls under and why, which nodes `depends_on` this one, which of
   them mention a removed operation, and which evidence was recorded against the
   old contract. A **HARD** change set -- a breaking change to a consumed contract
   or to a container, a new container, an id/kind/parent change, the root contract,
   a waiver grant -- asks you to confirm with that report in front of you. Draft
   and Revise show the same report in Guidance. Below its reasons the report
   says WHAT changed, entry by entry (`-` before, `+` after), for every contract
   key and for the SOFT and AUTO fields (`code`, `depends_on`, `status`, ...) --
   whatever the gate; `design` and the prose, which gate nothing, stay out. Each
   part carries its own gate, HARD first (`[HARD] invariants`, `[SOFT] provides`,
   `[AUTO] depends_on`): the change takes the highest, and Accept clears all of it.
4. **Build context** (optional) - a read-only preview of the scoped bundle C gets:
   ARCHITECTURE.md (global invariants) + ancestor contracts (short) + target spec
   (full) + own code + dependency contracts (one hop). To change what C gets,
   change the spec (or ARCHITECTURE.md) and save -- an edit of the bundle would be
   recorded nowhere, and the gate would measure against something else.
5. **Codex** - the coding agent implements within the bundle, which Codex builds
   when you press it, from the SAVED specs -- whatever the editor holds, as
   `cli.py code` and every run do. An unsaved spec in the editor stops it: C would
   implement the saved one, and the bundle would replace your draft. For a one-off
   hint, use **Ask Codex** in the output window. Output opens in a
   separate window with a live status bar (running/finished, elapsed, process-tree
   CPU, idle since last output) and an **Ask Codex** input box: type a follow-up and
   it replays the prior context + output with your message as a fresh `codex exec`
   run (it is single-shot, no live session). The agent runs in the node's build root.
6. **Validate** - spec-side structural check (intent graph). Does NOT run tests.
7. **Drift (code)** - code-side check: source imports vs declared `depends_on`.
   Import edges are detected per language: TS/JS (relative + require/dynamic),
   Java (`import a.b.C;` + wildcard), Kotlin (by package + top-level decl),
   Dart (relative/`part` + `package:<name>/...`), Python (`import a.b`,
   `from a.b import c`, relative `from .m import x`). Edges to external/library
   code are ignored. Parent->child (ancestor->descendant) edges are realization,
   not dependencies.
   An undeclared cross-node import is a HARD error and blocks the gate. Orphan
   detection is language-aware: the scanned file extensions are the union of those
   the `code` globs declare (`*.py` -> `.py`) AND those implied by the project's
   build manifests (pom.xml -> `.java`, pyproject.toml -> `.py`, package.json ->
   `.ts/.js`, ...). The manifest source matters because a directory glob like
   `pkg/**` names no extension; without it, deleting or rewriting an owner could
   silently drop its code from the scan. `code` globs are **project-root-relative**
   (the spec's location is independent of where the code lives), e.g.
   `code: ["cli/src/main/java/app/**"]`.
   Ownership is best declared explicitly; the gate catches any file you forgot to list.
8. **Run tests** - runs the project's tests at the node's build root
   (`mvn`/`uv run pytest`/`cargo`/`gradle`/`npm`/`flutter` by manifest). The verdict
   is **recorded as test evidence** (`.sge/evidence.json`) for every node sharing that
   build root. This backs the status lifecycle: a node marked **`verified` without a
   passing evidence record is a HARD error** (no fake completion) -- the gate blocks
   until tests are (re)run or the status is lowered. A FAIL records `fail` -> also blocks
   `verified`. (`.sge/` is a local trust marker, best git-ignored.)
   Evidence is recorded per **build root**; `engine/attribution.py` additionally
   maps each test file to the nodes it exercises (it is owned by the node, or it
   imports code the node owns) and the gate **WARNS** when a `verified` node has
   no test attributed to it. It warns rather than blocks because attribution is
   static -- reflection, fixtures and subprocesses are invisible to it
   (LIFECYCLE.md 5a).
   Second limit (LIFECYCLE.md 5b): evidence is local while `status` is committed,
   so a fresh clone has no records and the gate blocks every `verified` node
   until the tests are re-run. CI must run the tests before the gate; it cannot
   gate a bare checkout.
9. **Generate Index** (Validate menu / `cli.py index`) - writes `project.index.json`:
   a deterministic snapshot of the spec graph + capabilities + ownership/dependency/
   code edges + each node's status & test evidence. Generated, never hand-authored.

### Capability Registry (horizontal reuse axis)

The Spine gives vertical context ("what must I conform to?"). The **Registry**
gives the orthogonal answer ("what already exists that I could reuse?") so the
same capability is not built twice in unrelated branches. `Registry` menu:

- **Find Capability** - search existing `provides` contracts before building.
  Match -> `depends_on` it (REUSE); no match -> create a `shared` node so the
  next slice finds it. (Draft also auto-warns when an intent resembles one.)
- **Duplicates** - mechanical detector over the evidence graph. Combines
  contract-text similarity + signature shape + shared external dependency
  (e.g. two nodes that both `import pdfplumber` with a `path -> Text` surface).
  Skips ownership-line pairs (realization) and pairs already linked by
  `depends_on`. Surfaces high/medium clusters for human judgement.
- **Claim Capability** - register an intent-level claim before building; a
  matching open claim raises CONCURRENT-CAPABILITY-CREATION so two slices
  coordinate (one builds the shared node, the other depends on it). Claims live
  in `CAPABILITIES.claims.json` at the project root.

Similarity is lexical (token Jaccard) by default. When `semantic_match` is on
(cockpit.json, default true) and the planner is configured, its model adds a
semantic layer via dependency injection (agent/semantic.py): the lexical hits
are the cheap prefilter, then the model re-ranks Find results (blended 50/50
with lexical) and confirms Duplicate pairs ("same capability?" -> demotes
"similar but not the same", e.g. PDF-with-OCR vs without). The engine stays
deterministic; the LLM is the injected dependency and any AI failure falls back
to lexical, so the gate never breaks. Reports show the mode (lexical vs
semantic) and per-hit lex/sem scores.

Try the drift gate against the bundled fixture (has one deliberate violation):

```sh
uv run python -c "from engine import parser, drift; \
  n=parser.load_nodes('example-ts'); print(drift.run(n,'example-ts'))"
# -> undeclared dependency: checkout -> util ... gate: BLOCK
```

## Not yet implemented

- "Dependency bypasses contract" (importing another node's internal files):
  needs an explicit public-surface marker in the spec.
- Bare/workspace-alias TS import resolution (only relative TS specifiers are
  resolved; Java/Kotlin/Dart/Python use symbolic resolution against owned files).
