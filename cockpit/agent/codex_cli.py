"""Run a role -- the intent author I or the coder C -- as a `codex exec` agent
against its OWN endpoint (agent/llm.py: SGE_<ROLE>_BASE_URL / _API_KEY / _MODEL).

Codex is open source and speaks the same OpenAI-compatible API as the planner
and the reviewer, so all four roles are configured the same way: a URL, a key,
a model. The provider is defined ad hoc with `-c` overrides; ~/.codex/config.toml
is neither needed nor touched.

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

AGENT_ROLES = ("intent", "coder")


def key_variable(role: str) -> str:
    """The environment variable the child reads its key from."""
    return f"SGE_{role.upper()}_CODEX_KEY"


def command(role: str, *, json_events: bool = False,
            resume: str | None = None) -> tuple[list[str], dict]:
    """(argv without the prompt, environment) to run `role` as a codex agent.
    With `resume` (a session id from the stream's `thread.started`), the argv
    continues THAT session -- `codex exec resume ID` -- with its memory of what
    it did: the next round of an orchestrated run (orchestrate.py). Raises
    RuntimeError when the role has no model or no key -- said, not guessed: an
    agent role has no sensible default model."""
    if role not in AGENT_ROLES:
        raise ValueError(f"not an agent role: {role!r} (one of {AGENT_ROLES})")
    ep = llm.endpoint(role)
    if not ep["model"]:
        raise RuntimeError(f"no model for the {role}: set SGE_{role.upper()}_MODEL "
                           "in cockpit/.env")
    if not ep["api_key"]:
        raise RuntimeError(f"no API key for the {role}: set SGE_{role.upper()}_API_KEY "
                           f"or SGE_{role.upper()}_KEYCHAIN in cockpit/.env")
    provider, var = f"sge_{role}", key_variable(role)
    # resume takes the same options, but after its own name
    argv = [
        "codex", "exec", *(["resume"] if resume else []), "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "-c", f'model_provider="{provider}"',
        "-c", f'model_providers.{provider}.name="{provider}"',
        "-c", f'model_providers.{provider}.base_url="{ep["base_url"]}"',
        "-c", f'model_providers.{provider}.env_key="{var}"',
        # the Responses API first, the Chat API where a provider has only that
        "-c", f"model_providers.{provider}.fallback_chat=true",
        "-c", f'model_providers.{provider}.fallback_chat_path="/chat/completions"',
        "-m", ep["model"],
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
