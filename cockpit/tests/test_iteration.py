"""The rounds of an orchestrated run (AUTONOMY.md: the run): I's claim, E's rule, the
facts H' checks the goal by, and the driver that resumes the same session.
codex, the floor and H' are stubs here -- the suite never starts an agent or
reaches a model. graph_root: app > api > api.hello (depends_on util), util."""
import io
import json
import subprocess
from pathlib import Path

import pytest

import orchestrate
from agent import codex_cli, reviewer
from engine import accepted, iteration, parser
from tests.test_assist import _client_answering, _Resp

REPO = Path(__file__).resolve().parents[2]


def _log(root):
    path = root / ".sge" / "autonomy.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


# ---- I's claim ------------------------------------------------------------------

@pytest.mark.parametrize("message,expected", [
    ("Slice 3 closed, tests green.\n\nDONE", ("DONE", "")),
    ("**DONE**", ("DONE", "")),
    ("`DONE`\n", ("DONE", "")),
    ("x\nBLOCKED: svc.cli needs a decision by H", ("BLOCKED", "svc.cli needs a decision by H")),
    ("The gate needs a waiver only H can grant.\nBLOCKED",
     ("BLOCKED", "The gate needs a waiver only H can grant.")),
    ("DONE with the first slice.\nNow the second.", (None, "")),   # only the last line
    ("Done.", (None, "")),                                            # the line is DONE
    ("", (None, "")),
    (None, (None, "")),
])
def test_the_claim_is_the_last_line(message, expected):
    assert iteration.claim(message) == expected


def test_the_manuals_teach_the_lines_the_rule_reads():
    """The claim is a convention between the manual and this parser: if one
    changes, the other must."""
    for manual in ("ORCHESTRATOR.template.md", "AGENTS.template.md"):
        text = (REPO / "spec-growth-engine" / manual).read_text(encoding="utf-8")
        section = text[text.index("## When you stop"):]
        assert "DONE                  the task is done" in section
        assert "BLOCKED: <reason>     you cannot go on honestly" in section
        assert "stalled" in section
    assert iteration.claim("DONE")[0] == "DONE"
    assert iteration.claim("BLOCKED: <reason>") == ("BLOCKED", "<reason>")


# ---- E's rule -------------------------------------------------------------------

@pytest.mark.parametrize("kw,outcome", [
    (dict(round_no=1, failed="codex exited with 1", worked=True), "error"),
    (dict(round_no=2, failed=None, worked=False), "stalled"),
    (dict(round_no=1, failed=None, worked=False), None),  # a first round: checked
    (dict(round_no=3, failed=None, worked=True), None),
])
def test_what_ends_a_run_before_the_floor(kw, outcome):
    """BLOCKED is not among them: E measures first (see the rule after the floor)."""
    round_no = kw.pop("round_no")
    step = iteration.stop_early(round_no, **kw)
    assert (step or {}).get("outcome") == outcome


_GAPS = {"gaps": ["Increment 3, hyphens -- no test for a--b"]}


@pytest.mark.parametrize("round_no,claimed,green,goal,expected", [
    (1, "DONE", False, None, ("resume", None)),               # DONE is a claim
    (5, "DONE", False, None, ("stop", "limit")),
    (1, None, True, {"gaps": []}, ("stop", "done")),          # the verdict, not the claim
    (1, "DONE", True, _GAPS, ("resume", None)),
    (5, "DONE", True, _GAPS, ("stop", "limit")),
    (1, "DONE", True, {"unavailable": "no key"}, ("stop", "unchecked")),
    (1, None, True, {"unavailable": "no key"}, ("resume", None)),
    (5, None, True, {"unavailable": "no key"}, ("stop", "limit")),
])
def test_the_rule_after_the_floor(round_no, claimed, green, goal, expected):
    step = iteration.decide(round_no, 5, claimed=claimed, floor_green=green, goal=goal)
    assert (step["next"], step["outcome"]) == expected


def test_the_limit_says_what_was_still_missing():
    step = iteration.decide(2, 2, claimed="DONE", floor_green=True, goal=_GAPS)
    assert step["why"] == "2 round(s), and H' found 1 gap(s)"


# ---- what I is told when it is sent back ----------------------------------------

_RED = {"tests": {"passed": False, "text": "FAIL  /w/svc  (uv run pytest): 1 failed\n"
                                          "      evidence recorded for: svc.words\n"},
        "gate": {"passed": False, "text": "HARD errors: 1\n  [x] orphan code: svc/x.py\n"
                                          "gate: BLOCK\n"},
        "green": False}
_GREEN = {"tests": {"passed": True, "text": "PASS  /w/svc  (uv run pytest): 40 passed\n"},
          "gate": {"passed": True, "text": "warnings: 1\n  [!] HARD CHANGE PENDING on svc.cli\n"},
          "green": True}


def test_a_red_floor_is_passed_on_line_by_line():
    text = iteration.resume_prompt(2, 5, _RED, None)
    assert text.startswith("ROUND 2 of at most 5.")
    assert "- FAIL  /w/svc  (uv run pytest): 1 failed" in text
    assert "- orphan code: svc/x.py" in text
    assert "evidence recorded" not in text


def test_the_gaps_are_passed_on_and_the_way_out_is_named():
    text = iteration.resume_prompt(3, 5, _GREEN, _GAPS)
    assert "- Increment 3, hyphens -- no test for a--b" in text
    assert "BLOCKED: <reason>" in text and "the line DONE" in text
    assert "never by hand" in text


# ---- the facts H' checks the goal by ----------------------------------------------

def _tests_in(root: Path, name="test_hello.py", body="def test_greets():\n    pass\n"):
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / name).write_text(body, encoding="utf-8")


def test_the_facts_hold_the_specs_the_tests_and_the_floor(graph_root):
    _tests_in(graph_root)
    (graph_root / ".venv" / "lib").mkdir(parents=True)
    (graph_root / ".venv" / "lib" / "test_vendored.py").write_text("x", encoding="utf-8")
    text = iteration.facts(parser.load_nodes(graph_root), graph_root, _GREEN, [graph_root])
    assert "THE FLOOR: green" in text
    assert "PASS  /w/svc  (uv run pytest): 40 passed" in text
    assert "HARD CHANGE PENDING on svc.cli" in text           # a warning, as a fact
    assert "--- api.hello" in text and "greet()" in text      # every node's frontmatter
    assert "_path" not in text                                 # not the parser's own keys
    assert "def test_greets" in text                           # the test's source
    assert "test_vendored" not in text                         # not what the engine excludes


def test_over_the_budget_a_test_file_shows_its_names(graph_root, monkeypatch):
    monkeypatch.setattr(iteration, "TEST_SOURCE_BUDGET", 10)
    _tests_in(graph_root, body="def test_one():\n    '''long'''\n\ndef test_two():\n    pass\n")
    text = iteration.facts(parser.load_nodes(graph_root), graph_root, _GREEN, [graph_root])
    assert "names only" in text and "  test_one\n  test_two" in text
    assert "'''long'''" not in text


def test_the_facts_name_the_pending_hard_changes(graph_root):
    accepted.accept_all(parser.load_nodes(graph_root), graph_root, by="setup")
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("log()", "write(line)"),
                    encoding="utf-8")
    text = iteration.facts(parser.load_nodes(graph_root), graph_root, _GREEN, [])
    pending = text[text.index("PENDING HARD CHANGES"):text.index("THE TESTS")]
    assert "- util: breaking" in pending


# ---- H' checks the goal -----------------------------------------------------------

def test_h_prime_is_given_the_task_and_the_facts_not_the_claim(monkeypatch):
    requests = []
    answer = json.dumps({"summary": "one gap", "gaps": '["Done means, window -- no test"]'})
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls"), requests=requests))
    result = reviewer.check_goal("# Task\n## Done means\n- a window", "THE FLOOR: green")
    assert result["gaps"] == ["Done means, window -- no test"]   # decoded, as GLM sends it
    prompt = requests[0]["messages"][0]["content"]
    assert "TASK.md:\n# Task" in prompt and "FACTS (computed by the engine):" in prompt
    assert "WHAT I SAID" not in prompt and "max_tokens" not in requests[0]


def test_no_gap_is_a_met_goal(monkeypatch):
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(json.dumps({"summary": "met", "gaps": []}), "tool_calls")))
    assert reviewer.check_goal("t", "f")["gaps"] == []


def test_an_unreachable_reviewer_is_a_fact_not_a_crash(graph_root, monkeypatch):
    def refuse(*_a, **_k):
        raise RuntimeError("no API key for the reviewer")
    monkeypatch.setattr(reviewer, "check_goal", refuse)
    assert orchestrate.goal(str(graph_root), "t", _GREEN) == {
        "unavailable": "no API key for the reviewer"}


def test_a_goal_check_is_logged_with_its_model(graph_root, monkeypatch):
    monkeypatch.setattr(reviewer, "check_goal", lambda task, facts, previous=():
                        {"gaps": ["a -- b"], "summary": "", "model": "glm"})
    orchestrate.goal(str(graph_root), "t", _GREEN)
    assert _log(graph_root)[-1] == {**_log(graph_root)[-1], "actor": "H'", "by": "glm",
                                    "action": "goal-checked", "gaps": 1}


# ---- the floor --------------------------------------------------------------------

def test_the_floor_is_computed_without_writing_into_the_stream(graph_root, capsys):
    fl = orchestrate.floor(str(graph_root))
    assert fl["green"] and "spec-growth-engine gate: PASS" in fl["gate"]["text"]
    assert capsys.readouterr().out == ""       # stdout is the run's event stream


# ---- the session and the resume ----------------------------------------------------

def test_resume_continues_the_same_session(monkeypatch):
    monkeypatch.setenv("SGE_INTENT_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("SGE_INTENT_API_KEY", "k")
    monkeypatch.setenv("SGE_INTENT_MODEL", "m")
    monkeypatch.setenv("SGE_INTENT_HARNESS", "codex-cli")
    argv, _env = codex_cli.command("intent", json_events=True, resume="t-1")
    assert argv[:3] == ["codex", "exec", "resume"]
    assert argv[-2:] == ["--json", "t-1"]                      # the prompt follows the id
    assert "--dangerously-bypass-approvals-and-sandbox" in argv and "-m" in argv


class _Popen:
    def __init__(self, lines, code=0):
        self.stdout, self._code = iter(lines), code

    def wait(self):
        return self._code


def _events(*events):
    return [json.dumps(e) + "\n" for e in events]


def test_a_session_is_passed_through_and_read(monkeypatch):
    seen = {}
    lines = _events(
        {"type": "thread.started", "thread_id": "t-1"},
        {"type": "error", "message": "Reconnecting... 1/5"},       # survived: not fatal
        {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "all\nDONE"}},
        {"type": "turn.completed", "usage": {}})
    monkeypatch.setattr(orchestrate.subprocess, "Popen",
                        lambda argv, **kw: seen.update(argv=argv, **kw) or _Popen(lines))
    out = io.StringIO()
    info = orchestrate.session(["codex", "exec"], "go", {"A": "1"}, out)
    assert info == {"thread": "t-1", "message": "all\nDONE", "worked": 1, "failed": None}
    assert out.getvalue() == "".join(lines)
    assert seen["stdin"] is subprocess.DEVNULL and seen["argv"] == ["codex", "exec", "go"]


def test_a_session_that_dies_says_why(monkeypatch):
    lines = _events({"type": "thread.started", "thread_id": "t-1"},
                    {"type": "error", "message": "stream disconnected"})
    monkeypatch.setattr(orchestrate.subprocess, "Popen", lambda argv, **kw: _Popen(lines, 1))
    info = orchestrate.session(["codex"], "go", {}, io.StringIO())
    assert info["failed"] == "codex exited with 1: stream disconnected"


# ---- the rounds -------------------------------------------------------------------

def _info(message="DONE", worked=3, failed=None, thread="t-1"):
    return {"thread": thread, "message": message, "worked": worked, "failed": failed}


class _Run:
    """Scripted sessions, floors and goals; records what the driver did."""
    def __init__(self, root, sessions, floors=(), goals=()):
        self.root, self.started, self.floors_checked, self.goals_checked = root, [], 0, 0
        self.previous: list[list[str]] = []
        self._sessions, self._floors, self._goals = iter(sessions), iter(floors), iter(goals)
        self.out = io.StringIO()

    def start(self, argv, text, env, out):
        self.started.append((argv, text))
        return next(self._sessions)

    def floor(self, root):
        self.floors_checked += 1
        return next(self._floors)

    def goal(self, root, task, fl, previous=()):
        self.goals_checked += 1
        self.previous.append(list(previous))
        return next(self._goals)

    @staticmethod
    def command(role, *, json_events=False, resume=None):
        return ["codex", "exec", *(["resume"] if resume else []), "--json",
                *([resume] if resume else [])], {}

    def __call__(self, max_rounds=5):
        return orchestrate.run(str(self.root), "the task", "first prompt", max_rounds,
                               out=self.out, start=self.start, check_floor=self.floor,
                               check_goal=self.goal, command=self.command)

    def events(self, kind):
        return [e for e in map(json.loads, self.out.getvalue().splitlines())
                if e["type"] == kind]


def test_gaps_send_i_back_into_the_same_session_until_the_goal_is_met(graph_root):
    run = _Run(graph_root, [_info(), _info()], [_GREEN, _GREEN], [_GAPS, {"gaps": []}])
    assert run() == "done"
    (first_argv, first_text), (argv, text) = run.started
    assert first_text == "first prompt" and "resume" not in first_argv
    assert argv[2] == "resume" and argv[-1] == "t-1"
    assert "ROUND 2 of at most 5" in text and "no test for a--b" in text
    rounds = run.events("sge.round")
    assert [(r["round"], r["next"], r["gaps"]) for r in rounds] == [
        (1, "resume", _GAPS["gaps"]), (2, "stop", [])]
    assert run.events("sge.run") == [{"type": "sge.run", "outcome": "done", "rounds": 2,
                                      "why": "the floor is green, H' found no gap, and "
                                             "nothing waits for H",
                                      "thread": "t-1"}]
    logged = [e for e in _log(graph_root) if e["action"] == "round"]
    assert [(e["actor"], e["round"], e["next"]) for e in logged] == [
        ("E", 1, "resume"), ("E", 2, "stop")]


def test_blocked_over_a_red_floor_stops_without_asking_the_reviewer(graph_root):
    """E measures the floor even here (it is cheap and deterministic); on a red
    floor there is no goal to check, so H' is not asked."""
    run = _Run(graph_root, [_info("I need a decision.\nBLOCKED: ARCHITECTURE.md is H's")],
               [_RED])
    assert run() == "blocked"
    assert run.floors_checked == 1 and run.goals_checked == 0
    assert run.events("sge.run")[0]["why"] == "ARCHITECTURE.md is H's"


def test_a_red_floor_is_sent_back_without_asking_h_prime(graph_root):
    run = _Run(graph_root, [_info(), _info()], [_RED, _GREEN], [{"gaps": []}])
    assert run() == "done"
    assert run.goals_checked == 1                     # only for the green floor
    assert "orphan code: svc/x.py" in run.started[1][1]
    assert run.events("sge.round")[0]["floor"] == "red"


def test_the_round_limit_ends_a_run_that_never_meets_the_goal(graph_root):
    run = _Run(graph_root, [_info(), _info()], [_GREEN, _GREEN], [_GAPS, _GAPS])
    assert run(max_rounds=2) == "limit"
    assert len(run.started) == 2
    assert run.events("sge.round")[-1]["gaps"] == _GAPS["gaps"]   # H reads what is open


def test_a_resumed_round_without_work_ends_as_stalled(graph_root):
    run = _Run(graph_root, [_info(), _info("That test exists already.\nDONE", worked=0)],
               [_GREEN], [_GAPS])
    assert run() == "stalled"
    assert run.floors_checked == 1


def test_a_failed_session_ends_the_run(graph_root):
    run = _Run(graph_root, [_info(failed="codex exited with 1", thread=None)])
    assert run() == "error"


def test_one_round_is_a_run_without_rounds(graph_root):
    run = _Run(graph_root, [_info()], [_GREEN], [_GAPS])
    assert run(max_rounds=1) == "limit" and len(run.started) == 1


# ---- the command --------------------------------------------------------------------

def test_the_exit_code_says_whether_the_run_ended_done(tmp_path, monkeypatch):
    task = tmp_path / "TASK.md"
    task.write_text("# Task", encoding="utf-8")
    monkeypatch.setattr(orchestrate, "_load_env", lambda: None)
    seen = {}
    monkeypatch.setattr(orchestrate, "after", lambda root: ["test      PASS"])
    monkeypatch.setattr(orchestrate, "run", lambda root, t, prompt, rounds, out, unsupervised:
                        seen.update(task=t, prompt=prompt, rounds=rounds,
                                    unsupervised=unsupervised) or "done")
    assert orchestrate.main([str(tmp_path), "go", "--task", str(task), "--max-rounds", "3"]) == 0
    assert seen == {"task": "# Task", "prompt": "go", "rounds": 3, "unsupervised": False}
    runs = tmp_path / ".sge" / "runs"
    assert sorted(p.name for p in runs.iterdir()) == ["01.jsonl", "01.log", "01.roles"]
    assert "after     test      PASS" in (runs / "01.log").read_text(encoding="utf-8")
    monkeypatch.setattr(orchestrate, "run", lambda *a, **k: "limit")
    assert orchestrate.main([str(tmp_path), "go", "--task", str(task)]) == 1

    def unavailable(*_a, **_k):
        raise RuntimeError("no model for the intent")
    monkeypatch.setattr(orchestrate, "run", unavailable)
    assert orchestrate.main([str(tmp_path), "go", "--task", str(task)]) == 2


# ---- a question the work rests on ------------------------------------------------

_ASKS = ["app -> ARCHITECTURE.md: notes are stored as one NDJSON file"]


@pytest.mark.parametrize("goal,requests,expected", [
    ({"gaps": []}, _ASKS, ("stop", "asking")),          # green, no gap, a question
    ({"gaps": []}, [], ("stop", "done")),
    (_GAPS, _ASKS, ("resume", None)),                    # a gap is work; work first
])
def test_an_open_decision_request_is_not_a_finished_run(goal, requests, expected):
    step = iteration.decide(1, 5, claimed="DONE", floor_green=True, goal=goal,
                            requests=requests)
    assert (step["next"], step["outcome"]) == expected


def test_the_asking_outcome_names_the_question(graph_root):
    step = iteration.decide(1, 5, claimed=None, floor_green=True, goal={"gaps": []},
                            requests=_ASKS)
    assert _ASKS[0] in step["why"]


def test_the_floor_reads_the_questions_the_graph_raises(graph_root):
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace(
        "code:", "decision_requests:\n- target: ARCHITECTURE.md\n"
                 "  proposal: log output goes to stderr\n  reason: nothing says where\ncode:"),
        encoding="utf-8")
    fl = orchestrate.floor(str(graph_root))
    assert fl["requests"] == ["util -> ARCHITECTURE.md: log output goes to stderr"]


def test_a_pending_hard_change_is_not_a_question(graph_root):
    """It is a decision about work already done, and its own diff shows it."""
    accepted.accept_all(parser.load_nodes(graph_root), graph_root, by="setup")
    spec = graph_root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("log()", "write(line)"),
                    encoding="utf-8")
    assert iteration.open_requests(parser.load_nodes(graph_root)) == []


def test_the_facts_tell_the_reviewer_what_is_being_asked(graph_root):
    """So H' does not report an open question as a gap of its own."""
    nodes = parser.load_nodes(graph_root)
    nodes["util"]["decision_requests"] = [
        {"target": "ARCHITECTURE.md", "proposal": "p", "reason": "r"}]
    text = iteration.facts(nodes, graph_root, _GREEN, [])
    assert "DECISION REQUESTS THE GRAPH RAISED" in text
    assert "util -> ARCHITECTURE.md: p" in text


def test_the_manual_tells_the_intent_author_what_to_do_with_one():
    manual = (REPO / "spec-growth-engine" / "ORCHESTRATOR.template.md").read_text(
        encoding="utf-8")
    section = manual[manual.index("## When a decision is above you"):]
    section = section[:section.index("## When you stop")]
    assert "add a decision request to ARCHITECTURE.md" in section
    assert "GRANTS nothing" in section
    assert "ASSUMES the decision" in section          # go on, and say so
    assert "shape depends on it" in section           # unless: BLOCKED
    assert "asking" in section


# ---- the reviewer's memory between rounds (run 11) ---------------------------
#
# Run 11 was sent back three times, each time for two DIFFERENT things, and
# converged only when it ran out of rounds. The check had no memory: it was
# handed the task and the facts every round and judged afresh, so a closed gap
# left no trace and a new one never had to stand next to the old.

def test_the_reviewer_is_asked_about_the_gaps_it_named_last_round(monkeypatch):
    requests = []
    answer = json.dumps({"summary": "s", "gaps": ["b -- still missing"],
                         "closed": ["a -- was missing"]})
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls"), requests=requests))
    result = reviewer.check_goal("t", "f", ["a -- was missing", "b -- still missing"])
    prompt = requests[0]["messages"][0]["content"]
    assert "GAPS YOU NAMED AFTER THE PREVIOUS ROUND" in prompt
    assert "- a -- was missing" in prompt
    assert result["closed"] == ["a -- was missing"] and result["gaps"] == ["b -- still missing"]


def test_the_first_round_asks_about_nothing(monkeypatch):
    requests = []
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(json.dumps({"summary": "s", "gaps": []}), "tool_calls"), requests=requests))
    assert reviewer.check_goal("t", "f")["closed"] == []
    # the guide mentions previous gaps in the abstract; the SECTION must be absent
    assert "GAPS YOU NAMED" not in requests[0]["messages"][0]["content"]


def test_the_guide_judges_what_is_said_not_where_it_stands():
    """A task may be plain prose: naming the headings would make the check
    depend on a shape TASK.md is not required to have (3.12)."""
    guide = reviewer._GOAL_GUIDE
    assert "however it likes" in guide and "no headings at all" in guide
    assert "Judge what is SAID, not where it stands" in guide
    assert "SPEC-GROWTH-ENGINE.md 3.12" in guide
    assert "converges by exhaustion, not by agreement" in guide


def test_the_driver_carries_last_round_s_gaps_into_the_next_check(graph_root):
    run = _Run(graph_root, [_info(), _info()], [_GREEN, _GREEN],
               [_GAPS, {"gaps": [], "closed": _GAPS["gaps"]}])
    assert run() == "done"
    assert run.previous == [[], _GAPS["gaps"]]          # round 1 has none, round 2 has them
    assert run.events("sge.round")[1]["closed"] == _GAPS["gaps"]


def test_an_unavailable_reviewer_does_not_erase_what_was_named(graph_root):
    """Its silence is not agreement: the next check still gets the open gaps."""
    run = _Run(graph_root, [_info(), _info(claim := "x"), _info()],
               [_GREEN, _GREEN, _GREEN],
               [_GAPS, {"unavailable": "no key"}, {"gaps": [], "closed": []}])
    assert run() == "done"
    assert run.previous == [[], _GAPS["gaps"], _GAPS["gaps"]]


# ---- the digest: the one file in the chain that had no test --------------------

def test_the_record_renders_a_round_and_the_end(tmp_path):
    """The run's log in the project is written by one writer (orchestrate.Record)
    through runlog -- the lines the cockpit's window shows. The stream is kept
    as it came, next to it."""
    events = [
        {"type": "thread.started", "thread_id": "t-1"},
        {"type": "sge.round", "round": 2, "claim": "DONE", "floor": "green",
         "gaps": ["a -- b"], "closed": ["c -- d"], "requests": ["n -> ARCHITECTURE.md: p"],
         "next": "resume", "why": "1 gap"},
        {"type": "sge.run", "outcome": "asking", "rounds": 2, "why": "1 request"}]
    stem = orchestrate.next_run(tmp_path)
    shown = io.StringIO()
    record = orchestrate.Record(stem, shown, readable=True)
    record.write("\n".join(json.dumps(e) for e in events) + "\nnot an event\n")
    record.close()
    log = stem.with_suffix(".log").read_text(encoding="utf-8")
    assert "START     thread t-1" in log
    assert "ROUND 2" in log and "gaps=1" in log and "closed=1" in log
    assert "missing   a -- b" in log and "asks H    n -> ARCHITECTURE.md: p" in log
    assert "RUN       ASKING after 2 round(s)" in log and "not an event" in log
    assert shown.getvalue() == log                       # --readable prints the same lines
    raw = stem.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["type"] for line in raw[:3]] == [e["type"] for e in events]
    assert orchestrate.next_run(tmp_path).name == "02"

def test_a_blocked_run_still_has_its_floor_measured(graph_root):
    """Run 12 stopped for H with 561 tests green and a passing gate, and the
    round record said nothing about it: BLOCKED skipped the floor. It still
    stops -- E measures first, and H' checks the goal on the green floor."""
    run = _Run(graph_root, [_info("I need an answer.\nBLOCKED: the store rule is H's")],
               [_GREEN], [_GAPS])
    assert run() == "blocked"
    assert run.floors_checked == 1 and run.goals_checked == 1
    round_event = run.events("sge.round")[0]
    assert round_event["floor"] == "green" and round_event["outcome"] == "blocked"


# ---- waiting for H is not being blocked, and not a gap (runs 11 and 12) ---------
#
# Run 12 said BLOCKED over a green floor and six questions for H: it was waiting.
# Run 11 was sent back three times for a root it could not move: H' reported as a
# gap what only H could close. Both are the same distinction, drawn in two places.

_WAITS = {"gaps": [], "waiting": ["the root is verified -- rests on the HARD change "
                                  "to svc, which is H's"]}


@pytest.mark.parametrize("floor_green,goal,requests,expected", [
    (True, {"gaps": []}, _ASKS, "asking"),         # it only waited: say so
    (True, _WAITS, [], "asking"),                   # H' named what waits for H
    (True, {"gaps": []}, [], "blocked"),            # nothing visible waits: H reads why
    (True, _GAPS, _ASKS, "blocked"),                # a disputed gap: H decides
    (True, {"unavailable": "no key"}, _ASKS, "blocked"),
    (False, None, _ASKS, "blocked"),                # a red floor is not waiting
])
def test_blocked_is_asking_when_all_that_is_left_waits_for_h(floor_green, goal, requests,
                                                             expected):
    step = iteration.decide(1, 5, claimed="BLOCKED", floor_green=floor_green, goal=goal,
                            requests=requests, why="the store rule is H's")
    assert (step["next"], step["outcome"]) == ("stop", expected)
    if expected == "blocked":
        assert step["why"] == "the store rule is H's"
    else:
        assert step["why"].startswith("the intent author said BLOCKED, but nothing is "
                                      "missing that it could close")


def test_what_waits_for_h_is_not_sent_back_as_a_gap():
    step = iteration.decide(1, 5, claimed="DONE", floor_green=True, goal=_WAITS)
    assert (step["next"], step["outcome"]) == ("stop", "asking")
    assert _WAITS["waiting"][0] in step["why"]


def test_run_12_ends_asking_with_its_floor_on_record(graph_root):
    run = _Run(graph_root, [_info("Six items await H.\nBLOCKED: 5 requests, 1 waiver")],
               [{**_GREEN, "requests": _ASKS}], [{"gaps": [], "waiting": []}])
    assert run() == "asking"
    event = run.events("sge.round")[0]
    assert event["claim"] == "BLOCKED" and event["floor"] == "green"
    assert event["requests"] == _ASKS


def test_the_goal_check_names_what_waits_apart_from_the_gaps(monkeypatch):
    answer = json.dumps({"summary": "s", "gaps": [], "waiting": ["w -- rests on svc"]})
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls")))
    assert reviewer.check_goal("t", "f")["waiting"] == ["w -- rests on svc"]
    guide = " ".join(reviewer._GOAL_GUIDE.split())
    assert "WAITING, not a gap" in guide and "only burns a round" in guide
    assert "move it to `waiting`" in guide


def test_the_digest_shows_what_waits():
    from runlog import lines
    shown = lines({"type": "sge.round", "round": 1, "gaps": [], "waiting": ["w -- x"],
                   "next": "stop", "outcome": "asking", "why": "1 item"})
    assert "waits H   w -- x" in shown


def test_the_manual_does_not_send_a_waiting_run_into_blocked():
    manual = " ".join((REPO / "spec-growth-engine" / "ORCHESTRATOR.template.md")
                      .read_text(encoding="utf-8").split())
    assert "STOP NORMALLY: say what waits" in manual
    assert "Waiting for H is not being blocked" in manual


# ---- what C is doing, while I waits on it ----------------------------------------
#
# A run whose coder worked for minutes showed nothing in that time: C writes to
# its own log, and I's stream is silent until C is done. It looked stalled.

def test_the_watch_reports_the_last_new_line_of_a_coder_log(tmp_path):
    import os
    logs = tmp_path / ".sge" / "code"
    logs.mkdir(parents=True)
    old = logs / "util-20260101T000000.log"
    old.write_text("from an earlier session\n", encoding="utf-8")
    os.utime(old, (1, 1))                                  # before the watch began
    out = io.StringIO()
    watch = orchestrate.CoderWatch(tmp_path, out)
    log = logs / "core.rules-20260929T125909.log"
    log.write_text("reading the spec\nwriting match.py\n\n", encoding="utf-8")
    watch.poll()
    watch.poll()                                           # nothing new: nothing said
    with open(log, "a", encoding="utf-8") as f:
        f.write("running the tests\n")
    watch.poll()
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [(e["type"], e["node"], e["line"]) for e in events] == [
        ("sge.coder", "core.rules", "writing match.py"),
        ("sge.coder", "core.rules", "running the tests")]
    assert events[0]["log"] == ".sge/code/core.rules-20260929T125909.log"


def test_the_run_passes_on_what_c_did_during_a_session(graph_root):
    """The watch runs while the session does -- and looks once more when it ends,
    so C's last line is not lost."""
    def session_that_codes(argv, text, env, out):
        log = graph_root / ".sge" / "code" / "util-20260929T130000.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("wrote util/log.py\n", encoding="utf-8")
        return _info()
    run = _Run(graph_root, [], [_GREEN], [{"gaps": []}])
    run.start = session_that_codes
    assert run() == "done"
    [coder] = run.events("sge.coder")
    assert (coder["node"], coder["line"]) == ("util", "wrote util/log.py")


def test_the_digest_shows_what_c_is_doing():
    from runlog import lines
    shown = lines({"type": "sge.coder", "node": "core.rules", "line": "writing match.py"})
    assert shown == ["C core.rules   writing match.py"]
