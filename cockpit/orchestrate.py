"""Run the intent author I in ROUNDS until the goal is met (AUTONOMY.md: the run).

  uv run python orchestrate.py ROOT --task TASK.md [--max-rounds N] [--unsupervised]
                               [--readable] PROMPT

Usually started by the cockpit (Start a run...) or `cli.py run ROOT`, which
both land here. The project can be anywhere: everything a run records goes into
the project itself.

The run switch is off | on | unsupervised. This is `on` -- H answers what is
above a node, between runs -- and, with --unsupervised, the setting in which H'
answers it between ROUNDS, in H's place, and H reviews every answer afterwards
(engine/unsupervised.py). An unsupervised run needs the delegation on.

One `codex exec` session of I is one round. After it, E checks the floor (it
records the tests and runs the gate) and, on a green floor, H' checks the goal
(TASK.md against the specs and the tests). engine/iteration.py decides whether
I resumes the SAME session -- `codex exec resume`, with its memory of the run --
told what is missing, or the run stops, and why.

stdout is the run's event stream: codex's own events, `sge.coder` for what C is
doing while I waits on it (CoderWatch), one `sge.round` event after every round,
one `sge.run` event at the end, and one `sge.after` for what E and H' did once
it was over (runlog.py renders them) -- or, with --readable, those lines already
rendered. Every run is recorded in <ROOT>/.sge/runs/:

  NN.jsonl   the event stream, as it came
  NN.log     one readable line per event (runlog.py) -- follow it with tail -f
  NN.roles   who played which role (model, endpoint -- never a key), the mode,
             the round limit and the engine's commit

Every round is also in the audit log (<ROOT>/.sge/autonomy.jsonl).

After the run -- whatever its outcome -- E records the tests of the final state,
H' decides what the delegation lets it (when it is on) and briefs every pending
HARD change that has no fresh brief, so H finds the homework done
(`after`). Without a key the run is still complete, only undecided and
unprepared.
The exit code is 0 for a run that ends done, 1 for any other end (`asking`
included: the work stands, but a decision request waits for H), 2 when I cannot
start. MAX_ROUNDS=1 is one session and no second: a run without rounds.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import runlog  # noqa: E402
from engine import autonomy, iteration, lifecycle, parser, unsupervised as unsup  # noqa: E402


def session(argv: list[str], prompt: str, env: dict, out, *, cwd: str) -> dict:
    """Run one codex session in `cwd` -- the project, whoever started the run (the
    cockpit's window or `cli.py run`, in the cockpit's directory); pass its events
    through to `out`; return what the rule needs: the session id, I's last
    message, whether it did any work, and why it failed, if it did."""
    proc = subprocess.Popen(argv + [prompt], cwd=cwd,
                            stdin=subprocess.DEVNULL,   # see codex_cli
                            stdout=subprocess.PIPE, text=True, env=env)
    info = {"thread": None, "message": "", "worked": 0, "failed": None}
    last_error = ""
    for line in proc.stdout:  # type: ignore[union-attr]
        out.write(line)
        out.flush()
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind, item = ev.get("type"), ev.get("item") or {}
        if kind == "thread.started":
            info["thread"] = ev.get("thread_id")
        elif kind == "item.completed" and item.get("type") == "agent_message":
            info["message"] = item.get("text", "")
        elif kind == "item.completed" and item.get("type") in ("command_execution",
                                                                  "file_change"):
            info["worked"] += 1
        elif kind == "turn.failed":
            info["failed"] = (ev.get("error") or {}).get("message") or "the turn failed"
        elif kind == "error":
            # also sent for a retry the session survives: remembered, not fatal
            last_error = ev.get("message", "")
    code = proc.wait()
    if code and not info["failed"]:
        info["failed"] = f"codex exited with {code}" + (f": {last_error}" if last_error else "")
    if not info["thread"] and not info["failed"]:
        info["failed"] = "no session was started"
    return info


def floor(root: str) -> dict:
    """E's floor: record the tests (`cli.py test`), run the gate, and read the
    questions the graph is waiting on -- a green floor over an open decision
    request is not a finished run (engine/iteration.open_requests)."""
    import cli
    tests, gate = io.StringIO(), io.StringIO()
    with redirect_stdout(tests), redirect_stderr(tests):
        t = cli.cmd_test(root)
    with redirect_stdout(gate), redirect_stderr(gate):
        g = cli.cmd_gate(root)
    return {"tests": {"passed": t == 0, "text": tests.getvalue()},
            "gate": {"passed": g == 0, "text": gate.getvalue()},
            "requests": iteration.open_requests(parser.load_nodes(root)),
            "green": t == 0 and g == 0}


def goal(root: str, task: str, fl: dict, previous: list[str] = ()) -> dict:
    """H' checks the goal against the facts E computed. {"gaps", "closed",
    "summary", "model"}, or {"unavailable": why} -- never an exception: an
    unreachable reviewer is a fact the rule knows how to handle. `previous` are
    the gaps of the last round, which it must answer for before it looks for new
    ones (agent/reviewer.check_goal)."""
    import testrun
    from agent import reviewer
    nodes = parser.load_nodes(root)
    facts = iteration.facts(nodes, root, fl, testrun.build_roots(nodes, root))
    try:
        result = reviewer.check_goal(task, facts, previous)
    except RuntimeError as exc:
        return {"unavailable": str(exc)}
    if result is None:
        return {"unavailable": "H' gave no usable answer"}
    lifecycle.log_autonomy(root, {"actor": "H'", "by": result["model"],
                                  "action": "goal-checked", "gaps": len(result["gaps"]),
                                  "waiting": len(result.get("waiting") or []),
                                  "closed": len(result.get("closed") or [])})
    return result


CHECK_STEPS = ("E runs the tests -- the whole build -- and the gate",
               "H' reads TASK.md against the result")


def check(root: str, task: str, *, check_floor=floor, check_goal=goal,
          progress=None) -> dict:
    """The goal check WITHOUT an agent: what a run's last round says about the
    project as it stands -- E measures, and on a green floor H' checks it against
    TASK.md -- with no intent author to spend a session or touch a file. Nothing
    is written but what the tests and the gate always record (the evidence, the
    SOFT changes E clears) and the audit log.

    {"verdict": red | gaps | asking | done | unchecked, "why", "failures", "gaps",
     "waiting", "closed", "summary", "requests", "model"}. `requests` is every
    thing waiting for H -- a pending HARD change and a waiver too, not only the
    decision requests a run stops on: `done` is to mean nothing waits for you.
    `progress(step)` hears each of CHECK_STEPS as it starts: the check takes
    a while -- H' is a model call -- and must not look like it hung."""
    from engine import inbox
    say = progress or (lambda _step: None)
    say(CHECK_STEPS[0])
    fl = check_floor(root)
    waits = [f"{it['type']:8} {it['node']} -> {it['subject']}"
             for it in inbox.pending(parser.load_nodes(root), root)]
    out = {"failures": [], "gaps": [], "waiting": [], "closed": [], "summary": "",
           "requests": waits, "model": "", "where": []}
    if not fl["green"]:
        return {**out, "verdict": "red", "failures": iteration.failures(fl),
                "why": "the tests or the gate fail -- H' is not asked about a red floor"}
    say(CHECK_STEPS[1])
    gl = check_goal(root, task, fl)
    if "unavailable" in gl:
        return {**out, "verdict": "unchecked",
                "why": f"the floor is green, but H' could not check the goal: "
                       f"{gl['unavailable']}"}
    out.update(gaps=gl.get("gaps") or [], waiting=gl.get("waiting") or [],
               closed=gl.get("closed") or [], summary=gl.get("summary") or "",
               model=gl.get("model") or "",
               where=_located(root, gl.get("where") or []))
    if out["gaps"]:
        return {**out, "verdict": "gaps",
                "why": f"the floor is green, but H' names {len(out['gaps'])} gap(s) "
                       "against TASK.md"}
    if waits or out["waiting"]:
        return {**out, "verdict": "asking",
                "why": "nothing is missing, but something waits for you"}
    return {**out, "verdict": "done",
            "why": "the tests and the gate pass, H' finds no gap, nothing waits for you"}


def _located(root: str, where: list[dict]) -> list[dict]:
    """H''s places for the gaps, each looked up (engine/search.locate): the file it
    names and the line the quoted words start on -- None when they are not there
    verbatim. A place naming no file is dropped."""
    from engine import search
    nodes = parser.load_nodes(root)
    out = []
    for w in where:
        at = search.locate(root, nodes, w["in"], w["quote"])
        if at is not None:
            out.append({**w, "file": at["file"], "line": at["line"]})
    return out


def location_line(loc: dict) -> str:
    """One place a gap sits, as check_text writes it -- and the cockpit finds it again."""
    at = f"line {loc['line']}" if loc.get("line") else "(not found verbatim)"
    return f"  in      {loc['in']}  {at}  \"{loc['quote']}\""


def check_text(result: dict) -> str:
    """The check, one line per finding -- for the cockpit and `cli.py check`."""
    lines = [f"CHECK     {result['verdict'].upper()} -- {result['why']}"]
    lines += [f"failing   {x}" for x in result["failures"]]
    for n, gap in enumerate(result["gaps"], 1):
        lines.append(f"gap       {gap}")
        lines += [location_line(w) for w in result.get("where") or [] if w["gap"] == n]
    lines += [f"waits H   {x}" for x in result["waiting"]]
    lines += [f"asks H    {x}" for x in result["requests"]]
    lines += [f"closed    {x}" for x in result["closed"]]
    if result["summary"]:
        lines.append(f"H' says   {result['summary']}")
    if result["model"]:
        lines.append(f"checked   by H' ({result['model']}) against TASK.md")
    return "\n".join(lines)


UNSUPERVISED_NOTE = ("This run is UNSUPERVISED: nobody but H' answers your decision "
                     "requests, between rounds -- read \"In an unsupervised run\" in "
                     "ORCHESTRATOR.md.")


def first_prompt(unsupervised: bool = False) -> str:
    """The prompt a run starts with: read the manual, the goal is in TASK.md, and
    end with DONE or BLOCKED. It says nothing about the work itself -- that is
    TASK.md's job, and a prompt that repeats it is a second goal nobody checks.
    The cockpit and `cli.py run` both start with it."""
    method = HERE.parent / "spec-growth-engine"
    return ("Read ORCHESTRATOR.md in this directory and follow it exactly. Your task is "
            f"described in TASK.md. The method documents are in {method}; the engine is "
            "reached through the command the manual names, and is not yours to read. Work "
            "until the task is done, or until you are blocked in a way you cannot resolve "
            "honestly -- in that case stop and explain what blocked you. End your last "
            "message with a line of its own: DONE, or BLOCKED: <reason>."
            + (" " + UNSUPERVISED_NOTE if unsupervised else ""))


def blockers(root: str | Path, task: str | Path | None = None,
             unsupervised: bool = False) -> list[str]:
    """What is missing before a run can start -- the "needs" column of the
    README's table, checked instead of assumed. A run that starts without its
    goal, its manuals or an endpoint fails slowly and in a way that reads like
    the agent's fault. Empty list = ready. An unsupervised run also needs the
    delegation on: without it every HARD change piles up for H, and the run
    stands in for H everywhere except where it matters most."""
    from agent import llm
    root = Path(root)
    out = []
    if not (root / "SPEC.md").is_file():
        out.append(f"no spec root: {root}/SPEC.md is missing (New Project..., or cli.py init)")
    goal = Path(task) if task else root / "TASK.md"
    if not goal.is_file():
        out.append(f"no goal: {goal} is missing -- it is what H' checks the run against")
    for name, who in (("ORCHESTRATOR.md", "the intent author"),
                      ("AGENTS.md", "the method")):
        if not (root / name).is_file():
            out.append(f"no manual for {who}: {root}/{name} is missing "
                       f"(groundwork renders both)")
    for role in llm.ROLES:
        lacking = llm.missing(role)
        if lacking:
            out.append(f"no endpoint for the {role}: fix {', '.join(lacking)} "
                       "in cockpit/.env")
    harnesses = {llm.endpoint(role)["harness"] for role in llm.AGENT_ROLES} & set(llm.HARNESSES)
    for harness in sorted(harnesses):
        command = llm.HARNESSES[harness]
        if shutil.which(command) is None:
            out.append(f"`{command}` is not on PATH -- I and C run on the harness "
                       f"{harness} (install the Codex CLI: https://github.com/openai/codex)")
    if unsupervised and not autonomy.delegated(root):
        out.append("the delegation is off: an unsupervised run needs it on "
                   "(`cli.py delegate ROOT on`, or the switch beside the slider)")
    return out


def stand_in(root: str, task: str) -> dict:
    """H' in H's place, between two rounds of an unsupervised run: it answers the
    open decision requests and decides the pending HARD changes inside the
    delegation (engine/unsupervised.stand_in)."""
    from agent import reviewer
    arch = parser.load_architecture(root)
    return unsup.stand_in(
        root,
        lambda req, asker, spec, target: reviewer.answer_request(
            req, asker, spec, target, task=task, architecture=arch),
        lambda report, old, cur: reviewer.brief_hard_change(report, old, cur,
                                                            architecture=arch))


def _review_lines(stood: dict) -> list[str]:
    """What H' decided in H's place this round, for H to review: one line each."""
    out = [f"{a['decision']}: {a['node']} -> {a['target']}: {a['proposal']}"
           for a in stood["answered"] if a["decision"] in (unsup.ACCEPTED, unsup.REJECTED)]
    out += [f"accepted under the delegation: {d['node']}" for d in stood["delegated"]
            if d.get("action") == "accepted"]
    return out


AUDIT = Path(".sge") / "autonomy.jsonl"


def _audit_size(root: str) -> int:
    path = Path(root) / AUDIT
    return path.stat().st_size if path.exists() else 0


def _decided_inside(root: str, offset: int) -> list[str]:
    """What H' decided in H's place WHILE the session ran, read from the audit log
    from `offset` on: the intent author can ask for that itself (`cli.py decide`,
    under the delegation). The unsupervised guess run did, and its closing line
    listed nothing for H to review -- only what the stand-in decides BETWEEN rounds
    reached it (_review_lines)."""
    path = Path(root) / AUDIT
    if not path.exists():
        return []
    with path.open("rb") as fh:
        fh.seek(offset)
        raw = fh.read().decode("utf-8", "replace")
    out = []
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("actor") != "H'":
            continue
        action = str(entry.get("action", ""))
        if action.startswith("request-"):
            out.append(f"{action[len('request-'):]}: {entry.get('node')} -> "
                       f"{entry.get('target')}: {entry.get('proposal')}")
        elif action == "accepted":
            out.append(f"accepted under the delegation: {entry.get('node')}"
                       if entry.get("gate") == "HARD"
                       else f"accepted by H' ({entry.get('gate')}): {entry.get('node')}")
    return out


def _emit(out, event: dict) -> None:
    out.write(json.dumps(event, ensure_ascii=False) + "\n")
    out.flush()


class _Serialized:
    """One writer for two threads -- the session's events and CoderWatch's --
    so that no line of one lands inside a line of the other."""

    def __init__(self, out):
        self._out, self._lock = out, threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            self._out.write(text)

    def flush(self) -> None:
        with self._lock:
            self._out.flush()


class CoderWatch:
    """What C is doing, while I waits on it.

    I starts C with `cli.py code`, which can take minutes; C writes to its own
    log (<root>/.sge/code/<node>-<time>.log), and I's stream says nothing until C
    is done -- a working run looked like a stalled one. So while a session runs,
    this watches those logs: every `interval` seconds, for each log written to
    since the session began, the last new line is emitted as `sge.coder`. The
    watching happens here, once; every reader of the stream -- the cockpit's Run
    window, `cli.py run`, the run's own log -- gets it without polling itself.
    Throttled on purpose: one line per log per interval; C's full output stays in
    its log."""

    def __init__(self, root: str | Path, out, interval: float = 2.0):
        self.root, self.out, self.interval = Path(root), out, interval
        self._dir = self.root / ".sge" / "code"
        self._since = time.time()
        self._offsets: dict[Path, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Stop watching -- after one last look, so C's final line is not lost."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self.interval + 5)
        self.poll()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.poll()

    def poll(self) -> None:
        try:
            logs = sorted((p for p in self._dir.glob("*.log")
                           if p.stat().st_mtime >= self._since - 1),
                          key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        for path in logs:
            start = self._offsets.get(path, 0)
            try:
                with open(path, "rb") as f:
                    f.seek(start)
                    new = f.read()
            except OSError:
                continue
            if not new:
                continue
            self._offsets[path] = start + len(new)
            lines = [ln.strip() for ln in new.decode("utf-8", "replace").splitlines()
                     if ln.strip()]
            if lines:
                _emit(self.out, {"type": "sge.coder", "node": path.stem.rsplit("-", 1)[0],
                                 "line": lines[-1],
                                 "log": str(path.relative_to(self.root))})


def run(root: str, task: str, prompt: str, max_rounds: int = iteration.MAX_ROUNDS, *,
        out=None, start=session, check_floor=floor, check_goal=goal,
        command=None, unsupervised: bool = False, stand_in_h=stand_in,
        watch=CoderWatch, progress: dict | None = None) -> str:
    """The rounds. Returns how the run ended: done | asking | blocked | stalled |
    error | unchecked | limit (engine/iteration.py). Unsupervised, H' stands in
    for H after every measured round (stand_in_h), before the goal is checked."""
    out = _Serialized(out or sys.stdout)
    mode = "unsupervised" if unsupervised else "on"
    review: list[str] = []         # what H' decided in H's place, over the whole run --
    #                                between rounds, and inside them at I's request
    if command is None:
        from agent import codex_cli
        command = codex_cli.command
    argv, env = command("intent", json_events=True)
    text, thread, round_no = prompt, None, 1
    named: list[str] = []          # the gaps H' named last round, for its memory
    while True:
        if progress is not None:
            progress["round"] = round_no      # which round a crash happened in
        watching = watch(root, out) if watch else None
        if watching:
            watching.start()
        audited = _audit_size(root)
        try:
            info = start(argv, text, env, out, cwd=str(root))
        finally:
            if watching:
                watching.stop()
        review += _decided_inside(root, audited)
        thread = info["thread"] or thread
        claimed, why = iteration.claim(info["message"])
        fl = gl = None
        stood: dict = {"answered": [], "delegated": []}
        rework: list[dict] = []
        step = iteration.stop_early(round_no, failed=info["failed"],
                                    worked=info["worked"] > 0)
        if step is None:
            # BLOCKED too: E measures, and on a green floor H' checks the goal.
            # Run 12 said BLOCKED over 561 green tests and six questions for H --
            # it was waiting, not blocked, and the record should say so.
            fl = check_floor(root)
            requests = fl.get("requests") or []
            if unsupervised:
                stood = stand_in_h(root, task)
                review += _review_lines(stood)
                # every request was put to H'; what is still open is what it left
                requests = [f"{a['node']} -> {a['target']}: {a['proposal']}"
                            for a in stood["answered"] if a["decision"] == unsup.LEFT]
                rework = unsup.rework(stood["answered"], claimed)
            gl = check_goal(root, task, fl, named) if fl["green"] and not rework else None
            step = iteration.decide(round_no, max_rounds, claimed=claimed,
                                    floor_green=fl["green"], goal=gl,
                                    requests=requests, why=why, rework=rework)
        gaps = (gl or {}).get("gaps") or []
        named = gaps if gl and "unavailable" not in gl else named
        _emit(out, {"type": "sge.round", "round": round_no, "claim": claimed,
                    "claim_why": why, "worked": info["worked"],
                    "floor": None if fl is None else ("green" if fl["green"] else "red"),
                    "failures": iteration.failures(fl) if fl else [],
                    "gaps": gaps, "waiting": (gl or {}).get("waiting") or [],
                    "closed": (gl or {}).get("closed") or [],
                    "goal_unavailable": (gl or {}).get("unavailable"),
                    "requests": (fl or {}).get("requests") or [],
                    "decided": stood["answered"],
                    "delegated": [d["node"] for d in stood["delegated"]
                                  if d.get("action") == "accepted"],
                    "next": step["next"], "outcome": step["outcome"], "why": step["why"]})
        lifecycle.log_autonomy(root, {"actor": "E", "action": "round", "mode": mode,
                                      "round": round_no,
                                      "claim": claimed, "floor": None if fl is None
                                      else fl["green"], "gaps": len(gaps),
                                      "next": step["next"], "outcome": step["outcome"]})
        if step["next"] == "stop":
            _emit(out, {"type": "sge.run", "outcome": step["outcome"], "rounds": round_no,
                        "why": step["why"], "thread": thread,
                        **({"mode": mode} if unsupervised else {}),
                        **({"review": review} if unsupervised or review else {})})
            return step["outcome"]
        round_no += 1
        text = iteration.resume_prompt(round_no, max_rounds, fl, gl, stood["answered"])
        argv, env = command("intent", json_events=True, resume=thread)


# ---- the record of a run, in the project ----------------------------------------

RUNS = Path(".sge") / "runs"


def next_run(root: str | Path) -> Path:
    """<root>/.sge/runs/NN -- the stem of the next run's record (NN from 01)."""
    runs = Path(root) / RUNS
    runs.mkdir(parents=True, exist_ok=True)
    taken = [int(p.stem) for p in runs.glob("*.jsonl") if p.stem.isdigit()]
    return runs / f"{max(taken, default=0) + 1:02d}"


def roles_text(mode: str, max_rounds: int, task: str) -> str:
    """Who played which role -- model and endpoint, never a key -- and how the run
    was set up. Next to the stream, because a record without it cannot be
    compared with the next one."""
    from agent import codex_cli, llm
    try:
        commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    lines = [f"mode={mode}  max_rounds={max_rounds}  task={task}  "
             f"engine={commit or 'unknown'}"]
    for role in llm.ROLES:
        runner = ((llm.endpoint(role)["harness"] or "(no harness)")
                  if role in codex_cli.AGENT_ROLES else "chat call")
        lines.append(f"{role:9} {runner:10} {llm.describe(role)}   "
                     f"key: {llm.endpoint(role)['key_from'] or '(none)'}")
    return "\n".join(lines) + "\n"


class Record:
    """The stream a run writes, three ways at once: to `out` (raw events, or with
    `readable` the rendered lines), and into the project's record -- NN.jsonl as
    it came, NN.log rendered. One writer, so the log and the window can never say
    different things."""

    def __init__(self, stem: Path, out, readable: bool = False):
        self._out, self._readable, self._buf = out, readable, ""
        self._jsonl = open(stem.with_suffix(".jsonl"), "a", encoding="utf-8")
        self._log = open(stem.with_suffix(".log"), "a", encoding="utf-8")

    def write(self, text: str) -> None:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._line(line)

    def _line(self, line: str) -> None:
        self._jsonl.write(line + "\n")
        try:
            shown = runlog.lines(json.loads(line))
        except ValueError:
            shown = [line]            # not an event: kept as it is
        shown = shown if shown is not None else [line]
        for text in shown:
            self._log.write(text + "\n")
        if self._readable:
            for text in shown:
                self._out.write(text + "\n")
        else:
            self._out.write(line + "\n")

    def flush(self) -> None:
        for f in (self._jsonl, self._log, self._out):
            f.flush()

    def close(self) -> None:
        if self._buf:
            self._line(self._buf)
            self._buf = ""
        self.flush()
        self._jsonl.close()
        self._log.close()


def after(root: str) -> list[str]:
    """What E and H' do once a run is over, whatever its outcome: record the tests
    of the final state (what "migrated" is checked against), let H' decide what
    the delegation lets it, and have H' brief every pending HARD change without a
    fresh brief. One line per step; never an exception -- an unreachable H' only
    leaves the homework undone."""
    import cli
    out = []
    for name, step in (("test", cli.cmd_test), ("decide", cli.cmd_decide),
                       ("prepare", cli.cmd_prepare)):
        if name == "decide" and not autonomy.delegated(root):
            out.append("decide    the delegation is off: pending HARD changes are H's")
            continue
        said = io.StringIO()
        try:
            with redirect_stdout(said), redirect_stderr(said):
                step(root)
        except Exception as exc:  # noqa: BLE001 -- the run is over; say it, do not die
            said.write(f"failed: {exc}")
        lines = [ln.strip() for ln in said.getvalue().splitlines() if ln.strip()]
        out += [f"{name:9} {ln}" for ln in lines[-6:]] or [f"{name:9} (nothing to say)"]
    return out


def _ended_by(record, exc: Exception, round_no: int) -> int:
    """A run that ends in an exception still ENDS: one `sge.run` event, outcome
    `error`, with the reason and where it was raised -- into the window, and into
    .sge/runs/NN.log, which the traceback on stderr never reached (a run that
    crashed in round 1 read there like one that simply stopped). A RuntimeError
    or OSError is a role that cannot be reached or started, said by its message:
    exit 2. Anything else is a crash, with its traceback: exit 1."""
    where = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
    at = f" ({Path(where.filename).name}:{where.lineno}, {where.name})" if where else ""
    expected = isinstance(exc, RuntimeError | OSError)
    when = f"in round {round_no}" if round_no else "before its first round"
    why = f"the run {'stopped' if expected else 'crashed'} {when}: {type(exc).__name__}: {exc}{at}"
    tb = "" if expected else "".join(traceback.format_exception(exc)).rstrip()
    _emit(record, {"type": "sge.run", "outcome": "error", "rounds": max(round_no - 1, 0),
                   "why": why, **({"traceback": tb} if tb else {})})
    record.close()
    return 2 if expected else 1


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE / ".env")   # a value already in the environment wins
    except ImportError:  # pragma: no cover
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orchestrate", description=__doc__.split("\n")[0])
    p.add_argument("root", help="the spec root the run grows")
    p.add_argument("prompt", help="the first round's prompt")
    p.add_argument("--task", required=True, help="TASK.md: the goal H' checks against")
    p.add_argument("--max-rounds", type=int, default=iteration.MAX_ROUNDS)
    p.add_argument("--unsupervised", action="store_true",
                   help="H' answers decision requests between rounds, in H's place "
                        "(needs the delegation on)")
    p.add_argument("--readable", action="store_true",
                   help="print the rendered lines instead of the raw events (a terminal)")
    args = p.parse_args(argv)
    if args.max_rounds < 1:
        p.error("--max-rounds must be at least 1")
    _load_env()
    task = Path(args.task).read_text(encoding="utf-8")
    root = os.path.abspath(args.root)
    if args.unsupervised and not autonomy.delegated(root):
        print("an unsupervised run needs the delegation on: `cli.py delegate ROOT on` "
              "(H's act)", file=sys.stderr)
        return 2
    mode = "unsupervised" if args.unsupervised else "on"
    stem = next_run(root)
    stem.with_suffix(".roles").write_text(roles_text(mode, args.max_rounds, args.task),
                                          encoding="utf-8")
    record = Record(stem, sys.stdout, readable=args.readable)
    progress = {"round": 0}
    try:
        outcome = run(root, task, args.prompt, args.max_rounds, out=record,
                      unsupervised=args.unsupervised, progress=progress)
    except Exception as exc:  # noqa: BLE001 -- how the run ended belongs in its record
        return _ended_by(record, exc, progress["round"])
    _emit(record, {"type": "sge.after", "lines": after(root)})
    record.close()
    return 0 if outcome == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
