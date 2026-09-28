"""Start a role as a codex agent, with the endpoint cockpit/.env gives it.

  uv run python role_agent.py intent [--json] PROMPT    the intent author I
  uv run python role_agent.py coder  [--json] PROMPT    the coder C
  uv run python role_agent.py --describe                who plays which role

A run starts I through orchestrate.py; `cli.py code` starts C through
agent/codex_cli.py directly. --describe prints model and endpoint per role --
never a key -- the same lines a run records in <root>/.sge/runs/NN.roles.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE / ".env")   # a value already in the environment wins
    except ImportError:  # pragma: no cover
        pass


def main(argv: list[str]) -> int:
    _load_env()
    from agent import codex_cli, llm
    if argv[:1] == ["--describe"]:
        for role in llm.ROLES:
            ep = llm.endpoint(role)
            runner = ((ep["harness"] or "(no harness)") if role in codex_cli.AGENT_ROLES
                      else "chat call")
            print(f"{role:9} {runner:10} {llm.describe(role)}   "
                  f"key: {ep['key_from'] or '(none)'}")
            lacking = llm.missing(role)
            if lacking:
                print(f"{'':9} NOT CONFIGURED: fix {', '.join(lacking)} in cockpit/.env")
        return 0
    if len(argv) < 2 or argv[0] not in codex_cli.AGENT_ROLES:
        print(__doc__, file=sys.stderr)
        return 2
    role, rest = argv[0], argv[1:]
    json_events = "--json" in rest
    prompt = [a for a in rest if a != "--json"]
    if len(prompt) != 1:
        print("error: give exactly one PROMPT", file=sys.stderr)
        return 2
    try:
        cmd, env = codex_cli.command(role, json_events=json_events)
    except RuntimeError as exc:
        print(f"{role} unavailable: {exc}", file=sys.stderr)
        return 2
    # codex exec waits on an open stdin (codex_cli docstring): give it none
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.execvpe(cmd[0], cmd + prompt, env)
    return 0   # pragma: no cover -- execvpe does not return


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
