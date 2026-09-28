"""Starting a run, and reading its stream: orchestrate.blockers / first_prompt
and runlog.py, the rendering the cockpit's Run window and the run's own log
(<root>/.sge/runs/NN.log) share."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import orchestrate
import runlog
from agent import llm

COCKPIT = Path(__file__).resolve().parents[1]


# ---- what a run needs before it starts ---------------------------------------

def _ready(tmp_path, monkeypatch):
    """A project a run could start on: a root, the goal, both manuals, endpoints."""
    for name in ("SPEC.md", "TASK.md", "ORCHESTRATOR.md", "AGENTS.md"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    monkeypatch.setattr(llm, "missing", lambda role: [])
    monkeypatch.setattr(orchestrate.shutil, "which", lambda name: f"/usr/bin/{name}")
    return tmp_path


def test_a_ready_project_has_no_blockers(tmp_path, monkeypatch):
    assert orchestrate.blockers(_ready(tmp_path, monkeypatch)) == []


@pytest.mark.parametrize("missing,says", [("TASK.md", "no goal"),
                                          ("ORCHESTRATOR.md", "the intent author"),
                                          ("AGENTS.md", "the method"),
                                          ("SPEC.md", "no spec root")])
def test_each_missing_piece_is_named(tmp_path, monkeypatch, missing, says):
    """Named, not discovered three minutes in: a run that starts without its goal
    or its manual fails slowly, and the failure reads like the agent's."""
    root = _ready(tmp_path, monkeypatch)
    (root / missing).unlink()
    assert [line for line in orchestrate.blockers(root) if says in line]


def test_a_role_without_an_endpoint_blocks_the_run(tmp_path, monkeypatch):
    root = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "missing",
                        lambda role: ["SGE_CODER_BASE_URL is not a URL"] if role == "coder"
                        else [])
    [line] = [line for line in orchestrate.blockers(root) if "the coder" in line]
    assert "SGE_CODER_BASE_URL is not a URL" in line


def test_a_goal_elsewhere_is_accepted(tmp_path, monkeypatch):
    """The goal may live outside the spec root -- `--task FILE`."""
    root = _ready(tmp_path, monkeypatch)
    (root / "TASK.md").unlink()
    other = tmp_path.parent / "elsewhere.md"
    other.write_text("# goal\n", encoding="utf-8")
    assert orchestrate.blockers(root, other) == []


def test_the_first_prompt_says_where_the_method_is_and_how_to_end():
    prompt = orchestrate.first_prompt()
    assert "ORCHESTRATOR.md" in prompt and "TASK.md" in prompt
    assert "DONE" in prompt and "BLOCKED" in prompt
    assert str((COCKPIT.parent / "spec-growth-engine")) in prompt


# ---- the stream, rendered ----------------------------------------------------

def test_a_round_renders_what_it_found():
    out = runlog.lines({"type": "sge.round", "round": 2, "claim": "DONE", "floor": "green",
                        "gaps": ["the export is not tested"], "closed": ["a"],
                        "failures": [], "requests": ["svc: may I write ARCHITECTURE.md?"],
                        "next": "resume", "outcome": "", "why": "H' found 1 gap(s)"})
    assert out[0].startswith("ROUND 2   claim=DONE  floor=green  gaps=1  closed=1")
    assert "missing   the export is not tested" in out
    assert "asks H    svc: may I write ARCHITECTURE.md?" in out


def test_the_last_line_says_how_the_run_ended():
    out = runlog.lines({"type": "sge.run", "outcome": "asking", "rounds": 3,
                        "why": "1 decision request awaits H"})
    assert out == ["RUN       ASKING after 3 round(s): 1 decision request awaits H"]


@pytest.mark.parametrize("event,shown", [
    ({"type": "thread.started", "thread_id": "t1"}, "START     thread t1"),
    ({"type": "item.started", "item": {"type": "command_execution", "command": "cli.py gate"}},
     "$         cli.py gate"),
    ({"type": "item.completed", "item": {"type": "agent_message", "text": "DONE"}},
     "say       DONE"),
    ({"type": "turn.failed", "error": {"message": "rate limited"}}, "FAILED    rate limited"),
])
def test_codex_events_render_one_line_each(event, shown):
    assert runlog.lines(event) == [shown]


def test_an_event_of_another_format_is_not_this_ones():
    """None, not []: the run record keeps such a line as it came, instead of
    dropping it as an event worth no line (orchestrate.Record)."""
    assert runlog.lines({"type": "assistant", "message": {}}) is None
    assert runlog.lines({"type": "item.completed", "item": {"type": "reasoning"}}) == []


def test_a_missing_codex_cli_is_named_with_where_to_get_it(tmp_path, monkeypatch):
    """I and C run on the Codex CLI: without `codex` on PATH, nothing an agent
    does can start -- said before the run, with the way to fix it."""
    root = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "endpoint", lambda role: {"harness": "codex-cli"})
    monkeypatch.setattr(orchestrate.shutil, "which", lambda name: None)
    [line] = [line for line in orchestrate.blockers(root) if "PATH" in line]
    assert "`codex` is not on PATH" in line and "github.com/openai/codex" in line
