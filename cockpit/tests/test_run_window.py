"""The Run window in the real cockpit: what a person sees while an agent writes.

Each scenario (tests/gui_scenarios.py) drives the actual Tk widgets in its own
process -- see that module for why a subprocess. The stream is a fixed list of
events, so what is tested is the cockpit's half: the rendering, the reload after
a round, the lock on Draft and Revise, and what the end of a run says.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

COCKPIT = Path(__file__).resolve().parents[1]
SCENARIOS = COCKPIT / "tests" / "gui_scenarios.py"
TK_UNAVAILABLE = 77


@pytest.mark.parametrize("scenario", ["run_window", "run_window_comes_back",
                                      "run_locks_the_writers",
                                      "run_dialog_modes", "run_window_unsupervised",
                                      "new_project_scrolls", "new_project_suggests_a_goal",
                                      "edit_goal_with_p",
                                      "new_project_over_a_floor_keeps_the_dialog",
                                      "open_target_prepares_the_revise",
                                      "picking_a_target_loads_its_spec",
                                      "codex_builds_its_context",
                                      "check_goal_says_the_verdict",
                                      "rename_node_shows_the_plan_first",
                                      "code_affected_codes_in_order_and_locks",
                                      "find_in_any_text",
                                      "compact_shows_a_draft_and_a_lost_promise",
                                      "find_in_specs_and_open_a_gap",
                                      "gate_clears_soft_and_shows_what"])
def test_run_window(scenario):
    env = dict(os.environ, PYTHONPATH=str(COCKPIT))
    try:
        run = subprocess.run([sys.executable, str(SCENARIOS), scenario], cwd=COCKPIT, env=env,
                             capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{scenario}: the cockpit hung (no result within 60s)")
    if run.returncode == TK_UNAVAILABLE:
        pytest.skip(run.stdout.strip())
    assert run.returncode == 0, f"{scenario}:\n{run.stdout}\n{run.stderr[-2000:]}"
