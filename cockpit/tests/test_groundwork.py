"""Laying the floor of a new project (groundwork.py): what the steps write,
what they refuse, and the one place where a model's words reach a layer-1
artefact -- through an answer a person gave."""
import pytest

import cli
import groundwork
import layouts
from engine import accepted, parser

_ANSWERS = {"system_id": "tt", "purpose": "A time tracker.", "container": "track",
            "archetype": "python-uv-src", "by": "h",
            "invariants": list(groundwork.DEFAULT_INVARIANTS) + ["One session at a time."]}


def _floor(tmp_path, **over):
    answers = dict(_ANSWERS, **over)
    return groundwork.apply(tmp_path, groundwork.plan(answers))


# ---- the plan is what will be written, and nothing else ------------------------

def test_the_plan_writes_nothing(tmp_path):
    groundwork.plan(_ANSWERS)
    assert not list(tmp_path.iterdir()), "plan() is for showing; apply() writes"


def test_the_plan_is_the_floor_and_the_manuals_and_stops_there():
    """No component, no TASK.md, no run: the graph belongs to whoever grows it
    and the goal is H's prose."""
    kinds = [type(a).__name__ for a in groundwork.plan(_ANSWERS)]
    assert kinds == ["WriteRoot", "AddContainer", "WriteFloor", "AcceptAll",
                     "RecordAnswers", "RenderManuals"]


def test_the_manuals_are_rendered_for_this_project(tmp_path):
    """Rendering them by hand was the last manual step in a newcomer's path, and
    every value follows from the graph the floor just wrote."""
    _floor(tmp_path)
    for name in ("ORCHESTRATOR.md", "AGENTS.md"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "{{" not in text, f"{name} kept a placeholder"
        assert str(tmp_path) in text and "track" in text
        assert "GENERATED for this project" in text
    orchestrator = (tmp_path / "ORCHESTRATOR.md").read_text(encoding="utf-8")
    assert "cd track && uv run pytest" in orchestrator      # from testrun, not guessed
    assert "SPEC.md, ARCHITECTURE.md, track/SPEC.md" in orchestrator


def test_the_archetype_is_read_back_from_the_manifest(tmp_path):
    """Nothing records which archetype was picked, and nothing needs to: the
    manifest's file name is the choice."""
    _floor(tmp_path, archetype="rust-cargo")
    assert groundwork._archetype(tmp_path / "track") == "rust-cargo"
    text = (tmp_path / "ORCHESTRATOR.md").read_text(encoding="utf-8")
    assert "Rust / Cargo" in text and "cargo test" in text


def test_a_floor_with_no_manifest_says_the_test_command_is_missing(tmp_path):
    _floor(tmp_path, archetype=layouts.FREEFORM)
    text = (tmp_path / "ORCHESTRATOR.md").read_text(encoding="utf-8")
    assert "no build manifest" in text


def test_the_endpoint_report_names_every_role_and_no_key(monkeypatch):
    monkeypatch.setenv("SGE_PLANNER_API_KEY", "sk-SECRET")
    monkeypatch.setenv("SGE_PLANNER_MODEL", "m")
    monkeypatch.delenv("SGE_INTENT_MODEL", raising=False)
    report = dict(groundwork.endpoints())
    assert set(report) == {"planner", "reviewer", "intent", "coder"}
    assert "SECRET" not in str(report)
    assert report["intent"] == "no endpoint yet"      # an agent role needs a model


# ---- what a laid floor looks like ----------------------------------------------

def test_a_floor_is_a_root_a_container_a_manifest_and_a_baseline(tmp_path):
    said = _floor(tmp_path)
    nodes = parser.load_nodes(tmp_path)
    assert set(nodes) == {"tt", "tt.track"} or set(nodes) == {"tt", "track"}
    assert (tmp_path / "track" / "pyproject.toml").is_file()
    assert accepted.tracked(tmp_path), "the starting state is the baseline"
    assert any("accepted state" in line for line in said)


def test_the_container_carries_its_layout_and_owns_its_manifest(tmp_path):
    _floor(tmp_path)
    container = next(n for nid, n in parser.load_nodes(tmp_path).items() if nid != "tt")
    invariants = " ".join(container["contract"]["invariants"])
    assert "managed with uv" in invariants and "track/src/**/<name>/**" in invariants
    assert container["code"] == ["track/pyproject.toml"]


def test_the_answers_become_invariants_next_to_the_defaults(tmp_path):
    _floor(tmp_path)
    arch = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for line in groundwork.DEFAULT_INVARIANTS:
        assert f"- {line}" in arch
    assert "- One session at a time." in arch
    assert "## Quality goals" in arch and "## Decisions (ADRs)" in arch
    assert "- TODO" not in arch, "a floor of TODOs is what this step exists to avoid"


def test_a_floor_with_no_answers_still_carries_the_defaults(tmp_path):
    _floor(tmp_path, invariants=list(groundwork.DEFAULT_INVARIANTS))
    arch = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert arch.count("\n- ") >= len(groundwork.DEFAULT_INVARIANTS)


def test_the_floor_passes_the_gate(tmp_path, capsys):
    _floor(tmp_path)
    assert cli.main(["gate", str(tmp_path)]) == 0
    assert "gate: PASS" in capsys.readouterr().out


# ---- a floor is laid once ------------------------------------------------------

def test_it_refuses_a_project_that_already_has_a_root(tmp_path):
    _floor(tmp_path)
    assert "already holds a root node" in groundwork.refuses(tmp_path)
    with pytest.raises(ValueError, match="already holds a root node"):
        _floor(tmp_path)


def test_it_refuses_an_architecture_that_says_something(tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n## Invariants\n- Written by a person.\n", encoding="utf-8")
    assert "would replace it" in groundwork.refuses(tmp_path)


def test_a_bootstrapped_skeleton_is_not_something(tmp_path):
    """`- TODO` is what New Project leaves behind; laying a floor over it is the
    point of this step, not a collision."""
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture (cross-cutting)\n\n## Invariants (apply everywhere)\n- TODO\n",
        encoding="utf-8")
    assert groundwork.refuses(tmp_path) is None


# ---- the four questions, and P's part in them ----------------------------------

def test_four_questions_each_asking_for_one_invariant():
    assert len(groundwork.QUESTIONS) == 4
    keys = [q.key for q in groundwork.QUESTIONS]
    assert keys == ["persistence", "concurrency", "network", "anything_else"]
    for q in groundwork.QUESTIONS:
        assert q.ask.endswith("?") and q.hint


def test_p_words_an_answer_and_the_answer_survives_without_p():
    class _P:
        @staticmethod
        def one_line(prompt):
            assert "ONE invariant" in prompt and "two at a time" in prompt
            return "Two of these never run at the same time."

    question = groundwork.QUESTIONS[1]
    assert groundwork.propose(question, "no, never two at a time", _P()) \
        == "Two of these never run at the same time."

    class _Down:
        @staticmethod
        def one_line(_prompt):
            raise RuntimeError("no API key for the planner")

    assert groundwork.propose(question, "  no, never two at a time  ", _Down()) \
        == "no, never two at a time", "a floor must be layable offline"


# ---- the second door -----------------------------------------------------------

def test_the_cli_lays_the_same_floor(tmp_path, capsys):
    assert cli.main(["init", str(tmp_path), "--id", "shop", "--container", "api",
                     "--purpose", "A shop.", "--invariant", "Prices are integers.",
                     "--by", "h"]) == 0
    out = capsys.readouterr().out
    assert "root node `shop`" in out and "build manifest" in out
    arch = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "- Prices are integers." in arch
    assert groundwork.DEFAULT_INVARIANTS[0] in arch
    assert accepted.tracked(tmp_path)


def test_the_cli_refuses_to_lay_a_second_floor(tmp_path, capsys):
    cli.main(["init", str(tmp_path), "--id", "shop", "--container", "api"])
    capsys.readouterr()
    assert cli.main(["init", str(tmp_path), "--id", "shop2", "--container", "web"]) == 2
    assert "already holds a root node" in capsys.readouterr().err


@pytest.mark.parametrize("archetype", [k for k, _ in layouts.labels()])
def test_every_archetype_lays_a_floor_that_passes_the_gate(tmp_path, archetype, capsys):
    _floor(tmp_path, archetype=archetype)
    assert cli.main(["gate", str(tmp_path)]) == 0


# ---- the goal, when a run is intended ------------------------------------------

_GOAL = {"behaviours": "read add URL TITLE prints the id\nread list prints every entry",
         "always": "the list is still there tomorrow",
         "out_of_scope": "a graphical interface"}


def test_no_goal_is_written_unless_one_was_given(tmp_path):
    """H at the cockpit needs no TASK.md: the goal is in their head (3.12)."""
    _floor(tmp_path)
    assert not (tmp_path / "TASK.md").exists()
    assert not any(isinstance(a, groundwork.WriteTask) for a in groundwork.plan(_ANSWERS))


def test_the_goal_carries_the_persons_words_and_the_methods_standard(tmp_path):
    _floor(tmp_path, **_GOAL)
    task = (tmp_path / "TASK.md").read_text(encoding="utf-8")
    assert "- read add URL TITLE prints the id" in task          # as written
    assert "## What must always be true" in task
    assert "- the list is still there tomorrow" in task
    for line in groundwork.DONE_MEANS:                            # not theirs to invent
        assert f"- {line}" in task
    assert "## Deliberately not specified" in task and "intent author's" in task
    assert "## Out of scope" in task and "- a graphical interface" in task


def test_the_sections_a_task_does_not_need_stay_out(tmp_path):
    _floor(tmp_path, behaviours="one thing", always="", out_of_scope="")
    task = (tmp_path / "TASK.md").read_text(encoding="utf-8")
    assert "## What must always be true" not in task and "## Out of scope" not in task
    assert "## Done means" in task, "the yardstick is never optional"


def test_three_prompts_for_the_three_kinds_of_statement():
    """3.12: what it must DO, what must ALWAYS be true, what DONE means -- and the
    last of those is the one the method fills in."""
    assert [key for key, _ask, _hint in groundwork.TASK_PROMPTS] == [
        "behaviours", "always", "out_of_scope"]
    assert len(groundwork.DONE_MEANS) == 4


def test_the_cli_writes_the_goal_from_flags(tmp_path, capsys):
    assert cli.main(["init", str(tmp_path), "--id", "shop", "--container", "api",
                     "--does", "shop add ITEM", "--always", "prices are integers",
                     "--not-this", "a web interface"]) == 0
    task = (tmp_path / "TASK.md").read_text(encoding="utf-8")
    assert "- shop add ITEM" in task and "- prices are integers" in task
    assert "- a web interface" in task
    assert "read TASK.md once more" in capsys.readouterr().out



# ---- the goal comes from a template, like the manuals ------------------------

def test_the_task_comes_from_the_method_s_template(tmp_path):
    """Its structure and its "Done means" are the method's, and they live where
    the manuals' templates live -- editable without reading Python."""
    template = groundwork.TASK_TEMPLATE.read_text(encoding="utf-8")
    for key in ("PURPOSE", "MUST_DO", "ALWAYS", "OUT_OF_SCOPE"):
        assert "{{" + key + "}}" in template
    _floor(tmp_path, **_GOAL)
    task = (tmp_path / "TASK.md").read_text(encoding="utf-8")
    assert "{{" not in task and "TASK.md starts here" not in task
    assert task.startswith("# Task\n")
    for line in groundwork.DONE_MEANS:
        assert f"- {line}" in template


def test_an_empty_must_do_is_a_todo_not_a_missing_section(tmp_path):
    text = groundwork.task_text(groundwork.WriteTask("", "always this"))
    assert "## What it must do\n\n- TODO" in text


# ---- the same floor, again, elsewhere ----------------------------------------

def test_the_answers_are_recorded_with_the_floor(tmp_path):
    _floor(tmp_path, **_GOAL)
    saved = groundwork.answers_of(tmp_path)
    assert saved["system_id"] == _ANSWERS["system_id"]
    assert saved["invariants"] == [ln for ln in _ANSWERS["invariants"] if ln.strip()]
    assert saved["behaviours"] == _GOAL["behaviours"]
    assert "root" not in saved


def test_a_floor_laid_like_another_is_the_same_floor(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    _floor(first, **_GOAL)
    (first / "TASK.md").write_text((first / "TASK.md").read_text(encoding="utf-8")
                                   + "\nEdited after the floor was laid.\n", encoding="utf-8")
    groundwork.apply(second, groundwork.like(first))
    for name in ("SPEC.md", "ARCHITECTURE.md"):
        assert (second / name).read_text(encoding="utf-8") == \
            (first / name).read_text(encoding="utf-8"), name
    assert "Edited after the floor was laid." in (second / "TASK.md").read_text(encoding="utf-8")
    assert groundwork.answers_of(second) == groundwork.answers_of(first)


def test_like_refuses_a_project_laid_by_hand(tmp_path):
    with pytest.raises(ValueError, match="records no answers"):
        groundwork.like(tmp_path)


# ---- P proposes a fuller goal; the person decides -------------------------------

def test_the_goal_is_read_back_from_a_task(tmp_path):
    text = groundwork.task_text(groundwork.WriteTask(
        "read add URL\nread list", "the list survives a restart", "a GUI", "A reading list."))
    goal = groundwork.goal_of(text)
    assert goal == {"purpose": "A reading list.", "behaviours": "read add URL\nread list",
                    "always": "the list survives a restart", "out_of_scope": "a GUI"}


class _Planner:
    """P, scripted: records what it was given, answers with a fixed proposal."""
    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def propose_goal(self, purpose, must_do, always, out_of_scope, **kw):
        self.seen.append((purpose, must_do, always, out_of_scope, kw))
        return self.answer


def test_p_proposes_the_goal_as_lines_the_person_edits():
    p = _Planner({"must_do": ["a", "b"], "always": ["c"], "out_of_scope": []})
    out = groundwork.suggest_goal("pong", "- TODO", "", "", p,
                                  architecture="- deterministic", stack="Python / uv")
    assert out == {"behaviours": "a\nb", "always": "c", "out_of_scope": ""}
    purpose, must_do, _always, _oos, kw = p.seen[0]
    assert (purpose, must_do) == ("pong", "")           # the template's TODO is not a wish
    assert kw == {"architecture": "- deterministic", "stack": "Python / uv"}
    assert groundwork.suggest_goal("x", "y", "", "", _Planner(None)) is None


def test_the_planner_keeps_the_persons_words_and_says_what_not_how(monkeypatch):
    import json
    from agent import planner
    from tests.test_assist import _client_answering, _Resp
    requests = []
    answer = json.dumps({"must_do": ["`uv run pong` opens a window", "arrow keys move"],
                         "always": ["logic runs without a window"], "out_of_scope": ["sound"]})
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls"), requests=requests))
    out = planner.propose_goal("a game like pong", "A pong game against a bot.",
                               architecture="- Deterministic", stack="Python / uv")
    assert out["must_do"][0] == "`uv run pong` opens a window"
    prompt = requests[0]["messages"][0]["content"]
    assert "keep every statement the person wrote" in prompt
    assert "Say WHAT, never HOW" in prompt and "Never contradict an invariant" in prompt
    assert "A pong game against a bot." in prompt and "- Deterministic" in prompt


def test_a_proposal_without_a_behaviour_is_no_proposal(monkeypatch):
    import json
    from agent import planner
    from tests.test_assist import _client_answering, _Resp
    answer = json.dumps({"must_do": [], "always": ["x"], "out_of_scope": []})
    monkeypatch.setattr(planner, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls")))
    assert planner.propose_goal("p", "m") is None
