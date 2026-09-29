"""Run a role -- the intent author I or the coder C -- as a `codex exec` agent
against its OWN endpoint (agent/llm.py: SGE_<ROLE>_BASE_URL / _API_KEY / _MODEL).

Codex is open source and speaks the same OpenAI-compatible API as the planner
and the reviewer, so all four roles are configured the same way: a URL, a key,
a model. The provider is defined ad hoc with `-c` overrides, and the user's own
~/.codex/config.toml is NOT loaded (`--ignore-user-config`): whatever it says --
a service tier, a reasoning effort, a model catalog, a notify hook -- would
otherwise steer I and C too, differently on every machine, and cockpit/.env
would not be the whole configuration it claims to be.

The KEY never appears in the command -- only the NAME of the variable that
holds it (`env_key`), set in the child's environment alone. That matters: the
command is logged (the audit log's `by`, run records), and a key in it would be
a key in every log.

Two things every caller must know:
  - codex exec WAITS on an open stdin. Started with the caller's stdin, it hung
    until killed (the first smoke test). Give it /dev/null.
  - it runs with approvals and sandbox bypassed (the user's "yolo"): a role
    agent works unattended, in a throwaway or tracked workspace. What it may do
    is the manual's rule and the stream's record, not the sandbox's.
"""
from __future__ import annotations

import os

from . import llm

AGENT_ROLES = llm.AGENT_ROLES


def key_variable(role: str) -> str:
    """The environment variable the child reads its key from."""
    return f"SGE_{role.upper()}_CODEX_KEY"


def command(role: str, *, json_events: bool = False,
            resume: str | None = None) -> tuple[list[str], dict]:
    """(argv without the prompt, environment) to run `role` as a codex agent.
    With `resume` (a session id from the stream's `thread.started`), the argv
    continues THAT session -- `codex exec resume ID` -- with its memory of what
    it did: the next round of an orchestrated run (orchestrate.py). Raises
    RuntimeError naming every setting the role still lacks -- said, not guessed:
    no role has a default."""
    if role not in AGENT_ROLES:
        raise ValueError(f"not an agent role: {role!r} (one of {AGENT_ROLES})")
    lacking = llm.missing(role)
    if lacking:
        raise RuntimeError(f"the {role} is not configured: fix {', '.join(lacking)} in "
                           "cockpit/.env")
    ep = llm.endpoint(role)
    if ep["harness"] != "codex-cli":   # llm.HARNESSES names only what has an adapter
        raise RuntimeError(f"no adapter for the harness {ep['harness']!r} here")
    provider, var = f"sge_{role}", key_variable(role)
    # resume takes the same options, but after its own name
    argv = [
        "codex", "exec", *(["resume"] if resume else []), "--skip-git-repo-check",
        "--ignore-user-config",        # cockpit/.env alone configures the role
        "--dangerously-bypass-approvals-and-sandbox",
        "-c", f'model_provider="{provider}"',
        "-c", f'model_providers.{provider}.name="{provider}"',
        "-c", f'model_providers.{provider}.base_url="{ep["base_url"]}"',
        "-c", f'model_providers.{provider}.env_key="{var}"',
        # the Responses API first, the Chat API where a provider has only that
        "-c", f"model_providers.{provider}.fallback_chat=true",
        "-c", f'model_providers.{provider}.fallback_chat_path="/chat/completions"',
        "-m", ep["model"],
        # the role's own, from cockpit/.env; unset, the provider's default holds
        *(["-c", f'model_reasoning_effort="{ep["reasoning_effort"]}"']
          if ep["reasoning_effort"] else []),
    ]
    if json_events:
        argv.append("--json")
    if resume:
        argv.append(resume)            # the prompt follows the session id
    # SGE_ACTOR: who is writing, for the growth record (engine/intents.py) --
    # an intent drafted from inside this agent's shell is I's, not H's
    actor = {"intent": "I", "coder": "C"}[role]
    return argv, dict(os.environ, **{var: ep["api_key"], "SGE_ACTOR": actor})


def describe(role: str) -> str:
    """What runs the role, for logs -- never the key."""
    return f"codex exec: {llm.describe(role)}"
