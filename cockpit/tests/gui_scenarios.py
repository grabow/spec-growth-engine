"""GUI scenarios for the Requests window, run as SEPARATE processes.

Why a subprocess per scenario: driven in-process under pytest, the cockpit hung
in Tk's update() right after a Grant, while the identical steps ran in under a
second as a plain script. A fresh interpreter per scenario sidestepped it, gives
each scenario its own Tk, and turns a hang into a timeout failure instead of a
frozen suite. See test_requests_window.py.

The hang itself is understood now, and gone: `update()` returns only when the
event queue runs dry, and after an action on a window that is not on screen it
never does. Nothing here calls it -- `_settle` takes the pending events one at a
time, with a limit (see below). That is what let the windows be WITHDRAWN: a
suite has no business taking the screen and the focus, once per scenario, from
whoever is running it.

    python tests/gui_scenarios.py <name>     exit 0 ok, 1 failed, 77 no Tk
"""
import sys
import tempfile
import pathlib
import _tkinter
import tkinter as tk
from tkinter import ttk

TK_UNAVAILABLE = 77


def _project() -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp()) / "proj"
    root.mkdir()
    (root / "ARCHITECTURE.md").write_text("# Architecture\n\n## Decisions (ADRs)\n- TODO\n")
    (root / "SPEC.md").write_text("---\nid: svc\nparent: null\nkind: container\n"
                                  "contract: {purpose: x}\ncode: []\nstatus: specd\n---\n# svc\n")
    (root / "gui").mkdir()
    (root / "gui" / "SPEC.md").write_text(
        "---\nid: svc.gui\nparent: svc\nkind: component\ncontract: {purpose: y}\ncode: []\n"
        "waiver:\n  state: requested\n  kind: known-gap\n  reason: choose() does not raise\n"
        "status: implemented\n---\n# gui\n")
    (root / "tkwin").mkdir()
    (root / "tkwin" / "SPEC.md").write_text(
        "---\nid: svc.tkwin\nparent: svc\nkind: component\ncontract: {purpose: w}\ncode: []\n"
        "decision_requests:\n  - {target: ARCHITECTURE.md, proposal: 'ADR: use tkinter.', reason: gui}\n"
        "status: implemented\n---\n# t\n")
    return root


def _settle(widget, limit: int = 500) -> None:
    """Process what is pending, and stop. `update()` is what a Tk test reaches
    for, and it is also what hung this module before (see the docstring): it
    returns only when the queue runs dry, and with the windows withdrawn it
    never does -- eight seconds of stack dumps end inside tkinter's update().
    `dooneevent(DONT_WAIT)` takes ONE event and returns 0 when none is left, so
    a bounded loop does the same work and cannot hang."""
    widget.update_idletasks()
    taken = 0
    while taken < limit and widget.tk.dooneevent(_tkinter.DONT_WAIT):
        taken += 1


def _keep_off_the_screen() -> None:
    """Every window the cockpit opens is created WITHDRAWN.

    The scenarios drive the real widgets, which needs a real Tk -- but a mapped
    Tk window on macOS jumps to the front and takes the focus from whoever is
    running the suite, once per scenario. Withdrawn widgets still lay out,
    report their text and fire their commands, which is all a scenario reads.
    (The two modal dialogs -- NewNode, NewProject -- call grab_set, which needs
    a viewable window; no Requests scenario opens one.)"""
    created = tk.Toplevel.__init__

    def __init__(self, *a, **kw):
        created(self, *a, **kw)
        self.withdraw()

    tk.Toplevel.__init__ = __init__


def _cockpit(replies=()):
    import app
    import appconfig
    import tkinter.simpledialog as sd
    appconfig.CONFIG_PATH = pathlib.Path(tempfile.mkdtemp()) / "cockpit.json"  # never the real one
    errors = []
    app.messagebox.askyesno = lambda *a, **k: True
    app.messagebox.askyesnocancel = lambda *a, **k: True
    app.messagebox.showerror = lambda title, msg, **k: errors.append(msg)
    it = iter(replies)
    sd.askstring = lambda *a, **k: next(it)
    root = _project()
    _keep_off_the_screen()
    try:
        c = app.Cockpit(str(root))
    except tk.TclError as exc:
        print(f"Tk cannot start here: {exc}")
        sys.exit(TK_UNAVAILABLE)
    c.withdraw()          # the main window, before the first update maps it
    _settle(c)
    c.errors, c.proj = errors, root
    return c


def _window(c):
    c.show_requests()
    _settle(c)
    win = [w for w in c.winfo_children() if isinstance(w, tk.Toplevel)][-1]

    def walk(w):
        yield w
        for ch in w.winfo_children():
            yield from walk(ch)

    tree = next(w for w in walk(win) if isinstance(w, ttk.Treeview))
    buttons = {w.cget("text"): w for w in walk(win) if isinstance(w, ttk.Button)}
    return tree, buttons


def _check(ok, message):
    if not ok:
        print("FAILED:", message)
        sys.exit(1)


def badge():
    """Regression: the first reload ran before the button existed, so a freshly
    opened project showed plain 'Requests' whatever was waiting."""
    c = _cockpit()
    _check(c.requests_button.cget("text") == "Requests (2)", c.requests_button.cget("text"))


def validate():
    c = _cockpit()
    c.run_validate()
    text = c.guidance.get("1.0", "end")
    _check("2 request(s) await YOUR decision" in text, text)


def grant():
    import frontmatter
    c = _cockpit(replies=("hartwig", "2099-01-01"))
    tree, buttons = _window(c)
    tree.selection_set(tree.get_children()[0])
    _settle(c)
    buttons["Grant..."].invoke()
    _settle(c)
    w = frontmatter.load(c.proj / "gui" / "SPEC.md").metadata["waiver"]
    _check((w["state"], w["owner"], w["expires"]) == ("granted", "hartwig", "2099-01-01"), w)
    _check(c.requests_button.cget("text") == "Requests (1)", c.requests_button.cget("text"))


def invalid_grant():
    import frontmatter
    c = _cockpit(replies=("hartwig", "soon"))
    tree, buttons = _window(c)
    tree.selection_set(tree.get_children()[0])
    _settle(c)
    buttons["Grant..."].invoke()
    _settle(c)
    _check(any("not a date" in e for e in c.errors), c.errors)
    state = frontmatter.load(c.proj / "gui" / "SPEC.md").metadata["waiver"]["state"]
    _check(state == "requested", state)


def stale():
    """A list gone stale on disk must not decide a request H never looked at."""
    c = _cockpit()
    tree, buttons = _window(c)
    tree.selection_set(tree.get_children()[1])
    _settle(c)
    spec = c.proj / "tkwin" / "SPEC.md"
    spec.write_text(spec.read_text().replace("use tkinter", "use Qt"))
    buttons["Accept (record ADR)"].invoke()
    _settle(c)
    _check(any("changed on disk" in e for e in c.errors), c.errors)
    _check("tkinter" not in (c.proj / "ARCHITECTURE.md").read_text(), "ADR written from a stale list")


def _pending_hard(c):
    """Track the project, then change the root's contract the way an agent would
    (on disk, no Save): a pending HARD change on `svc`, third in the list."""
    from engine import accepted, parser
    accepted.accept_all(parser.load_nodes(c.proj), c.proj, by="setup")
    spec = c.proj / "SPEC.md"
    spec.write_text(spec.read_text().replace("purpose: x", "purpose: z"))
    c.reload_nodes()
    _settle(c)


def _select_hard(c, tree):
    [row] = [i for i in tree.get_children() if tree.item(i, "values")[0] == "HARD"]
    tree.selection_set(row)
    _settle(c)


def hard_accept():
    """Prepare (H' stubbed) -> the brief is shown -> Accept change: accepted, and
    the log records the brief H had in front of it."""
    import json
    import app
    from engine import accepted, parser
    c = _cockpit()
    _pending_hard(c)
    _check(c.requests_button.cget("text") == "Requests (3)", c.requests_button.cget("text"))
    app.reviewer.brief_hard_change = lambda report, old, cur, **k: {
        "recommendation": "accept", "confidence": 0.9, "summary": "purpose reworded",
        "risks": [], "alternatives": [], "model": "stub"}
    tree, buttons = _window(c)
    _select_hard(c, tree)
    buttons["Prepare (H')"].invoke()
    _settle(c)
    _select_hard(c, tree)
    win = [w for w in c.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    shown = [w.get("1.0", "end") for w in _walk(win) if isinstance(w, tk.Text)]
    _check(any("H' recommends: ACCEPT" in t for t in shown), shown)
    buttons["Accept change"].invoke()
    _settle(c)
    _check(not c.errors, c.errors)
    _check(accepted.pending(parser.load_nodes(c.proj), c.proj) == [], "still pending")
    last = json.loads((c.proj / ".sge" / "autonomy.jsonl").read_text().splitlines()[-1])
    _check((last["action"], last["brief"]["recommendation"]) == ("accepted", "accept"), last)
    _check(c.requests_button.cget("text") == "Requests (2)", c.requests_button.cget("text"))


def hard_reject():
    """Reject with a reason: the change leaves H's inbox, and the gate blocks on it."""
    from engine import parser, validate
    c = _cockpit(replies=("keep the purpose",))
    _pending_hard(c)
    tree, buttons = _window(c)
    _select_hard(c, tree)
    buttons["Reject..."].invoke()
    _settle(c)
    _check(not c.errors, c.errors)
    report = validate.run(parser.load_nodes(c.proj), str(c.proj))
    _check("HARD CHANGE REJECTED on svc" in report and "keep the purpose" in report, report)
    _check(c.requests_button.cget("text") == "Requests (2)", c.requests_button.cget("text"))



class _FakeRun:
    """A run without a run: the stream orchestrate.py would write, from a list.
    What the window does with it is the cockpit's code, unchanged."""

    def __init__(self, lines):
        self.stdout = iter(line + "\n" for line in lines)
        self.pid, self.returncode = 4242, 0

    def poll(self):
        return None

    def wait(self):
        return 0


def run_window():
    """A run, watched: the window renders the stream, the cockpit re-reads the
    graph after every round, Draft is locked while an agent writes the same
    files, and the end names the outcome -- `asking` opens the Requests window,
    because that is where the question is."""
    import json
    import time
    import types
    import app
    c = _cockpit()

    class _Inline:
        """The stream reader, in the main thread. Tk's after() refuses to queue
        from another thread while no mainloop is running -- the scenarios drive
        the widgets by hand, so the thread is the one thing they cannot keep."""

        def __init__(self, target=None, args=(), daemon=None):
            self._call, self._args = target, args

        def start(self):
            self._call(*self._args)

    app.threading = types.SimpleNamespace(Thread=_Inline)
    events = [
        {"type": "thread.started", "thread_id": "t-1"},
        {"type": "item.started", "item": {"type": "command_execution", "command": "cli.py gate"}},
        {"type": "sge.round", "round": 1, "claim": None, "floor": "red", "gaps": [],
         "failures": ["gate: HARD change on svc"], "next": "resume", "outcome": "",
         "why": "the floor is red"},
        {"type": "sge.round", "round": 2, "claim": "DONE", "floor": "green", "gaps": [],
         "requests": ["svc.tkwin -> ARCHITECTURE.md: use tkinter."], "next": "stop",
         "outcome": "asking", "why": "1 decision request awaits H"},
        {"type": "sge.run", "outcome": "asking", "rounds": 2,
         "why": "1 decision request awaits H"},
    ]
    c._open_run_window(_FakeRun([json.dumps(e) for e in events]), str(c.proj / "TASK.md"), 5)
    _check(str(c.draft_button.cget("state")) == "disabled", "Draft was not locked")
    for _ in range(400):          # the stream is read in a thread; give it turns
        if c._run is None:
            break
        _settle(c)
        time.sleep(0.01)
    _check(c._run is None, "the run never ended")

    windows = [w for w in c.winfo_children() if isinstance(w, tk.Toplevel)]
    run_win = next(w for w in windows if w.title().startswith("Run - "))
    shown = "\n".join(w.get("1.0", "end") for w in _walk(run_win) if isinstance(w, tk.Text))
    _check("ROUND 1" in shown and "floor=red" in shown, shown)
    _check("missing   gate: HARD change on svc" in shown, shown)
    _check("asks H    svc.tkwin -> ARCHITECTURE.md: use tkinter." in shown, shown)
    _check("RUN       ASKING after 2 round(s)" in shown, shown)
    _check("RUN ASKING" in shown, "the window never said how it ended")
    _check(str(c.draft_button.cget("state")) == "normal", "Draft stayed locked")
    _check("Run ASKING" in c.guidance.get("1.0", "end"), c.guidance.get("1.0", "end"))
    _check(any(w.title().startswith("Requests awaiting") for w in windows),
           "asking did not open the Requests window")


def run_locks_the_writers():
    """While a run writes, Draft and Revise say so instead of writing too."""
    c = _cockpit()
    c._run = {"round": 2}
    c.draft()
    _check("A run is in progress" in c.guidance.get("1.0", "end"),
           c.guidance.get("1.0", "end"))
    c.revise()
    _check("round 2" in c.guidance.get("1.0", "end"), c.guidance.get("1.0", "end"))


def run_dialog_modes():
    """The run is on or unsupervised. Unsupervised needs the delegation, so
    without it the choice is there but off; with it, choosing it swaps the
    first prompt and the dialog hands the choice on."""
    import app
    import orchestrate
    c = _cockpit()
    app.RunDialog.grab_set = lambda self: None     # modal needs a viewable window
    (c.proj / "TASK.md").write_text("# Task\n", encoding="utf-8")

    def radios(d):
        return {w.cget("text").split(" --")[0]: w for w in _walk(d)
                if isinstance(w, ttk.Radiobutton)}

    off = app.RunDialog(c, str(c.proj), [], delegated=False)
    _check(set(radios(off)) == {"on", "unsupervised"}, str(set(radios(off))))
    _check("disabled" in str(radios(off)["unsupervised"].cget("state")),
           "unsupervised was offered without the delegation")
    labels = " ".join(w.cget("text") for w in _walk(off) if isinstance(w, ttk.Label))
    _check("needs the delegation on" in labels, labels)
    off.destroy()

    d = app.RunDialog(c, str(c.proj), [], delegated=True)
    _check("disabled" not in str(radios(d)["unsupervised"].cget("state")), "still off")
    d.unsupervised.set(True)
    d._mode_changed()
    _check(d.prompt.get("1.0", "end").strip() == orchestrate.first_prompt(True),
           "the prompt did not follow the mode")
    d._ok()
    _check(d.result is not None and d.result[3] is True, str(d.result))


def run_window_unsupervised():
    """An unsupervised run that ended with things H' decided for H: the end says
    how many, and opens Requests, where they wait for review."""
    import json
    import time
    import types
    import app
    c = _cockpit()

    class _Inline:
        def __init__(self, target=None, args=(), daemon=None):
            self._call, self._args = target, args

        def start(self):
            self._call(*self._args)

    app.threading = types.SimpleNamespace(Thread=_Inline)
    events = [
        {"type": "sge.round", "round": 1, "claim": "DONE", "floor": "green", "gaps": [],
         "decided": [{"node": "svc.tkwin", "target": "ARCHITECTURE.md",
                      "proposal": "ADR: use tkinter.", "decision": "accepted"}],
         "next": "stop", "outcome": "done", "why": "no gap"},
        {"type": "sge.run", "outcome": "done", "rounds": 1, "why": "no gap",
         "mode": "unsupervised", "review": ["accepted: svc.tkwin -> ARCHITECTURE.md: "
                                            "ADR: use tkinter."]},
    ]
    c._open_run_window(_FakeRun([json.dumps(e) for e in events]), str(c.proj / "TASK.md"),
                       5, unsupervised=True)
    for _ in range(400):
        if c._run is None:
            break
        _settle(c)
        time.sleep(0.01)
    _check(c._run is None, "the run never ended")
    windows = [w for w in c.winfo_children() if isinstance(w, tk.Toplevel)]
    run_win = next(w for w in windows if w.title().startswith("Run - "))
    shown = "\n".join(w.get("1.0", "end") for w in _walk(run_win) if isinstance(w, tk.Text))
    _check("RUN (UNSUPERVISED)" in shown, shown)
    _check("H' accepted   svc.tkwin -> ARCHITECTURE.md" in shown, shown)
    _check("review H  accepted: svc.tkwin" in shown, shown)
    said = c.guidance.get("1.0", "end")
    _check("H' decided 1 thing(s) in your place" in said, said)
    _check(any(w.title().startswith("Requests awaiting") for w in windows),
           "the review did not open the Requests window")


def new_project_scrolls():
    """The New Project form is taller than a laptop screen once the goal fields
    are open: it scrolls, its buttons stay outside the scrolled part, and
    opening the goal scrolls the new fields into view."""
    import app
    c = _cockpit()
    app.GroundworkDialog.grab_set = lambda self: None     # modal needs a viewable window
    d = app.GroundworkDialog(c, str(c.proj))
    _settle(d)
    canvas = d._canvas
    _check(int(canvas.cget("height")) <= d.winfo_screenheight() - 200,
           "the form is taller than the screen allows")
    buttons = [w for w in _walk(d) if isinstance(w, ttk.Button)
               and w.cget("text") in ("Lay the floor", "Cancel")]
    _check(len(buttons) == 2, "the buttons are gone")
    _check(not any(str(b).startswith(str(canvas)) for b in buttons),
           "the buttons scroll away with the form")
    d.wants_run.set(True)
    d._toggle_goal()
    _settle(d)
    _check(d.goal_frame.winfo_manager() == "grid", "the goal fields did not open")
    top, bottom = canvas.yview()
    _check(bottom == 1.0, f"the goal fields are not scrolled into view: {canvas.yview()}")
    d.wants_run.set(False)
    d._toggle_goal()
    _check(d.goal_frame.winfo_manager() == "", "the goal fields did not close")
    d._cancel()


def _walk(w):
    yield w
    for ch in w.winfo_children():
        yield from _walk(ch)


SCENARIOS = {f.__name__: f for f in (badge, validate, grant, invalid_grant, stale,
                                     hard_accept, hard_reject,
                                     run_window, run_locks_the_writers,
                                     run_dialog_modes, run_window_unsupervised,
                                     new_project_scrolls)}

if __name__ == "__main__":
    SCENARIOS[sys.argv[1]]()
    print("ok")
