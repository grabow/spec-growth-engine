"""The headless gate CLI: exit codes + git pre-commit hook installation."""
import os
import stat

import cli
from tests.conftest import write_spec


def test_gate_passes_on_clean_graph(graph_root, capsys):
    # graph_root: api.hello depends_on util, both declared; Python files, no drift
    code = cli.main(["gate", str(graph_root)])
    out = capsys.readouterr().out
    assert code == 0
    assert "gate: PASS" in out


def test_validate_blocks_on_undeclared_node(tmp_path, capsys):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["a"]}, code=[])
    write_spec(tmp_path / "a", id="a", parent="app", kind="component",
               contract={"provides": ["x()"]}, depends_on=["ghost"], code=[])
    code = cli.main(["validate", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "gate: BLOCK" in out
    assert "ghost" in out


def test_gate_blocks_on_code_drift(ts_root, capsys):
    # ts_root: checkout imports util WITHOUT declaring it -> drift BLOCK
    code = cli.main(["gate", str(ts_root)])
    out = capsys.readouterr().out
    assert code == 1
    assert "gate: BLOCK" in out
    assert "checkout -> util" in out


def test_duplicates_is_advisory_never_blocks(tmp_path, capsys):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["a", "b"]}, code=[])
    write_spec(tmp_path / "a", id="a", parent="app", kind="component",
               contract={"purpose": "Read PDFs.", "provides": ["readPdf(p): Text"]}, code=[])
    write_spec(tmp_path / "b", id="b", parent="app", kind="component",
               contract={"purpose": "Extract text from PDF.", "provides": ["pdfText(f): Text"]},
               code=[])
    code = cli.main(["duplicates", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0  # advisory: surfaces but never blocks
    assert "a ~ b" in out


def test_install_hook_writes_executable_hook(tmp_path, capsys):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)  # fake repo, no git binary needed
    code = cli.main(["install-hook", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    assert hook.is_file()
    assert os.access(hook, os.X_OK)
    text = hook.read_text()
    assert cli.HOOK_MARKER in text
    assert "cli.py" in text and "gate" in text
    assert str(tmp_path.resolve()) in text


def test_install_hook_refuses_foreign_hook_without_force(tmp_path, capsys):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    code = cli.main(["install-hook", str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 2
    assert "not ours" in err
    # --force overwrites
    assert cli.main(["install-hook", str(tmp_path), "--force"]) == 0
    assert cli.HOOK_MARKER in (hooks / "pre-commit").read_text()


def test_install_hook_errors_without_repo(tmp_path, capsys):
    code = cli.main(["install-hook", str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 2
    assert "no git repository" in err


# ---- `pending` is the inbox, not the HARD list (aligned with the cockpit) ------
#
# The Requests window has always shown four kinds; headless, `pending` showed
# one. A question the graph raised -- the mechanism run 08 found closed and run
# 09 used twice -- reached a person at a terminal only as a warning in
# `validate`, one screen further away than a decision should be.

def _asks(graph_root, **fields):
    spec = graph_root / "util" / "SPEC.md"
    text = spec.read_text(encoding="utf-8")
    spec.write_text(text.replace("code:", "\n".join(fields.pop("lines")) + "\ncode:"),
                    encoding="utf-8")


def test_pending_lists_a_decision_request(graph_root, capsys):
    _asks(graph_root, lines=["decision_requests:",
                             "- target: ARCHITECTURE.md",
                             "  proposal: log output goes to stderr",
                             "  reason: nothing says where it goes"])
    cli.main(["accept", str(graph_root), "--all"])
    capsys.readouterr()
    cli.main(["pending", str(graph_root)])
    out = capsys.readouterr().out
    assert "DECISION requested by util  ->  ARCHITECTURE.md" in out
    assert "proposal: log output goes to stderr" in out
    assert "reason:   nothing says where it goes" in out
    assert "1 request(s) await you as well: decision on util" in out


def test_pending_lists_a_requested_waiver(graph_root, capsys):
    _asks(graph_root, lines=["waiver:", "  state: requested", "  kind: known-gap",
                             "  reason: the sink cannot be tested offline"])
    cli.main(["accept", str(graph_root), "--all"])
    capsys.readouterr()
    cli.main(["pending", str(graph_root)])
    out = capsys.readouterr().out
    assert "WAIVER requested on util  (known-gap)" in out
    assert "reason: the sink cannot be tested offline" in out
    assert "only H grants" in out


def test_pending_says_so_when_nothing_awaits_you(graph_root, capsys):
    cli.main(["accept", str(graph_root), "--all"])
    capsys.readouterr()
    cli.main(["pending", str(graph_root)])
    assert "nothing awaits your decision" in capsys.readouterr().out


def test_an_untracked_project_still_shows_what_the_graph_asks(graph_root, capsys):
    """The accepted state is about CHANGES; a question needs no baseline."""
    _asks(graph_root, lines=["decision_requests:", "- target: ARCHITECTURE.md",
                             "  proposal: p", "  reason: r"])
    capsys.readouterr()
    cli.main(["pending", str(graph_root)])
    out = capsys.readouterr().out
    assert "DECISION requested by util" in out and "not tracked" in out
