"""What every model-backed role shares: one client, one call, one parser -- and
one ENDPOINT per role, so which model, at which provider, plays which role is
a choice.

  role        what it does                 set in cockpit/.env
  ----------  ---------------------------  -----------------------------------------
  planner  P  intent -> SPEC.md            SGE_PLANNER_BASE_URL / _API_KEY / _MODEL
  reviewer H' drafts, delegation, goals    SGE_REVIEWER_BASE_URL / _API_KEY / _MODEL
  intent   I  goal -> node intents (a run) SGE_INTENT_BASE_URL / _API_KEY / _MODEL
                                           / _HARNESS
  coder    C  SPEC -> code                 SGE_CODER_BASE_URL / _API_KEY / _MODEL
                                           / _HARNESS

  optional, every role: SGE_<ROLE>_REASONING_EFFORT -- how hard the model thinks
  (e.g. low | medium | high), passed as it is written: to the chat call for P and
  H', to the harness for I and C. Unset, the provider's own default holds.

Every role is set the same way, and only by its own settings: nothing falls
back to another role, and nothing to a provider this code would have to know.
Two roles on the same model repeat the same values -- which is what makes it
visible that they are the same (the cockpit says so when H' reviews with P's
model). P and H' are chat calls from here, against an OpenAI-compatible
endpoint. I and C are AGENTS, run by a harness -- the agent CLI that plays the
role -- which is the fourth setting of those two. The harness decides how the
endpoint is handed over and what API it has to speak. There is one, and it is
REQUIRED for I and C: `codex-cli`, the Codex CLI (https://github.com/openai/codex,
the `codex` command), run as `codex exec` against an OpenAI-compatible endpoint
(agent/codex_cli.py). A second harness is a second adapter, and an entry in
HARNESSES.

Everything is read at CALL time, not import time, so a .env loaded after the
import still counts.
"""
from __future__ import annotations

import json
import os

import openai

ROLES = ("planner", "reviewer", "intent", "coder")
AGENT_ROLES = ("intent", "coder")
FIELDS = ("BASE_URL", "API_KEY", "MODEL")
OPTIONAL = ("REASONING_EFFORT",)
# harness -> the executable it needs on PATH
HARNESSES = {"codex-cli": "codex"}


def fields(role: str) -> tuple[str, ...]:
    """The settings a role takes: three, and a HARNESS for an agent role."""
    return FIELDS + (("HARNESS",) if role in AGENT_ROLES else ())


def variable(role: str, field: str) -> str:
    """SGE_<ROLE>_<FIELD> -- the name, which is safe to show; never its value."""
    return f"SGE_{role.upper()}_{field}"


def _setting(role: str, field: str) -> str:
    return (os.environ.get(variable(role, field)) or "").strip()


def endpoint(role: str) -> dict:
    """{base_url, api_key, model, harness, key_from} for a role, from its own
    settings and nothing else (`harness` is '' for a chat role). `key_from`
    names the variable the key came from ('' when there is none), never the
    key -- it is safe to log."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; one of {ROLES}")
    key = _setting(role, "API_KEY")
    return {"base_url": _setting(role, "BASE_URL"), "api_key": key,
            "model": _setting(role, "MODEL"),
            "harness": _setting(role, "HARNESS") if role in AGENT_ROLES else "",
            "reasoning_effort": _setting(role, "REASONING_EFFORT"),
            "key_from": variable(role, "API_KEY") if key else ""}


def missing(role: str) -> list[str]:
    """What keeps this role from being called, one entry per setting: the name
    of each one that is unset, or '<name> is not a URL' for an endpoint that
    does not start with http:// or https://, or '<name> is still the
    placeholder' for a key copied from an example unchanged (`sk-...`) -- each
    fails only at the first call otherwise. [] when it can be called."""
    out = []
    for field in fields(role):
        value = _setting(role, field)
        if not value:
            out.append(variable(role, field))
        elif field == "BASE_URL" and not value.startswith(("http://", "https://")):
            out.append(f"{variable(role, field)} is not a URL")
        elif field == "API_KEY" and "..." in value:
            out.append(f"{variable(role, field)} is still the placeholder")
        elif field == "HARNESS" and value not in HARNESSES:
            out.append(f"{variable(role, field)} is not a known harness "
                       f"({' | '.join(HARNESSES)})")
    return out


def describe(role: str) -> str:
    """'<model> @ <base_url>' -- for logs and run records, with the reasoning
    effort when one is set. Never the key."""
    ep = endpoint(role)
    effort = f", reasoning {ep['reasoning_effort']}" if ep["reasoning_effort"] else ""
    return f"{ep['model'] or '(no model set)'} @ {ep['base_url'] or '(no URL set)'}{effort}"


def planner_model() -> str:
    """P's model."""
    return endpoint("planner")["model"]


def reviewer_model() -> str:
    """The reviewer's model."""
    return endpoint("reviewer")["model"]


def _client(role: str = "planner"):
    """An OpenAI-compatible client for the role's endpoint."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai not installed; run 'uv sync'.") from exc
    lacking = missing(role)
    if lacking:
        raise RuntimeError(f"the {role} is not configured: fix {', '.join(lacking)} in "
                           "cockpit/.env (never hardcode the key)")
    ep = endpoint(role)
    return OpenAI(base_url=ep["base_url"], api_key=ep["api_key"])


def _tool_args(resp) -> dict:
    """Return the function-call arguments dict, or {} if the model returned none
    (occasional flakiness) -- the caller degrades (semantic: to the lexical
    result; H': to no review) or says so (planner). Arguments cut off mid-JSON
    count as none, they must not raise (seen while a max_tokens limit was still
    set: finish_reason=length, 902 of 900 tokens spent reasoning); _call_tool
    reports the cut-off itself."""
    calls = resp.choices[0].message.tool_calls
    if not calls:
        return {}
    try:
        data = json.loads(calls[0].function.arguments or "")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _call_tool(client, tool: dict, prompt: str, *, model: str | None,
               role: str = "planner") -> tuple[dict, str | None]:
    """Make the model call `tool` once; return (its arguments, finish_reason).

    No max_tokens, on purpose: GLM-5.2 reasons before it answers, the reasoning
    counts against that limit, and how much it reasons varies from call to call.
    A draft of cockpit/example took 3137 tokens, 2796 of them reasoning; the old
    fixed 1500 cut every draft off. Without it OpenRouter allows the model's
    own maximum. The arguments are {} for an answer without usable ones (see
    _tool_args). Raises RuntimeError, with the reason, when the provider refuses
    (bad key, rate limit, outage -- a bare openai.APIError escaped the cockpit's
    handlers as a traceback) or when the answer is cut off even so: that is a
    failure to report, never a silent empty answer."""
    kwargs = dict(model=model or planner_model(), tools=[tool],
                  messages=[{"role": "user", "content": prompt}])
    effort = endpoint(role)["reasoning_effort"]      # the ROLE's, whichever model
    if effort:
        kwargs["reasoning_effort"] = effort
    forced = {"type": "function", "function": {"name": tool["function"]["name"]}}
    try:
        resp = client.chat.completions.create(**kwargs, tool_choice=forced)
    except openai.APIError as exc:
        # DeepSeek V4 reasons by default and rejects tool_choice outright
        # ("Thinking mode does not support this tool_choice", 400). Offering the
        # tool without forcing it is the same request minus the guarantee, and
        # the guide already ends with "Call <tool>" -- better than losing the
        # role to the provider. An answer without a call is reported below.
        if "tool_choice" not in str(exc):
            raise RuntimeError(f"the provider refused: {exc}") from exc
        try:
            resp = client.chat.completions.create(**kwargs)
        except openai.APIError as retry:
            raise RuntimeError(f"the provider refused: {retry}") from retry
    data = _tool_args(resp)
    finish = getattr(resp.choices[0], "finish_reason", None)
    if not data and finish == "length":
        raise RuntimeError("the answer was cut off at the model's output limit "
                           "(finish_reason=length; its reasoning counts against it). "
                           "Try again.")
    return data, finish
