"""An unsupervised run (AUTONOMY.md §2, run: off | on | unsupervised): between
rounds H' answers the decision requests in H's place, and decides the pending
HARD changes inside the delegation. Every answer is an ADR that waits for H's
review. H' is a stub; the suite never reaches a model."""
import io
import json

import pytest

import orchestrate
from agent import reviewer
from engine import accepted, autonomy, decisions, inbox, iteration, parser, unsupervised
from tests.test_assist import _client_answering, _Resp

_ARCH_REQ = ("- target: ARCHITECTURE.md\n  proposal: 'ADR: log output goes to stderr'\n"
             "  reason: nothing says where\n")
_NODE_REQ = ("- target: api\n  proposal: 'provides: + a health check'\n"
             "  reason: the task asks for one\n")


def _ask(root, *requests):
    spec = root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace(
        "code:", "decision_requests:\n" + "".join(requests) + "code:"), encoding="utf-8")


def _log(root):
    return [json.loads(line) for line in
            (root / ".sge" / "autonomy.jsonl").read_text(encoding="utf-8").splitlines()]


def _answers(*verdicts):
    """answer_fn: one scripted verdict per call; records what it was shown."""
    it, seen = iter(verdicts), []

    def answer(req, asker, spec, target):
        seen.append((req["target"], asker, target))
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v
    answer.seen = seen
    return answer


def _v(decision, confidence=0.9, reason="because"):
    return {"decision": decision, "reason": reason, "confidence": confidence, "model": "m"}


# ---- the answer, recorded ----------------------------------------------------

def test_an_answer_in_hs_place_is_an_adr_that_says_so(graph_root):
    _ask(graph_root, _ARCH_REQ, _NODE_REQ)
    nodes = parser.load_nodes(graph_root)
    inbox.decide_in_hs_place(nodes, graph_root, "util", 0, "ADR: log output goes to stderr",
                             accept=True, reason="it is the convention", by="H' (m)")
    nodes = parser.load_nodes(graph_root)
    inbox.decide_in_hs_place(nodes, graph_root, "util", 0, "provides: + a health check",
                             accept=False, reason="the task does not ask for it",
                             by="H' (m)")
    arch = (graph_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert ("log output goes to stderr (requested by util; decided by H' (m) in an "
            "unsupervised run, awaiting H's review: it is the convention)") in arch
    assert ("Rejected: provides: + a health check (requested by util for api; decided by "
            "H' (m) in an unsupervised run, awaiting H's review: the task does not ask "
            "for it)") in arch
    assert decisions.requests_of(parser.load_nodes(graph_root)["util"]) == []


def test_an_answer_without_a_reason_is_refused(graph_root):
    _ask(graph_root, _ARCH_REQ)
    with pytest.raises(ValueError, match="needs a reason"):
        inbox.decide_in_hs_place(parser.load_nodes(graph_root), graph_root, "util", 0,
                                 "ADR: log output goes to stderr", accept=True, reason=" ",
                                 by="H'")


def test_every_answer_waits_for_h_as_a_hard_change_only_h_may_accept(graph_root):
    """Nothing new keeps it H's: a change to ARCHITECTURE.md is HARD, and outside
    the delegation's scope."""
    accepted.accept_all(parser.load_nodes(graph_root), graph_root, by="setup")
    _ask(graph_root, _ARCH_REQ)
    unsupervised.answer(graph_root, _answers(_v("accept")))
    [change] = [c for c in accepted.pending(parser.load_nodes(graph_root), graph_root)
                if c["node"] == accepted.ARCHITECTURE]
    assert change["gate"] == "HARD"
    assert autonomy.delegable_scope(change) == (False, "ARCHITECTURE.md is H's")


# ---- answering every request ---------------------------------------------------

def test_h_prime_answers_every_open_request(graph_root):
    _ask(graph_root, _ARCH_REQ, _NODE_REQ)
    answer = _answers(_v("accept"), _v("reject", reason="not in the task"))
    out = unsupervised.answer(graph_root, answer)
    assert [(a["target"], a["decision"]) for a in out] == [
        ("ARCHITECTURE.md", "accepted"), ("api", "rejected")]
    assert [t for t, _, _ in answer.seen] == ["ARCHITECTURE.md", "api"]
    arch = (graph_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert answer.seen[0][2].strip() and answer.seen[0][2].strip() in arch  # the target's text
    assert "id: api" in answer.seen[1][2]
    assert iteration.open_requests(parser.load_nodes(graph_root)) == []
    logged = [e for e in _log(graph_root) if e["action"].startswith("request-")]
    assert [(e["actor"], e["action"], e["target"]) for e in logged] == [
        ("H'", "request-accepted", "ARCHITECTURE.md"), ("H'", "request-rejected", "api")]


def test_an_unsure_answer_is_not_given(graph_root):
    _ask(graph_root, _ARCH_REQ)
    [a] = unsupervised.answer(graph_root, _answers(_v("accept", confidence=0.4)))
    assert a["decision"] == "left for H" and "unsure" in a["reason"]
    assert len(iteration.open_requests(parser.load_nodes(graph_root))) == 1


def test_an_unavailable_reviewer_leaves_the_rest_for_h(graph_root):
    _ask(graph_root, _ARCH_REQ, _NODE_REQ)
    answer = _answers(RuntimeError("no key"))
    out = unsupervised.answer(graph_root, answer)
    assert [a["decision"] for a in out] == ["left for H", "left for H"]
    assert len(answer.seen) == 1                          # asked once, not per request
    assert all("no key" in a["reason"] for a in out)


@pytest.mark.parametrize("answered,claimed,expected", [
    ([("ARCHITECTURE.md", "accepted")], "DONE", []),       # recorded; nothing to do
    ([("api", "accepted")], "DONE", ["api"]),              # authorises a change to make
    ([("ARCHITECTURE.md", "rejected")], "DONE", ["ARCHITECTURE.md"]),   # the work assumed it
    ([("ARCHITECTURE.md", "accepted")], "BLOCKED", ["ARCHITECTURE.md"]),  # it waited for it
    ([("api", "left for H")], "BLOCKED", []),
])
def test_which_answers_send_the_author_back(answered, claimed, expected):
    records = [{"node": "util", "target": t, "proposal": "p", "decision": d, "reason": "r"}
               for t, d in answered]
    assert [a["target"] for a in unsupervised.rework(records, claimed)] == expected


# ---- the rounds, unsupervised -----------------------------------------------------

_GREEN = {"tests": {"passed": True, "text": "PASS  /w  (pytest): 3 passed\n"},
          "gate": {"passed": True, "text": "gate: PASS\n"}, "green": True,
          "requests": ["util -> api: provides: + a health check"]}


def _info(message="DONE", worked=3):
    return {"thread": "t-1", "message": message, "worked": worked, "failed": None}


def _answered(decision, target="api"):
    return {"node": "util", "target": target, "proposal": "provides: + a health check",
            "decision": decision, "by": "m", "reason": "not in the task"}


class _Run:
    def __init__(self, root, sessions, stood, goals):
        self.root, self.started, self.goals_checked = root, [], 0
        self._sessions, self._stood, self._goals = iter(sessions), iter(stood), iter(goals)
        self.out = io.StringIO()

    def start(self, argv, text, env, out, *, cwd):
        self.started.append(text)
        return next(self._sessions)

    def goal(self, root, task, fl, previous=()):
        self.goals_checked += 1
        return next(self._goals)

    def stand_in(self, root, task):
        return next(self._stood)

    def __call__(self, max_rounds=5, unsupervised_=True):
        return orchestrate.run(str(self.root), "the task", "first prompt", max_rounds,
                               out=self.out, start=self.start,
                               check_floor=lambda root: dict(_GREEN), check_goal=self.goal,
                               command=lambda role, **k: (["codex"], {}),
                               unsupervised=unsupervised_, stand_in_h=self.stand_in)

    def events(self, kind):
        return [e for e in map(json.loads, self.out.getvalue().splitlines())
                if e["type"] == kind]


def test_a_rejection_sends_the_author_back_before_the_goal_is_checked(graph_root):
    run = _Run(graph_root, [_info(), _info()],
               [{"answered": [_answered("rejected")], "delegated": []},
                {"answered": [], "delegated": [{"node": "util", "action": "accepted"}]}],
               [{"gaps": [], "waiting": []}])
    assert run() == "done"
    assert run.goals_checked == 1                          # not in round 1: work first
    assert "REJECTED   util -> api: provides: + a health check -- not in the task" \
        in run.started[1]
    first, second = run.events("sge.round")
    assert first["next"] == "resume" and first["decided"][0]["decision"] == "rejected"
    assert second["delegated"] == ["util"]
    [end] = run.events("sge.run")
    assert end["mode"] == "unsupervised"
    assert end["review"] == ["rejected: util -> api: provides: + a health check",
                             "accepted under the delegation: util"]
    assert {e["mode"] for e in _log_rounds(graph_root)} == {"unsupervised"}


def _log_rounds(root):
    return [e for e in _log(root) if e["action"] == "round"]


def test_blocked_on_a_question_goes_on_once_h_prime_answered_it(graph_root):
    """Unsupervised, BLOCKED on a question is not the end: the answer is what
    it waited for."""
    run = _Run(graph_root, [_info("The shape depends on it.\nBLOCKED: need api's answer"),
                            _info()],
               [{"answered": [_answered("accepted")], "delegated": []},
                {"answered": [], "delegated": []}],
               [{"gaps": [], "waiting": []}])
    assert run() == "done"
    assert "ACCEPTED   util -> api" in run.started[1]


def test_a_question_h_prime_left_open_ends_the_run_asking(graph_root):
    run = _Run(graph_root, [_info()],
               [{"answered": [_answered("left for H")], "delegated": []}],
               [{"gaps": [], "waiting": []}])
    assert run() == "asking"
    assert "util -> api: provides: + a health check" in run.events("sge.run")[0]["why"]


def test_a_supervised_run_does_not_stand_in_for_h(graph_root):
    run = _Run(graph_root, [_info()], [], [{"gaps": [], "waiting": []}])
    assert run(unsupervised_=False) == "asking"            # the request waits for H
    assert "mode" not in run.events("sge.run")[0]


# ---- starting one ----------------------------------------------------------------

def test_an_unsupervised_run_needs_the_delegation(tmp_path, monkeypatch, capsys):
    task = tmp_path / "TASK.md"
    task.write_text("# Task", encoding="utf-8")
    monkeypatch.setattr(orchestrate, "_load_env", lambda: None)
    monkeypatch.setattr(orchestrate, "run", lambda *a, **k: pytest.fail("must not start"))
    assert orchestrate.main([str(tmp_path), "go", "--task", str(task), "--unsupervised"]) == 2
    assert "needs the delegation on" in capsys.readouterr().err
    autonomy.set_delegation(tmp_path, True, by="h")
    monkeypatch.setattr(orchestrate, "run", lambda *a, **k: k["unsupervised"] and "done")
    assert orchestrate.main([str(tmp_path), "go", "--task", str(task), "--unsupervised"]) == 0


def test_the_blockers_name_the_delegation_only_for_an_unsupervised_run(tmp_path):
    says = "an unsupervised run needs it on"
    assert not [b for b in orchestrate.blockers(tmp_path) if says in b]
    assert [b for b in orchestrate.blockers(tmp_path, unsupervised=True) if says in b]
    autonomy.set_delegation(tmp_path, True, by="h")
    assert not [b for b in orchestrate.blockers(tmp_path, unsupervised=True) if says in b]


def test_the_first_prompt_says_the_run_is_unsupervised():
    assert "UNSUPERVISED" not in orchestrate.first_prompt()
    assert 'read "In an unsupervised run" in ORCHESTRATOR.md' in orchestrate.first_prompt(True)


# ---- H' itself ---------------------------------------------------------------------

def test_the_reviewer_decides_the_proposal_as_worded(monkeypatch):
    requests = []
    answer = json.dumps({"decision": "reject", "reason": "r", "confidence": 0.8})
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls"), requests=requests))
    out = reviewer.answer_request({"target": "api", "proposal": "p", "reason": "why"},
                                  "util", "id: util", "id: api", task="the task")
    assert (out["decision"], out["confidence"]) == ("reject", 0.8)
    prompt = requests[0]["messages"][0]["content"]
    assert "Decide the proposal AS WORDED" in prompt and "H reviews every answer" in prompt
    assert "proposal: p" in prompt and "TASK.md:\nthe task" in prompt


def test_an_answer_that_is_neither_accept_nor_reject_is_no_answer(monkeypatch):
    answer = json.dumps({"decision": "maybe", "reason": "r", "confidence": 0.9})
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(
        _Resp(answer, "tool_calls")))
    assert reviewer.answer_request({"target": "api", "proposal": "p"}, "u", "", "") is None


def test_the_digest_shows_what_h_prime_decided():
    from runlog import lines
    shown = lines({"type": "sge.round", "round": 1, "decided": [_answered("rejected")],
                   "delegated": ["util"], "next": "resume", "why": "w"})
    assert any(line.startswith("H' rejected   util -> api") for line in shown)
    assert "H' accepted util (delegation)" in shown
    end = lines({"type": "sge.run", "outcome": "done", "rounds": 2, "why": "w",
                 "mode": "unsupervised", "review": ["rejected: util -> api: p"]})
    assert "(unsupervised)" in end[0] and "review H  rejected: util -> api: p" in end


def test_cli_run_starts_one_with_the_same_words(tmp_path, monkeypatch):
    """`cli.py run --unsupervised` is the cockpit's Start a run, without the
    window: the same prompt, the same flag, readable lines."""
    import cli
    seen = []
    monkeypatch.setattr(orchestrate, "blockers", lambda *a, **k: [])
    monkeypatch.setattr(orchestrate, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["run", str(tmp_path), "--unsupervised", "--max-rounds", "3"]) == 0
    [argv] = seen
    assert argv[1] == orchestrate.first_prompt(True)
    assert "--unsupervised" in argv and "--readable" in argv
    assert argv[argv.index("--max-rounds") + 1] == "3"
    assert argv[argv.index("--task") + 1] == str(tmp_path / "TASK.md")


def test_cli_run_refuses_what_is_not_ready(tmp_path, monkeypatch, capsys):
    import cli
    monkeypatch.setattr(orchestrate, "main", lambda argv: pytest.fail("must not start"))
    assert cli.main(["run", str(tmp_path), "--unsupervised"]) == 2
    err = capsys.readouterr().err
    assert "not ready for a run" in err and "the delegation is off" in err

def test_the_manual_has_the_section_the_prompt_sends_the_author_to():
    from pathlib import Path
    manual = (Path(__file__).resolve().parents[2] / "spec-growth-engine"
              / "ORCHESTRATOR.template.md").read_text(encoding="utf-8")
    assert "## In an unsupervised run" in manual
    flat = " ".join(manual.split())
    for phrase in ("it never rewords it", "you are resumed with the answer",
                   "the ADR authorises exactly that change", "What stays H's even here"):
        assert phrase in flat, phrase


def test_an_unsupervised_run_end_to_end_on_disk(graph_root):
    """The real floor, the real stand-in on real files; only the sessions and
    H' are scripted. The question is answered, the author is sent back to act
    on the rejection, and the run ends with the answer waiting for H."""
    accepted.accept_all(parser.load_nodes(graph_root), graph_root, by="setup")
    autonomy.set_delegation(graph_root, True, by="h")
    _ask(graph_root, _NODE_REQ)
    sessions = iter([_info(), _info()])
    answer = _answers(_v("reject", reason="the task does not ask for one"))
    out = io.StringIO()
    outcome = orchestrate.run(
        str(graph_root), "the task", "first prompt", 5, out=out,
        start=lambda argv, text, env, o, cwd: next(sessions),
        check_goal=lambda root, task, fl, previous=(): {"gaps": [], "waiting": []},
        command=lambda role, **k: (["codex"], {}), unsupervised=True,
        stand_in_h=lambda root, task: unsupervised.stand_in(root, answer,
                                                           lambda *a: None))
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    rounds = [e for e in events if e["type"] == "sge.round"]
    assert rounds[0]["next"] == "resume" and rounds[0]["decided"][0]["decision"] == "rejected"
    assert outcome == "done" and len(rounds) == 2
    assert iteration.open_requests(parser.load_nodes(graph_root)) == []
    arch = [c for c in accepted.pending(parser.load_nodes(graph_root), graph_root)
            if c["node"] == accepted.ARCHITECTURE]
    assert arch, "the answer must wait for H as a pending change to ARCHITECTURE.md"
    assert events[-1]["review"] == ["rejected: util -> api: provides: + a health check"]


# ---- one rule, stated everywhere it is stated ------------------------------------
#
# Before the unsupervised run, "only H decides what is above a node" was true, and
# said so in seven places. Each of them must now name the exception -- a place
# that still says "only H" is a second rule, and the reader has no way to tell
# which one holds.

_REPO = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path,start,end", [
    ("spec-growth-engine/SPEC-GROWTH-ENGINE.md", "### 3.10a Decision request", "```\n\n"),
    ("spec-growth-engine/GOVERNANCE.md", "### Decision requests", "In the cockpit"),
    ("spec-growth-engine/GOVERNANCE.md", "Intent author (I), when it is an agent",
     "Reviewer (H'), in an UNSUPERVISED run"),
    ("spec-growth-engine/GOVERNANCE.md", "## 5. Operation-level authority", "## 6."),
    ("spec-growth-engine/LIFECYCLE.md", "**Whose decision this is.**", "For each slice"),
    ("spec-growth-engine/ORCHESTRATOR.template.md", "## When a decision is above you",
     "## In an unsupervised run"),
    ("spec-growth-engine/ORCHESTRATOR.template.md", "## How the graph grows", "```text"),
    ("cockpit/engine/decisions.py", '"""', "What is enforced here"),
    ("cockpit/engine/inbox.py", '"""', "A decision that targets a node"),
])
def test_every_rule_about_who_decides_above_a_node_names_the_unsupervised_run(path, start,
                                                                              end):
    text = (_REPO / path).read_text(encoding="utf-8")
    section = text[text.index(start):]
    section = section[:section.index(end, len(start))]
    assert "unsupervised" in section.lower(), f"{path}, from {start!r}"


def test_cli_run_reads_the_endpoints_before_it_judges_them(tmp_path, monkeypatch):
    """Without cockpit/.env loaded, every role looks unconfigured and a ready
    project is refused for endpoints it has."""
    import cli
    order = []
    monkeypatch.setattr(cli, "_load_env", lambda: order.append("env"))
    monkeypatch.setattr(orchestrate, "blockers",
                        lambda *a, **k: order.append("blockers") or [])
    monkeypatch.setattr(orchestrate, "main", lambda argv: 0)
    assert cli.main(["run", str(tmp_path)]) == 0
    assert order == ["env", "blockers"]
