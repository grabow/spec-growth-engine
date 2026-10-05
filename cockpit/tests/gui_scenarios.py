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
    _check(str(c.save_button.cget("state")) == "disabled", "Save was not locked")
    _check(c.autonomy_scale.instate(["disabled"]), "the slider stayed live during a run")
    _check("a run drafts without it" in c.autonomy_label.cget("text"),
           c.autonomy_label.cget("text"))
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
    _check(not c.autonomy_scale.instate(["disabled"]), "the slider stayed off after the run")
    _check("(the draft gate)" in c.autonomy_label.cget("text"), c.autonomy_label.cget("text"))
    _check("Run ASKING" in c.guidance.get("1.0", "end"), c.guidance.get("1.0", "end"))
    _check("Why: 1 decision request awaits H" in c.guidance.get("1.0", "end"),
           "the cockpit did not say why the run ended")
    _check(any(w.title().startswith("Requests awaiting") for w in windows),
           "asking did not open the Requests window")


def run_window_comes_back():
    """Close hides the run's window, it does not end it: Build > Show Run Window
    brings back the same window with all it showed -- and a new run replaces it."""
    import json
    import types
    import app
    c = _cockpit()
    app.threading = types.SimpleNamespace(Thread=_InlineThread)

    c.show_run_window()
    said = c.guidance.get("1.0", "end")
    _check("No run" in said and ".sge" in said, said)

    done = [json.dumps({"type": "sge.run", "outcome": "done", "rounds": 1, "why": "met"})]
    c._open_run_window(_FakeRun(done), str(c.proj / "TASK.md"), 5)
    _settle(c)
    win = c._run_win
    close = next(w for w in _walk(win) if isinstance(w, ttk.Button) and w.cget("text") == "Close")
    close.invoke()
    _check(win.winfo_exists(), "Close destroyed the run window")
    win.tk.call(win.protocol("WM_DELETE_WINDOW"))           # the title bar's close button
    _check(win.winfo_exists(), "the title bar's close destroyed the run window")

    brought = []
    win.deiconify = lambda: brought.append(True)            # a mapped window would take the focus
    c.show_run_window()
    _check(brought, "Show Run Window did not bring the window back")
    shown = "\n".join(w.get("1.0", "end") for w in _walk(win) if isinstance(w, tk.Text))
    _check("RUN DONE" in shown, shown)

    c._open_run_window(_FakeRun(done), str(c.proj / "TASK.md"), 5)
    _settle(c)
    _check(not win.winfo_exists() and c._run_win is not win, "the old run window stayed")


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


class _InlineThread:
    """A thread that runs where it is started: the scenarios drive Tk by hand,
    with no mainloop for a background thread to hand its result back to."""
    def __init__(self, target=None, args=(), daemon=None):
        self._call, self._args = target, args

    def start(self):
        self._call(*self._args)


class _ProposingPlanner:
    def propose_goal(self, purpose, must_do, always, out_of_scope, **kw):
        return {"must_do": [must_do or "x", "arrow keys move the paddle"],
                "always": ["the logic runs without a window"], "out_of_scope": ["sound"]}


def new_project_suggests_a_goal():
    """In the New Project dialog, P turns a few words into a fuller goal -- in the
    fields, for the person to edit; nothing is written."""
    import types
    import app
    c = _cockpit()
    app.GroundworkDialog.grab_set = lambda self: None
    app.threading = types.SimpleNamespace(Thread=_InlineThread)
    d = app.GroundworkDialog(c, str(c.proj))
    d._planner = _ProposingPlanner()
    d.wants_run.set(True)
    d._toggle_goal()
    d.goal["behaviours"].insert("1.0", "A pong game against a bot.")
    d._suggest_goal()
    _settle(d)
    said = d.goal["behaviours"].get("1.0", "end")
    _check("A pong game against a bot." in said and "arrow keys move the paddle" in said, said)
    _check("the logic runs without a window" in d.goal["always"].get("1.0", "end"), "always")
    _check("It is your goal" in d.suggest_status.cget("text"), d.suggest_status.cget("text"))
    _check(not (c.proj / "TASK.md").exists(), "a suggestion wrote TASK.md")
    d._cancel()


def new_project_over_a_floor_keeps_the_dialog():
    """A floor is laid once. Over an existing one the dialog says so -- and
    stays open, so what was typed, and what P proposed, is not lost -- and it
    names the way to change the goal of a project that exists."""
    import app
    c = _cockpit()
    app.GroundworkDialog.grab_set = lambda self: None
    said = []
    app.messagebox.showerror = lambda title, msg, **k: said.append(msg)
    d = app.GroundworkDialog(c, str(c.proj))          # c.proj has a root already
    d.wants_run.set(True)
    d._toggle_goal()
    d.goal["behaviours"].insert("1.0", "A pong game against a bot.")
    d._ok()
    _check(d.result is None, "a floor was offered over an existing one")
    _check(said and "already holds a root node" in said[0], str(said))
    _check("Edit Goal (TASK.md)" in said[0], "the way to change the goal is not named")
    _check(d.winfo_exists(), "the dialog closed and took the input with it")
    _check("A pong game" in d.goal["behaviours"].get("1.0", "end"), "the input is gone")
    d._cancel()


def open_target_prepares_the_revise():
    """A decision request for a node: Open target loads that node's spec and puts
    the change into the Intent box, so Revise can apply it -- nothing to copy --
    and the main window has a Save for what Revise produces."""
    c = _cockpit()
    gui = c.proj / "gui" / "SPEC.md"
    gui.write_text(gui.read_text().replace(
        "status: implemented",
        "decision_requests:\n  - {target: svc, proposal: 'svc offers a graphical interface.', "
        "reason: the task asks for one}\nstatus: implemented"), encoding="utf-8")
    c.reload_nodes()
    tree, buttons = _window(c)
    item = next(i for i in tree.get_children() if "svc.gui" in str(tree.item(i, "values"))
                and "decision" in str(tree.item(i, "values")).lower())
    tree.selection_set(item)
    _settle(c)
    buttons["Open target"].invoke()
    _settle(c)
    prepared = c.input.get("1.0", "end")
    _check("Apply this decision, requested by svc.gui: svc offers a graphical interface."
           in prepared, prepared)
    said = c.guidance.get("1.0", "end")
    _check("Revise ->" in said and "Resolved" in said, said)
    _check(c.target.get() == "svc", c.target.get())
    _check(str(c.save_button.cget("text")) == "Save", "no Save in the main window")


def picking_a_target_loads_its_spec():
    """The Target box works like a double-click in the graph: pick a node and its
    SPEC.md is in the editor. A spec nobody saved is not thrown away unasked --
    declined, the target goes back to the node the draft belongs to."""
    import app
    c = _cockpit()
    gui = (c.proj / "gui" / "SPEC.md").read_text()
    c.target.set("svc.gui")
    c.target.event_generate("<<ComboboxSelected>>")
    _settle(c)
    _check(c.view.get("1.0", "end").strip() == gui.strip(), "svc.gui's spec was not loaded")

    # the view is as on disk: nothing to lose, no question
    asked = []
    app.messagebox.askyesno = lambda *a, **k: asked.append(a) or False
    c.target.set("svc")
    c.target.event_generate("<<ComboboxSelected>>")
    _settle(c)
    _check(not asked, "asked although nothing was unsaved")
    _check("id: svc\n" in c.view.get("1.0", "end"), "svc's spec was not loaded")

    # an unsaved revision of svc; picking svc.gui asks, and No keeps it
    draft = c.view.get("1.0", "end").strip().replace("purpose: x", "purpose: changed")
    c._set(c.view, draft)
    c.target.set("svc.gui")
    c.target.event_generate("<<ComboboxSelected>>")
    _settle(c)
    _check(len(asked) == 1, f"asked {len(asked)} time(s)")
    _check(c.view.get("1.0", "end").strip() == draft, "the unsaved spec was discarded")
    _check(c.target.get() == "svc", f"the target stayed {c.target.get()}")

    # Yes discards it and loads the pick
    app.messagebox.askyesno = lambda *a, **k: True
    c.target.set("svc.gui")
    c.target.event_generate("<<ComboboxSelected>>")
    _settle(c)
    _check(c.view.get("1.0", "end").strip() == gui.strip(), "svc.gui's spec was not loaded")


def codex_builds_its_context():
    """Codex gives C a bundle built from the SAVED specs, every time -- never the
    editor's text: not a bare SPEC.md, not another node's bundle, not an edit.
    Build Context is a read-only preview; an unsaved spec stops Codex, because C
    implements what is saved."""
    import app
    c = _cockpit()
    sent = []

    def implement(bundle, nid, **kw):
        sent.append(bundle)
        raise OSError("not launched in a test")

    def for_gui(bundle):
        return (bundle.startswith("# ARCHITECTURE.md")
                and "# Target node: svc.gui (full spec)" in bundle)

    app.coder.command = lambda: (["codex"], {})
    app.coder.implement = implement

    # the spec of svc.gui in the editor -- as picking the node leaves it
    c.target.set("svc.gui")
    c.target.event_generate("<<ComboboxSelected>>")
    _settle(c)
    c.run_agent()
    _check(len(sent) == 1 and for_gui(sent[0]), f"C got no bundle: {sent[-1][:80] if sent else ''}")
    _check(c.view.get("1.0", "end").strip() == sent[0].strip(), "what C got is not shown")

    # a bundle of ANOTHER node in the editor: C still gets svc.gui's
    c.target.set("svc")
    c.build_ctx()
    c.target.set("svc.gui")
    c.run_agent()
    _check(for_gui(sent[-1]), "C got the bundle of svc")

    # the preview is read-only, and even a forced edit does not reach C
    c.build_ctx()
    _check(str(c.view.cget("state")) == "disabled", "the preview can be edited")
    said = c.guidance.get("1.0", "end")
    _check("preview" in said and "saved specs" in said, said)
    c.view.configure(state="normal")
    c.view.insert("end", "\nNOTE: keep choose() pure.")
    c.run_agent()
    _check("NOTE" not in sent[-1], "an edit of the bundle reached C")

    # anything written to the editor makes it writable again
    c.load_spec()
    _check(str(c.view.cget("state")) == "normal", "a loaded spec stayed read-only")

    # an unsaved spec: nothing is sent
    c._set(c.view, c.view.get("1.0", "end").strip().replace("purpose: y", "purpose: z"))
    before = len(sent)
    c.run_agent()
    _check(len(sent) == before, "C was started over an unsaved spec")
    said = c.guidance.get("1.0", "end")
    _check("not saved" in said, said)


def check_goal_says_the_verdict():
    """Build > Check Goal: E and H' judge the project against TASK.md with no
    agent. The verdict goes to Guidance -- the editor, and a draft in it, stay
    as they are -- and nothing starts without a goal or during a run."""
    import types
    import app
    c = _cockpit()
    app.threading = types.SimpleNamespace(Thread=_InlineThread)
    c.after = lambda ms, fn, *args: fn(*args)            # no mainloop to hand back to

    c.check_goal()
    said = c.guidance.get("1.0", "end")
    _check("No goal to check against" in said, said)

    (c.proj / "TASK.md").write_text("# Task\n", encoding="utf-8")
    seen = []

    shown = []

    def check(root, task, progress=None):
        seen.append(task)
        for step in app.orchestrate.CHECK_STEPS:            # what the real one says
            progress(step)
            shown.append(c.guidance.get("1.0", "end"))
        return {"verdict": "gaps", "why": "H' names 1 gap(s) against TASK.md",
                "failures": [], "gaps": ["no test for the tkinter window"], "waiting": [],
                "closed": [], "summary": "", "requests": [], "model": "m"}
    app.orchestrate.check = check
    c._set(c.view, "---\nid: svc\nan unsaved draft\n---\n")
    c.check_goal()
    said = c.guidance.get("1.0", "end")
    _check(seen == ["# Task\n"], f"checked against {seen}")
    _check("[1/2] E runs the tests" in shown[0] and "working" in shown[0], shown[0])
    _check("[1/2] E runs the tests -- the whole build -- and the gate   done" in shown[1]
           and "[2/2] H' reads TASK.md" in shown[1] and "minute or two" in shown[1],
           shown[1])
    _check("CHECK     GAPS" in said and "gap       no test for the tkinter window" in said,
           said)
    _check("Start Run" in said, "the verdict did not say what to do next")
    _check("an unsaved draft" in c.view.get("1.0", "end"), "the check replaced the editor")
    _check(not c._checking, "the check never finished")

    c._run = {"round": 1}                                 # a run in progress
    c.check_goal()
    _check(len(seen) == 1, "a check started during a run")
    c._run = None


def rename_node_shows_the_plan_first():
    """Node > Rename Node: the plan is shown before anything moves; a no leaves
    everything as it was, a yes renames, and the cockpit follows the node."""
    import app
    c = _cockpit(replies=["window", "screen"])          # the new last id part, twice
    asked = []
    app.messagebox.askyesno = lambda title, msg, **k: asked.append(msg) or False
    c.target.set("svc.tkwin")
    c.rename_node()
    _check(asked and "svc.tkwin  ->  svc.window" in asked[0], f"no plan shown: {asked}")
    _check((c.proj / "tkwin" / "SPEC.md").exists(), "a no still renamed it")

    app.messagebox.askyesno = lambda *a, **k: True
    c.rename_node()
    _check("svc.screen" in c.nodes and "svc.tkwin" not in c.nodes, sorted(c.nodes))
    _check(c.target.get() == "svc.screen", f"the target is {c.target.get()}")
    _check("id: svc.screen" in c.view.get("1.0", "end"), "the renamed spec is not loaded")
    said = c.guidance.get("1.0", "end")
    _check("renamed   svc.tkwin -> svc.screen" in said and "code      untouched" in said,
           said)


def code_affected_codes_in_order_and_locks():
    """Build > Codex Affected: the list in order is shown first; it runs
    `cli.py code ROOT ID --affected` as a process of its own, shown like a run --
    the writers locked while C writes -- and says how it ended."""
    import types
    import app
    c = _cockpit()
    app.threading = types.SimpleNamespace(Thread=_InlineThread)
    app.llm.missing = lambda role: []
    asked, started = [], []
    app.messagebox.askyesno = lambda title, msg, **k: asked.append(msg) or True
    lines = ["affected, in order: svc.gui", "", "===== 1/1  C implements svc.gui =====",
             "C writes ...", "AFFECTED DONE: 1 node(s) coded; tests pass, gate pass"]

    def popen(argv, **kw):
        started.append(argv)
        return _FakeRun(lines)
    app.subprocess.Popen = popen
    c.target.set("svc.gui")
    c.code_affected()
    _check(asked and "1. svc.gui" in asked[0], f"no list shown first: {asked}")
    _check(started and started[0][-4:] == ["code", c.root_dir, "svc.gui", "--affected"],
           f"argv {started}")
    for _ in range(400):
        if c._chain is None:
            break
        _settle(c)
    _check(c._chain is None, "Codex Affected never ended")
    shown = "\n".join(w.get("1.0", "end") for w in _walk(c._run_win) if isinstance(w, tk.Text))
    _check("C implements svc.gui" in shown and "AFFECTED DONE" in shown, shown)
    _check("AFFECTED DONE" in c.guidance.get("1.0", "end"), c.guidance.get("1.0", "end"))
    _check(str(c.draft_button.cget("state")) == "normal", "Draft stayed locked")

    asked.clear()
    app.messagebox.askyesno = lambda title, msg, **k: asked.append(msg) or False
    c.code_affected()
    _check(len(started) == 1, "a no still started it")


def find_in_any_text():
    """Cmd+F / Ctrl+F finds in a text: every match marked, the current one counted,
    Enter and Shift+Enter step through, read-only text too, Esc clears the marks.
    With the focus on a button it searches the biggest text of that window."""
    import types
    import app
    c = _cockpit()
    _check(c.bind_class("Text", c.find_key), "no find key on text widgets")
    c._preview("alpha beta\nAlpha gamma\nnothing\nALPHA")      # read-only, too
    box = app.FindBox.show(c.view)
    box.var.set("alpha")
    _check(box.count.cget("text") == "1 of 3", box.count.cget("text"))
    _check(len(c.view.tag_ranges("find")) == 6, "not every match is marked")
    box.next()
    box.next()
    _check(box.count.cget("text") == "3 of 3", box.count.cget("text"))
    box.next()
    _check(box.count.cget("text") == "1 of 3", "next does not wrap around")
    box.prev()
    _check(box.count.cget("text") == "3 of 3", "prev does not wrap around")
    _check(app.FindBox.show(c.view) is box, "a second Cmd+F opened a second box")
    box.var.set("zebra")
    _check(box.count.cget("text") == "not found", box.count.cget("text"))
    box.close()
    _check(not c.view.tag_ranges("find") and not c.view.tag_ranges("find_current"),
           "closing left marks behind")

    (c.proj / "TASK.md").write_text("# Task\n\nfind me here\n", encoding="utf-8")
    c.edit_goal()
    _settle(c)
    win = [w for w in c.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    button = next(w for w in _walk(win) if isinstance(w, ttk.Button))
    c._find_in_window(types.SimpleNamespace(widget=button))
    box = app.FindBox._open.get(str(win._editor))
    _check(box is not None, "Cmd+F on a button did not search the window's editor")
    box.var.set("find me")
    _check(box.count.cget("text") == "1 of 1", box.count.cget("text"))


def compact_shows_a_draft_and_a_lost_promise():
    """Compact puts the shorter spec in the editor, unsaved, and says loudly when a
    provides name went missing; Revise shows P's note on its change."""
    import app
    c = _cockpit()
    gui = c.proj / "gui" / "SPEC.md"
    gui.write_text(gui.read_text().replace("contract: {purpose: y}",
                                           "contract: {purpose: y, provides: [choose(), show()]}"),
                   encoding="utf-8")
    c.reload_nodes()
    saved = gui.read_text()
    c.target.set("svc.gui")
    app.planner.compact_spec = lambda cur, arch="", **kw: (
        cur.replace("choose(), show()", "choose()"), "merged show into choose")
    c.compact()
    said = c.guidance.get("1.0", "end")
    _check("WARNING -- compacting dropped from provides: show" in said, said)
    _check("P's note: merged show into choose" in said, said)
    _check("show()" not in c.view.get("1.0", "end"), "the draft is not in the editor")
    _check(gui.read_text() == saved, "Compact saved by itself")

    c.load_spec()
    app.planner.compact_spec = lambda cur, arch="", **kw: (cur + "\nShort.\n", "")
    c.compact()
    _check("Every provides name is still there." in c.guidance.get("1.0", "end"),
           c.guidance.get("1.0", "end"))

    c.load_spec()
    app.planner.revise_spec = lambda cur, change, **kw: (cur, "show takes a title now")
    c._set(c.input, "give show a title")
    c.revise()
    _check("P's note: show takes a title now" in c.guidance.get("1.0", "end"),
           c.guidance.get("1.0", "end"))


def edit_goal_with_p():
    """For a project that exists: TASK.md in an editor, P's proposal in its place,
    written only by Save."""
    import types
    import app
    c = _cockpit()
    app.threading = types.SimpleNamespace(Thread=_InlineThread)
    app.llm.missing = lambda role: []
    app.planner.propose_goal = _ProposingPlanner().propose_goal
    task = c.proj / "TASK.md"
    task.write_text("# Task\n\na game like pong\n\n## What it must do\n\n"
                    "- A pong game against a bot.\n", encoding="utf-8")
    c.edit_goal()
    _settle(c)
    win = [w for w in c.winfo_children() if isinstance(w, tk.Toplevel)
           and w.title().startswith("Goal - ")][-1]
    win._suggest()
    _settle(c)
    text = win._editor.get("1.0", "end")
    _check("arrow keys move the paddle" in text and "A pong game against a bot." in text, text)
    _check("## Done means" in text, "the method's standard went missing")
    _check("arrow keys" not in task.read_text(encoding="utf-8"), "saved before Save")
    win._save()
    _check("arrow keys move the paddle" in task.read_text(encoding="utf-8"), "not saved")


def _walk(w):
    yield w
    for ch in w.winfo_children():
        yield from _walk(ch)


SCENARIOS = {f.__name__: f for f in (badge, validate, grant, invalid_grant, stale,
                                     hard_accept, hard_reject,
                                     run_window, run_window_comes_back,
                                     run_locks_the_writers,
                                     run_dialog_modes, run_window_unsupervised,
                                     new_project_scrolls, new_project_suggests_a_goal,
                                     edit_goal_with_p,
                                     new_project_over_a_floor_keeps_the_dialog,
                                     open_target_prepares_the_revise,
                                     picking_a_target_loads_its_spec,
                                     codex_builds_its_context,
                                     check_goal_says_the_verdict,
                                     rename_node_shows_the_plan_first,
                                     code_affected_codes_in_order_and_locks,
                                     find_in_any_text,
                                     compact_shows_a_draft_and_a_lost_promise)}

if __name__ == "__main__":
    SCENARIOS[sys.argv[1]]()
    print("ok")
