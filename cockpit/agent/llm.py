"""What every model-backed role shares: one client, one call, one parser -- and
one ENDPOINT per role, so which model, at which provider, plays which role is
a choice.

  role        what it does                 set in cockpit/.env
  ----------  ---------------------------  -----------------------------------
  planner  P  intent -> SPEC.md            SGE_PLANNER_BASE_URL / _API_KEY / _MODEL
  reviewer H' drafts, delegation, goals    SGE_REVIEWER_...  (each unset field: P's)
  intent   I  goal -> node intents (a run) SGE_INTENT_...    (URL, key: P's if unset)
  coder    C  SPEC -> code                 SGE_CODER_...     (URL, key: P's if unset)

Every endpoint is OpenAI-compatible: P and H' are called from here; I and C are
agents run by `codex exec` (agent/codex_cli.py) against the same kind of
endpoint. A key comes from SGE_<ROLE>_API_KEY, or -- to keep it out of every
file -- from the macOS keychain: SGE_<ROLE>_KEYCHAIN=<service name>, read the
way ~/.claude/provider-switch.zsh reads DeepSeek's. The planner's defaults are
OpenRouter and OPENROUTER_API_KEY, so a .env from before stays valid.

P and H' may be the same model; then H' reviews what its own model wrote, and
the cockpit says so. Everything is read at CALL time, not import time, so a
.env loaded after the import still counts.
"""
from __future__ import annotations

import json
import os
import subprocess

import openai

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "z-ai/glm-5.2"
ROLES = ("planner", "reviewer", "intent", "coder")


def _setting(role: str, field: str) -> str:
    return (os.environ.get(f"SGE_{role.upper()}_{field}") or "").strip()


def _key(role: str) -> tuple[str, str]:
    """(key, where it came from) -- the second is safe to log, the first never."""
    key = _setting(role, "API_KEY")
    if key:
        return key, f"SGE_{role.upper()}_API_KEY"
    service = _setting(role, "KEYCHAIN")
    if not service:
        return "", ""
    try:
        run = subprocess.run(["security", "find-generic-password", "-a",
                              os.environ.get("USER", ""), "-s", service, "-w"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    key = run.stdout.strip() if run.returncode == 0 else ""
    return key, (f"keychain: {service}" if key else "")


def endpoint(role: str) -> dict:
    """{base_url, api_key, model, key_from} for a role. Unset fields fall back:
    the reviewer to the planner field by field; intent and coder take the
    planner's URL and key (not its model -- that must be chosen); the planner to
    OpenRouter, OPENROUTER_API_KEY and DEFAULT_MODEL. `key_from` names WHERE the
    key came from, never the key -- it is safe to log."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; one of {ROLES}")
    if role == "planner":
        own, source = _key("planner")
        return {"base_url": _setting("planner", "BASE_URL") or OPENROUTER_BASE,
                "api_key": own or os.environ.get("OPENROUTER_API_KEY", ""),
                "model": _setting("planner", "MODEL") or DEFAULT_MODEL,
                "key_from": source or "OPENROUTER_API_KEY"}
    base = endpoint("planner")
    own, source = _key(role)
    model = _setting(role, "MODEL") or (base["model"] if role == "reviewer" else "")
    return {"base_url": _setting(role, "BASE_URL") or base["base_url"],
            "api_key": own or base["api_key"],
            "model": model,
            "key_from": source or f"the planner's ({base['key_from']})"}


def describe(role: str) -> str:
    """'<model> @ <base_url>' -- for logs and run records. Never the key."""
    ep = endpoint(role)
    return f"{ep['model'] or '(no model set)'} @ {ep['base_url']}"


def planner_model() -> str:
    """P's model."""
    return endpoint("planner")["model"]


def reviewer_model() -> str:
    """The reviewer's model; the planner's when none is set."""
    return endpoint("reviewer")["model"]


def _client(role: str = "planner"):
    """An OpenAI-compatible client for the role's endpoint."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai not installed; run 'uv sync'.") from exc
    ep = endpoint(role)
    if not ep["api_key"]:
        raise RuntimeError(
            f"no API key for the {role}: set SGE_{role.upper()}_API_KEY or "
            f"SGE_{role.upper()}_KEYCHAIN in cockpit/.env"
            + (", or OPENROUTER_API_KEY" if role in ("planner", "reviewer") else "")
            + " (never hardcode the key)."
        )
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


def _call_tool(client, tool: dict, prompt: str, *,
               model: str | None) -> tuple[dict, str | None]:
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
