# Spec Growth Engine

**Spec-anchored, code-coupled, drift-enforced architecture for AI-assisted
software development.**

The Spec Growth Engine is a software-development method and the tool that
enforces it. Software grows as a graph of `SPEC.md` files -- one per node:
system, container, component -- each stating a contract, and the code is
coupled to that graph: a deterministic gate checks that the code does what the
graph says, that nothing grew outside it, and that "done" is earned by
recorded test evidence rather than claimed.

It is built for work in which language models write most of the specs and the
code. Their judgement is used where it helps; the deterministic gate decides
what gets through.

## Papers

- **The method** -- Hartwig Grabowski. *The Spec Growth Engine: Spec-Anchored,
  Code-Coupled, Drift-Enforced Architecture for AI-Assisted Software
  Development.* [arXiv:2606.27045](https://arxiv.org/abs/2606.27045), 2026.
- **This implementation** -- Hartwig Grabowski. *Implementing the Spec Growth
  Engine: Preventing Spec-Code Divergence, and Growing the Spec with Agents.*
  [arXiv:2610.11725](https://arxiv.org/abs/2610.11725), 2026.

## Two layers

```text
LAYER 1   spec-code divergence                SPEC.md, ARCHITECTURE.md, .sge/
          The engine: a graph of contracts, a gate that blocks, evidence that
          is recorded, a change set that says what moved. Deterministic. A
          person and the cockpit are a COMPLETE use of it -- no agent, no goal
          file, no run, and no API key.

LAYER 2   agent-driven development            TASK.md, the manuals, the runs
          An orchestrated run in which an AGENT writes the node intents, asks
          the planner for specs and the coder for code, and is sent back by a
          deterministic rule until the goal is met. Judgement is allowed here,
          because layer 1 measures the result afterwards.
```

An autonomous run is worth only as much as the deterministic instance that
measures it afterwards. Layer 1 does not need layer 2; layer 2 cannot exist
without layer 1.

## Who does what

```text
H    the human architect   the goal, the boundaries, every consequential decision
I    the intent author     what each node is for -- you in the cockpit, or an agent
P    the planner           turns an intent into a SPEC.md (a language model)
C    the coder             implements one node from its SPEC.md (a coding agent)
H'   the reviewer          judges what the engine cannot -- a second model, never a person
E    the engine            derives, validates, blocks; calls no model, authors no intent
```

How much of H's judgement is delegated is set with three independent
switches -- the **draft gate** (D0: you alone, D1: with a review, D2: the
reviewer saves small, safe changes itself), the **delegation** (may the
reviewer accept a breaking change once every consumer is migrated?), and the
**run** (off, on, or unsupervised). Whatever they say, the deterministic gate
always runs and always blocks. See
[`spec-growth-engine/AUTONOMY.md`](spec-growth-engine/AUTONOMY.md).

## Getting started

New to it? [`cockpit/MANUAL.md`](cockpit/MANUAL.md) walks through the cockpit step
by step, with screenshots -- a small program built from nothing, every button
explained.

Requirements:

- **Python 3.12** and [**uv**](https://docs.astral.sh/uv/) -- for everything.
- **The Codex CLI** ([github.com/openai/codex](https://github.com/openai/codex),
  the `codex` command: `npm install -g @openai/codex`; 0.155 or newer, for
  `--ignore-user-config` -- your own `~/.codex/config.toml` does not apply to
  SGE's agents) -- required for the
  coder C (the cockpit's Codex button, `cli.py code`) and for agent runs, which
  run I and C on it. The cockpit, the gate, drafting and reviews do not need it.
- **An OpenAI-compatible endpoint and key per role you use** -- see
  [Models and keys](#models-and-keys).

```sh
cd cockpit
uv sync --group dev
uv run python app.py                  # the cockpit, on the bundled example
uv run pytest -q                      # the test suite
```

In the cockpit, **Open > New Project...** lays the floor of a new project in
any directory: a root, a first container with its code layout and build
manifest, the invariants that hold everywhere, and -- if an agent is to build
it -- the goal (`TASK.md`). From there you grow it node by node: describe what
a node is for, let the planner draft its `SPEC.md` (or write it yourself), and
let the gate tell you what is missing.

Without the cockpit:

```sh
uv run python cli.py init ~/work/notes --id notes --container app \
    --does "notes add TEXT prints the id" --always "notes survive a restart"
uv run python cli.py gate ~/work/notes          # the commit gate: validate + drift;
                                                # on a pass E accepts what is SOFT
uv run python cli.py install-hook ~/work/notes  # in a git repo: the gate on every commit
uv run python cli.py run ~/work/notes           # an agent grows it, in rounds
uv run python cli.py check ~/work/notes         # does it meet TASK.md? (H', no agent)
```

The gate is offline and needs no key.

## Models and keys

Four roles call a model -- the planner P, the reviewer H', and the agents I
and C -- and each has its own OpenAI-compatible endpoint, set in
`cockpit/.env`. Copy `cockpit/.env.example` and fill in the roles you use -- or
copy `cockpit/.env.deepseek.example`, a complete configuration for DeepSeek that
needs only your key in place of each `sk-...`. Every
role takes the same three lines; the two agents take a fourth, the harness that
runs them -- the Codex CLI, `codex-cli`, the only one so far:

```sh
SGE_PLANNER_BASE_URL=https://...       # any OpenAI-compatible provider
SGE_PLANNER_API_KEY=...
SGE_PLANNER_MODEL=<model id>           # the same three lines for REVIEWER
SGE_PLANNER_REASONING_EFFORT=high      # optional, any role: e.g. low | medium | high

SGE_CODER_BASE_URL=https://...         # the same lines for INTENT
SGE_CODER_API_KEY=...
SGE_CODER_MODEL=<model id>
SGE_CODER_REASONING_EFFORT=high
SGE_CODER_HARNESS=codex-cli
```

Nothing falls back: a role without its three lines is not configured, and
whatever needs it says which settings are missing. Two roles on the same model
repeat the same values -- for the reviewer that works, but a different model
makes its review independent. Drafting needs the planner; reviews and briefs
the reviewer; the coder needs C, and agent runs need I and C -- both on the
Codex CLI. Details are in
[`cockpit/README.md`](cockpit/README.md#models-endpoints-and-keys-cockpitenv);
`uv run python role_agent.py --describe` shows who plays which role -- never a
key.

## Repository

```text
cockpit/               the tool: engine (engine/), model-backed roles (agent/),
                       the Tk cockpit (app.py), the CLI (cli.py), the run
                       driver (orchestrate.py), tests, and two example graphs
spec-growth-engine/    the method: concept, glossary, governance, lifecycle,
                       autonomy, and the templates a project is laid from
```

Start reading at
[`spec-growth-engine/SPEC-GROWTH-ENGINE.md`](spec-growth-engine/SPEC-GROWTH-ENGINE.md):
it indexes the method documents and gives a reading order (§6). The cockpit's
own manual is [`cockpit/README.md`](cockpit/README.md); what is built, and what
is not yet, is in [`cockpit/STATUS.md`](cockpit/STATUS.md).

## Status

A research prototype, in active development. The engine and the cockpit are
covered by a test suite; the method was developed through a series of agent
runs against small, concrete tasks. The unsupervised run mode has so far been
used on one small task -- the number-guessing game in Section 4 of the
implementation paper, given to a supervised and an unsupervised run -- and not
yet on a larger one. Expect the interfaces to change.

## License and author

Licensed under the [Apache License 2.0](LICENSE).

Hartwig Grabowski, Hochschule Offenburg --
hartwig.grabowski@hs-offenburg.de --
ORCID [0009-0001-4300-2626](https://orcid.org/0009-0001-4300-2626)
