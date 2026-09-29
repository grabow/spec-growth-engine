"""Spec Growth Engine - guided cockpit (Tk shell over the headless engine).

Plain ASCII in tk.Text widgets: the view pane is both viewer AND editor, so you
review/edit the AI's SPEC.md draft in place. No markdown rendering needed.

Run:  uv run python app.py [SPEC_ROOT]   (default: ./example)
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from pathlib import Path


def _locate_bundled_tcl() -> None:
    """Point Tcl/Tk at the libraries shipped with the running interpreter.

    uv's CPython bundles Tcl/Tk under the INSTALLATION (sys.base_prefix), but
    inside a virtualenv Tcl searches relative to sys.prefix -- the venv -- and
    finds nothing: `uv run python app.py` died with "Can't find a usable
    init.tcl" while the libraries sat right there. Only fills in what is unset,
    so an explicit TCL_LIBRARY still wins, and does nothing on interpreters that
    locate their own (Homebrew, the system framework build).

    Must run BEFORE `import tkinter`: the paths are read when Tk initialises.
    """
    lib = Path(sys.base_prefix) / "lib"
    for var, pattern, marker in (("TCL_LIBRARY", "tcl8.*", "init.tcl"),
                                 ("TK_LIBRARY", "tk8.*", "tk.tcl")):
        if os.environ.get(var):
            continue
        for candidate in sorted(lib.glob(pattern)):
            if (candidate / marker).is_file():
                os.environ[var] = str(candidate)
                break


_locate_bundled_tcl()

import tkinter as tk  # noqa: E402  (must follow _locate_bundled_tcl)
from tkinter import filedialog, messagebox, ttk  # noqa: E402
from tkinter.scrolledtext import ScrolledText  # noqa: E402

from dotenv import load_dotenv

load_dotenv()  # read cockpit/.env: SGE_<ROLE>_BASE_URL / _API_KEY / _MODEL per role

import appconfig
import groundwork
import layouts
import orchestrate
import runlog
import specfix
import testrun
from agent import coder, llm, planner, reviewer, semantic
from engine import (
    accepted, assist, autonomy, capability, changeset, context, drift, graph, inbox,
    index as index_mod, intents, iteration, lifecycle, migration, nodes as nodeops,
    parser, validate,
)

KINDS = ["component", "container", "system", "code"]

def _looks_like_spec(text: str) -> bool:
    """True if the text is a SPEC.md: YAML frontmatter containing an `id:` line."""
    t = text.lstrip()
    if not t.startswith("---"):
        return False
    end = t.find("\n---", 3)
    head = t[:end] if end != -1 else t
    return any(line.strip().startswith("id:") for line in head.splitlines())


def _spec_id(text: str) -> str:
    """The `id:` of a SPEC.md's frontmatter; "" when the text is not a SPEC.md."""
    if not _looks_like_spec(text):
        return ""
    t = text.lstrip()
    end = t.find("\n---", 3)
    for line in (t[:end] if end != -1 else t).splitlines():
        if line.strip().startswith("id:"):
            return line.strip()[3:].strip().strip("'\"")
    return ""

MONO = ("TkFixedFont", 12)


def _node_tree_children(nodes: dict[str, dict]) -> dict[str, list[str]]:
    """Return parent -> child node ids; missing parents are shown as root-level."""
    children: dict[str, list[str]] = {"": []}
    for nid, node in nodes.items():
        parent = node.get("parent")
        parent_key = parent if parent in nodes else ""
        children.setdefault(parent_key, []).append(nid)
        children.setdefault(nid, [])
    for kids in children.values():
        kids.sort()
    return children


def _orphan_nodes(nodes: dict[str, dict]) -> set[str]:
    """Nodes naming a parent that is not in the graph. They get laid out at root
    level, where they look like a legitimate second system -- so flag them."""
    return {nid for nid, node in nodes.items()
            if node.get("parent") and node.get("parent") not in nodes}


def _default_collapsed(nodes: dict[str, dict]) -> set[str]:
    """Collapsed on open: everything below container level. The full tree is
    ~230px per LEAF, so a handful of containers is several screens wide."""
    children = _node_tree_children(nodes)
    return {nid for nid, node in nodes.items()
            if node.get("kind") == "container" and children.get(nid)}


def _node_graph_layout(
    nodes: dict[str, dict],
    *,
    collapsed: Iterable[str] = (),
    x_gap: int = 230,
    y_gap: int = 130,
    x_origin: int = 120,
    y_origin: int = 70,
) -> tuple[dict[str, tuple[int, int]], list[tuple[str, str]]]:
    """Top-down ownership-tree layout: y = C4 depth, x = leaf slots, parents
    centred over their children. A collapsed node keeps its box but contributes
    its children neither as boxes nor as leaf slots."""
    children = _node_tree_children(nodes)
    hide_under = set(collapsed)
    positions: dict[str, tuple[int, int]] = {}
    edges: list[tuple[str, str]] = []
    leaf_index = 0

    def walk(nid: str, depth: int) -> int:
        nonlocal leaf_index
        kids = [] if nid in hide_under else children.get(nid, [])
        if not kids:
            x = x_origin + leaf_index * x_gap
            leaf_index += 1
        else:
            child_xs = []
            for child in kids:
                edges.append((nid, child))
                child_xs.append(walk(child, depth + 1))
            x = sum(child_xs) // len(child_xs)
        positions[nid] = (x, y_origin + depth * y_gap)
        return x

    for root_id in children.get("", []):
        walk(root_id, 0)
    return positions, edges


def _hidden_counts(nodes: dict[str, dict], visible: Iterable[str]) -> dict[str, int]:
    """node id -> how many of its descendants the collapse state hides. Nodes
    hidden under a visible child count towards THAT child, not here."""
    children = _node_tree_children(nodes)
    drawn = set(visible)
    counts: dict[str, int] = {}
    for nid in nodes:
        hidden, stack = 0, list(children.get(nid, []))
        while stack:
            cur = stack.pop()
            if cur not in drawn:
                hidden += 1
                stack.extend(children.get(cur, []))
        counts[nid] = hidden
    return counts


def _dependency_edges(nodes: dict[str, dict],
                      visible: Iterable[str]) -> list[tuple[str, str]]:
    """Declared depends_on edges, lifted to the nearest DRAWN ancestor -- so a
    collapsed container still shows what its insides depend on. Edges that
    collapse onto a single box are dropped; the rest are de-duplicated."""
    drawn = set(visible)
    anchor: dict[str, str | None] = {}
    for nid in nodes:
        cur: str | None = nid
        while cur and cur not in drawn:
            cur = nodes.get(cur, {}).get("parent")
        anchor[nid] = cur
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for nid, node in nodes.items():
        for dep in node.get("depends_on") or []:
            if dep not in nodes:
                continue
            a, b = anchor.get(nid), anchor.get(dep)
            if not a or not b or a == b or (a, b) in seen:
                continue
            seen.add((a, b))
            out.append((a, b))
    return out


def _widget_size(widget, fallback: tuple[int, int] = (900, 600)) -> tuple[int, int]:
    """Usable size of a widget. An unmapped widget reports 1x1 -- taking that at
    face value makes `Fit` zoom all the way out on a window that just opened."""
    w, h = widget.winfo_width(), widget.winfo_height()
    if w <= 1 or h <= 1:
        w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
    return (w if w > 1 else fallback[0], h if h > 1 else fallback[1])


def _scaled_font(font: tuple[str, int], zoom: float) -> tuple[str, int]:
    return (font[0], max(6, int(round(font[1] * zoom))))


def _fit_label(text: str, px: int, font_px: int) -> str:
    """Shorten an id with an ellipsis so it stays inside its box when zoomed out."""
    chars = max(3, int(px / max(font_px * 0.62, 1)))
    return text if len(text) <= chars else text[:chars - 1] + "\u2026"


def _box_exit(x: int, y: int, tx: int, ty: int, w: int, h: int) -> tuple[int, int]:
    """Where the line from box centre (x,y) towards (tx,ty) leaves the box, so
    dependency edges touch the border instead of running under the label."""
    dx, dy = tx - x, ty - y
    if not dx and not dy:
        return x, y
    sx = (w / 2) / abs(dx) if dx else float("inf")
    sy = (h / 2) / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return int(x + dx * s), int(y + dy * s)


def _node_fill(kind: str) -> str:
    return {
        "system": "#f3f0ff",
        "container": "#e9f5ff",
        "component": "#ecf8ef",
        "code": "#fff4df",
    }.get(kind, "#f4f4f4")


class Cockpit(tk.Tk):
    def __init__(self, root_arg: str | None = None) -> None:
        super().__init__()
        self.geometry("1300x840")
        self.config_data = appconfig.load()
        # working dir: explicit arg > last used > bundled example
        root = root_arg or self.config_data.get("last_root") or "example"
        if not Path(root).is_dir():
            root = "example"
        self.root_dir = str(Path(root))
        self.graph_collapsed: set[str] | None = None  # graph view: collapsed subtrees
        self.graph_zoom = 1.0
        self._graph_root: str | None = None  # root the view state belongs to
        self._run: dict | None = None        # the run in progress, if any
        self._save_config()  # persist the resolved root
        self._update_title()
        self.reload_nodes()

        self._build_menu()

        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True)

        left = ttk.PanedWindow(main, orient="vertical")
        main.add(left, weight=1)

        # --- target picker + intent input ---
        top = ttk.Frame(left)
        left.add(top, weight=4)
        row = ttk.Frame(top)
        row.pack(fill="x")
        ttk.Label(row, text="Target node:").pack(side="left")
        self.target = ttk.Combobox(row, values=sorted(self.nodes), state="readonly")
        self.target.pack(side="left", fill="x", expand=True, padx=4)
        # picking a node shows its SPEC.md, as a double-click in the graph does
        self.target.bind("<<ComboboxSelected>>", lambda _e: self._target_picked())
        ttk.Button(row, text="Tree...", command=self.show_node_tree).pack(side="left")
        # The way back to agents: requests awaiting H. The count is on the button so
        # a pending decision is visible without pressing Validate and reading warnings.
        self.requests_button = ttk.Button(row, text="Requests", command=self.show_requests)
        self.requests_button.pack(side="left", padx=(4, 0))
        # the first reload ran before this button existed, so count now -- opening a
        # project is exactly when pending requests need to be visible
        self._update_requests_badge()
        if self.nodes:
            self.target.current(0)

        ttk.Label(
            top, text="Intent for Draft (language + examples)  /  change request for Revise"
        ).pack(anchor="w", pady=(6, 0))
        self.input = ScrolledText(top, height=8, font=MONO, wrap="word")
        self.input.pack(fill="both", expand=True)
        btns = ttk.Frame(top)
        btns.pack(anchor="e", pady=4)
        # Both emit a spec into the View on the right; long arrow = Draft (from
        # scratch), short arrow = Revise (edits the existing spec in place, status kept).
        self.draft_button = ttk.Button(btns, text="Draft ⟶", command=self.draft)
        self.draft_button.pack(side="left", padx=3)
        self.revise_button = ttk.Button(btns, text="Revise →", command=self.revise)
        self.revise_button.pack(side="left", padx=3)
        # what Draft and Revise put into the editor is not saved until this is pressed
        self.save_button = ttk.Button(btns, text="Save", command=self.save_spec)
        self.save_button.pack(side="left", padx=(12, 3))

        # --- guidance pane (small: little text lives here) ---
        gf = ttk.Frame(left)
        left.add(gf, weight=1)

        # --- two controls, because they are two decisions ---
        # the SLIDER is the draft gate (D0..D2): who clears a spec you are drafting,
        # here, now. It stops at D2 because a draft is not on disk and cannot be
        # migrated. The other two switches do not belong on its scale: the
        # delegation acts on PENDING HARD changes, per project, and a run is not a
        # level at all -- it is how a project is operated (AUTONOMY.md 2).
        af = ttk.Frame(gf)
        af.pack(fill="x", pady=(0, 2))
        ttk.Label(af, text="Autonomy").pack(side="left")
        self.autonomy = tk.IntVar(
            value=min(int(self.config_data.get("draft_gate", 1) or 0),
                      autonomy.DRAFT_MAX))
        self.autonomy_scale = ttk.Scale(
            af, from_=0, to=autonomy.DRAFT_MAX, orient="horizontal",
            command=self._on_autonomy)
        self.autonomy_scale.pack(side="left", fill="x", expand=True, padx=4)
        self.autonomy_label = ttk.Label(af, font=MONO)
        self.autonomy_label.pack(side="left")
        self.autonomy_scale.set(self.autonomy.get())  # after label exists (set fires _on_autonomy)
        ticks = ttk.Frame(gf)
        ticks.pack(fill="x")
        for i in range(autonomy.DRAFT_MAX + 1):
            ttk.Label(ticks, text=f"D{i}", font=MONO).pack(side="left", expand=True)
        self._render_autonomy()

        # the SWITCH is the delegation (on/off): who accepts a pending HARD change
        # in THIS project. H's act, revocable, recorded in .sge/autonomy.json and
        # in the audit log -- the same act as `cli.py delegate ROOT on`.
        pf = ttk.Frame(gf)
        pf.pack(fill="x", pady=(2, 2))
        self.delegation = tk.BooleanVar(value=False)
        self.delegation_box = ttk.Checkbutton(
            pf, text="Delegation: let H' accept HARD changes in its scope",
            variable=self.delegation, command=self._on_delegation)
        self.delegation_box.pack(side="left")
        self.delegation_label = ttk.Label(pf, font=MONO, foreground="#5f5e5a")
        self.delegation_label.pack(side="left", padx=(6, 0))
        self._render_delegation()

        ttk.Label(gf, text="Guidance").pack(anchor="w")
        self.guidance = ScrolledText(gf, height=6, font=MONO, wrap="word")
        self.guidance.pack(fill="both", expand=True)

        # --- view / editor pane ---
        vf = ttk.Frame(main)
        main.add(vf, weight=2)
        ttk.Label(vf, text="View / Editor  (SPEC.md draft / context / drift)").pack(anchor="w")
        self.view = ScrolledText(vf, font=MONO, wrap="none")
        self.view.pack(fill="both", expand=True)

        self._set(
            self.guidance,
            "Step 1 - pick or name a target node, describe the intent, then 'Draft ⟶'.\n"
            f"Loaded {len(self.nodes)} node(s) from {self.root_dir}.",
        )

    # ---- helpers ---------------------------------------------------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        def menu(label: str, items: list) -> None:
            m = tk.Menu(menubar, tearoff=0)
            for entry in items:
                if entry is None:
                    m.add_separator()
                else:
                    text, cmd = entry
                    m.add_command(label=text, command=cmd)
            menubar.add_cascade(label=label, menu=m)

        menu("Open", [("Open", self.open_dir), ("New Project...", self.groundwork),
                      ("New Project Like...", self.groundwork_like), None,
                      ("Refresh Manuals", self.refresh_manuals),
                      ("Reload", self.reload_and_refresh)])
        menu("Node", [("Show Tree", self.show_node_tree), None,
                      ("New Node", self.new_node), ("Delete Node", self.delete_node)])
        menu("Arch", [("Edit Arch", self.load_arch), ("Save Arch", self.save_arch)])
        menu("Spec", [("Load Spec", self.load_spec), ("Save Spec", self.save_spec)])
        menu("Build", [("Build Context", self.build_ctx), ("Codex", self.run_agent),
                       ("Run Tests", self.run_tests_action), None,
                       ("Edit Goal (TASK.md)...", self.edit_goal),
                       ("Start Run...", self.start_run)])
        menu("Validate", [("Requests...", self.show_requests), None,
                          ("Validate", self.run_validate), ("Drift", self.run_drift),
                          None, ("Generate Index", self.generate_index),
                          ("Install Git Hook", self.install_git_hook)])
        menu("Registry", [("Find Capability", self.find_capability),
                          ("Duplicates", self.show_duplicates),
                          ("Claim Capability", self.claim_capability)])
        self.config(menu=menubar)

    def reload_nodes(self) -> None:
        self.nodes = parser.load_nodes(self.root_dir)
        self.arch = parser.load_architecture(self.root_dir)
        self._update_requests_badge()

    def _update_requests_badge(self) -> None:
        """Show how many requests await H on the Requests button. Called on every
        reload; the button does not exist yet during the first load in __init__."""
        if not hasattr(self, "requests_button"):
            return
        try:
            n = len(inbox.pending(self.nodes, self.root_dir))
        except Exception:  # a malformed request must not break loading
            n = 0
        self.requests_button.configure(text=f"Requests ({n})" if n else "Requests")

    def _heal_specs(self) -> list[str]:
        """Before loading, auto-repair any SPEC.md whose YAML breaks (the recurring
        unquoted 'word: word' colon / leading backtick) so a node never silently
        vanishes from the tree. Only files that do NOT parse are touched; valid specs
        are left exactly as-is. Files that cannot be auto-fixed are reported as broken
        (visible, not silent). NOTE: this is an authoring-time convenience -- the CLI
        gate stays strict and BLOCKS on invalid YAML (no silent drift into a commit).
        """
        notes: list[str] = []
        for rel, msg in parser.invalid_specs(self.root_dir):
            path = Path(self.root_dir) / rel
            try:
                original = path.read_text(encoding="utf-8")
            except OSError:
                continue
            fixed, fixes = specfix.repair_frontmatter(original)
            if fixes:
                path.write_text(fixed if fixed.endswith("\n") else fixed + "\n", encoding="utf-8")
                notes.append(f"auto-fixed {rel} (quoted {len(fixes)} YAML line(s))")
            else:
                notes.append(f"BROKEN, hidden: {rel} -- {msg}")
        return notes

    def _reload_quiet(self) -> None:
        """Re-read specs/ARCHITECTURE from disk before a gate action, so it reflects
        on-disk truth (files may have changed via the coder or an external editor).
        Heals broken YAML first; updates the picker but leaves selection and guidance."""
        self._heal_specs()
        self.reload_nodes()
        self.target["values"] = sorted(self.nodes)

    def reload_and_refresh(self) -> None:
        heal = self._heal_specs()
        self.reload_nodes()
        self._render_delegation()   # another project, another delegation
        ids = sorted(self.nodes)
        self.target["values"] = ids
        if self._target() not in self.nodes and ids:
            self.target.set(ids[0])
        msg = f"Reloaded {len(self.nodes)} node(s) from {self.root_dir}."
        if heal:
            msg += "\nSPEC YAML check:\n  " + "\n  ".join(heal)
        self._set(self.guidance, msg)

    def _on_autonomy(self, raw: str) -> None:
        """Snap the slider to a discrete step and lock it at autonomy.DRAFT_MAX:
        a draft is not on disk, so it cannot be migrated -- the delegation acts on
        pending HARD changes and is set per project (`cli.py delegate`), not here."""
        try:
            lvl = round(float(raw))
        except (TypeError, ValueError):
            return
        capped = max(0, min(lvl, autonomy.DRAFT_MAX))
        if capped != self.autonomy_scale.get():
            self.autonomy_scale.set(capped)  # snap back; re-enters here but converges
        self.autonomy.set(capped)
        self.config_data["draft_gate"] = capped
        appconfig.save(self.config_data)
        self._render_autonomy()

    def _render_autonomy(self) -> None:
        if not hasattr(self, "autonomy_label"):
            return  # called during init before the label exists
        lvl = self.autonomy.get()
        running = getattr(self, "_run", None) is not None
        self.autonomy_label.config(
            text=f"D{lvl} {autonomy.NAMES.get(lvl, '?')}  "
                 + ("(a run drafts without it)" if running else "(the draft gate)"))

    # ---- the delegation: who accepts a pending HARD change here -------------

    def _render_delegation(self) -> None:
        """Show what .sge/autonomy.json says, not what the box was last left at:
        `cli.py delegate` and a run's setup write it too."""
        if not hasattr(self, "delegation_box"):
            return  # called during init before the widget exists
        on = autonomy.delegated(self.root_dir)
        self.delegation.set(on)
        self.delegation_label.config(
            text="H' may accept, in scope" if on else "every HARD change is yours")

    def _on_delegation(self) -> None:
        """H delegates, or takes it back. Asked once, because it is a delegation
        and not a preference -- and revocable: `reject` overrules any acceptance."""
        on = bool(self.delegation.get())
        if on and not messagebox.askyesno(
                "Delegate HARD changes",
                "Let the reviewer accept a breaking change ON ITS OWN, but only "
                "where:\n\n"
                "  - it is a component contract that other nodes consume,\n"
                "  - the node is not protected, not a container, not the root,\n"
                "  - and the engine finds every consumer migrated and tested.\n\n"
                "Protected zones, containers, ARCHITECTURE.md, new nodes and "
                "deletions stay yours. Every acceptance waits here for you to "
                "confirm or overrule.\n\nDelegate?"):
            self.delegation.set(autonomy.delegated(self.root_dir))
            return
        try:
            autonomy.set_delegation(self.root_dir, on, by=getpass.getuser())
        except (ValueError, OSError) as exc:
            messagebox.showerror("Delegation", str(exc))
        self._render_delegation()
        self._set(self.guidance,
                  f"Delegation {'on' if autonomy.delegated(self.root_dir) else 'off'}: "
                  + ("the reviewer may accept a pending HARD change inside its scope; "
                     "`Requests...` shows what it accepted, to confirm or overrule."
                     if self.delegation.get() else
                     "every pending HARD change waits for you (`Requests...`)."))

    def _update_title(self) -> None:
        self.title(f"Spec Growth Engine - Cockpit   [{self.root_dir}]")

    def _save_config(self) -> None:
        self.config_data["last_root"] = str(Path(self.root_dir).resolve())
        appconfig.save(self.config_data)

    # ---- project / root selection ---------------------------------------
    def open_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.root_dir, title="Open spec root")
        if not chosen:
            return
        self.root_dir = chosen
        self._save_config()
        self._update_title()
        self.reload_and_refresh()
        if not self.nodes:
            self._set(
                self.guidance,
                f"No nodes in {chosen}.\nUse 'New project...' to bootstrap a root SPEC.md.",
            )

    def groundwork_like(self) -> None:
        """Lay the floor another project was laid with, in a new directory: its
        recorded answers (<old>/.sge/groundwork.json) and its TASK.md as it reads
        now. A second attempt at the same task is a new directory, not the first
        one reset -- and nothing is asked again, so nothing drifts."""
        source = filedialog.askdirectory(title="Lay a new project like which one?",
                                         initialdir=self.root_dir, mustexist=True)
        if not source:
            return
        try:
            actions = groundwork.like(source, by=getpass.getuser())
        except ValueError as exc:
            messagebox.showerror("New project like...", str(exc))
            return
        target = filedialog.askdirectory(title="Where? (a new or empty directory)",
                                         initialdir=str(Path(source).parent))
        if not target:
            return
        why = groundwork.refuses(target)
        if why:
            messagebox.showerror("New project like...", why)
            return
        answers = groundwork.answers_of(source)
        if not messagebox.askyesno(
                "New project like...",
                f"Lay the floor of {source}\nin {target}:\n\n"
                f"  root `{answers.get('system_id')}`, container "
                f"`{answers.get('container')}`, {len(answers.get('invariants') or [])} "
                "invariant(s)"
                + ("\n  TASK.md, copied as it reads now" if (Path(source) / "TASK.md").is_file()
                   else "") + "\n\nLay it?"):
            return
        self._lay(target, actions, answers)

    def refresh_manuals(self) -> None:
        """AGENTS.md and ORCHESTRATOR.md, re-rendered for this project from the
        method's templates -- after the templates changed, or the container did."""
        try:
            texts = groundwork.manuals(self.root_dir)
        except (FileNotFoundError, ValueError) as exc:
            self._set(self.guidance, f"The manuals could not be rendered: {exc}")
            return
        said = []
        for name, text in texts.items():
            path = Path(self.root_dir) / name
            before = path.read_text(encoding="utf-8") if path.is_file() else None
            path.write_text(text, encoding="utf-8")
            said.append(f"{name}: " + ("unchanged" if before == text else
                                       "written" if before is None else "refreshed"))
        self._set(self.guidance, "Manuals, from the method's templates:\n  "
                  + "\n  ".join(said))

    def groundwork(self) -> None:
        """Lay a floor, then open the project on it. The dialog collects answers,
        groundwork.plan says what that would write, the person sees it, and only
        then is anything written -- the one place where a model's wording reaches
        a layer-1 artefact, through an answer a person gave (groundwork.py)."""
        dialog = GroundworkDialog(self, self.root_dir)
        try:
            from agent import planner
            planner_available = not llm.missing("planner")
            dialog._planner = planner if planner_available else None
        except ImportError:  # pragma: no cover
            pass
        self.wait_window(dialog)
        if not dialog.result:
            return
        answers = dialog.result
        root = answers.pop("root")
        why = groundwork.refuses(root)
        if why:
            messagebox.showerror("New project", why)
            return
        actions = groundwork.plan(answers)
        goal = any(isinstance(a, groundwork.WriteTask) for a in actions)
        preview = "\n".join(
            ["This will write:", ""]
            + [f"  {root}/SPEC.md            the root `{answers['system_id']}`",
               f"  {root}/{answers['container']}/SPEC.md   the container, with its code layout",
               f"  {root}/ARCHITECTURE.md    {len(answers['invariants'])} invariant(s)"]
            + ([f"  {root}/TASK.md            the goal a run is measured against"]
               if goal else [])
            + ["", "and record all of it as the accepted state, so every later change",
               "is measured against it.", "", "Lay this floor?"])
        if not messagebox.askyesno("New project", preview):
            return
        self._lay(root, actions, answers)

    def _lay(self, root: str, actions: list, answers: dict) -> None:
        """Write a confirmed floor and open the project on it."""
        try:
            said = groundwork.apply(root, actions)
        except (ValueError, OSError) as exc:
            messagebox.showerror("New project", str(exc))
            return
        self.root_dir = str(root)
        self._save_config()
        self._update_title()
        self.reload_and_refresh()
        roles = "\n  ".join(f"{role:9} {where}" for role, where in groundwork.endpoints())
        self._set(self.guidance, "The floor is laid:\n  " + "\n  ".join(said)
                  + f"\n\nroles, as a run would find them:\n  {roles}"
                  + "\n\nNow grow it: pick the container, say what the first component "
                    "is for, and press 'Draft ⟶'."
                  + ("\nFor the agent run: TASK.md and the manuals are in place -- read "
                     "the goal once more before you start it."
                     if (Path(self.root_dir) / "TASK.md").is_file() else
                     "\nFor an agent run, write TASK.md next to this root -- the "
                     "manuals are already there."))

    # ---- node CRUD -------------------------------------------------------
    def new_node(self) -> None:
        if not self.nodes:
            messagebox.showinfo("New node", "No root node yet. Create example/SPEC.md first.")
            return
        dialog = NewNodeDialog(self, sorted(self.nodes), self._target())
        self.wait_window(dialog)
        if not dialog.result:
            return
        parent_id, segment, kind, layout_key = dialog.result
        layout_inv = layouts.template(layout_key) if kind == "container" else None
        seed = None
        if kind == "container":
            # the build manifest comes from the SAME archetype as the layout lines
            seed = layouts.manifest(layout_key, nodeops.compute_id(
                self.nodes[parent_id], segment).replace(".", "/"))
        try:
            nid, path = nodeops.new_node(
                parent_id, segment, kind, self.nodes, layout_invariants=layout_inv,
                manifest=seed
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("New node", str(exc))
            return
        self.reload_and_refresh()
        self.target.set(nid)
        self._set(
            self.guidance,
            f"Created `{nid}` ({path})."
            + (f"\nSeeded {seed[0]} and declared it as this container's code -- "
               "C owns it from its first run." if seed else "")
            + "\nDescribe the intent and click 'Draft ⟶'.",
        )

    def delete_node(self) -> None:
        nid = self._target()
        if not nid or nid not in self.nodes:
            messagebox.showinfo("Delete node", "Pick an existing target node first.")
            return
        if not messagebox.askyesno("Delete node", f"Delete node '{nid}' (its SPEC.md)?"):
            return
        try:
            removed, deps = nodeops.delete_node(nid, self.nodes)
        except ValueError as exc:
            if "has children" in str(exc) and messagebox.askyesno(
                "Delete node", f"{exc}\n\nDelete the whole subtree recursively?"
            ):
                removed, deps = nodeops.delete_node(nid, self.nodes, recursive=True)
            else:
                return
        self.reload_and_refresh()
        msg = f"Removed: {removed}"
        if deps:
            msg += f"\nWARNING: still referenced by depends_on of: {deps}"
        self._set(self.guidance, msg)

    @staticmethod
    def _set(widget: ScrolledText, text: str) -> None:
        widget.configure(state="normal")  # a preview leaves the editor read-only
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    @staticmethod
    def _get(widget: ScrolledText) -> str:
        return widget.get("1.0", "end").strip()

    def _target(self) -> str:
        return self.target.get().strip()

    def show_node_tree(self) -> None:
        """Open a clickable node-link ownership graph of all loaded SPEC nodes."""
        self._reload_quiet()
        win = tk.Toplevel(self)
        win.title(f"Node Graph - {self.root_dir}")
        win.geometry("980x680")

        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(frame, background="#ffffff", highlightthickness=1,
                           highlightbackground="#d6d6d6")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        zoom_label = ttk.Label(win, font=("TkFixedFont", 9), foreground="#5f5e5a")
        self._load_graph_view()
        self._draw_node_graph(canvas)
        zoom_label.configure(text=f"{self.graph_zoom * 100:3.0f}%")

        # wheel: scroll; shift+wheel: scroll sideways; ctrl/cmd+wheel: zoom.
        def _wheel(event, axis="y"):
            step = -1 if event.delta > 0 else 1
            (canvas.yview_scroll if axis == "y" else canvas.xview_scroll)(step, "units")
        canvas.bind("<MouseWheel>", _wheel)
        canvas.bind("<Shift-MouseWheel>", lambda e: _wheel(e, "x"))
        for seq in ("<Control-MouseWheel>", "<Command-MouseWheel>"):
            canvas.bind(seq, lambda e: self._graph_zoom_step(
                canvas, 1.1 if e.delta > 0 else 1 / 1.1, zoom_label))

        legend = ttk.Frame(win, padding=(8, 4, 8, 0))
        legend.pack(fill="x")
        ttk.Label(legend, text="\u2500\u2500 owns", foreground="#5f5e5a",
                  font=("TkFixedFont", 9)).pack(side="left")
        ttk.Label(legend, text="\u2504\u2504\u25b6 depends_on", foreground="#c2410c",
                  font=("TkFixedFont", 9)).pack(side="left", padx=10)
        ttk.Label(legend, text="\u25a1 red = parent missing", foreground="#c0392b",
                  font=("TkFixedFont", 9)).pack(side="left")
        ttk.Label(legend, text="+n / \u2212 = collapse", foreground="#5f5e5a",
                  font=("TkFixedFont", 9)).pack(side="left", padx=10)

        buttons = ttk.Frame(win, padding=(8, 0, 8, 8))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Reload Graph",
                   command=lambda: self._reload_node_graph(canvas)).pack(side="left")
        ttk.Button(buttons, text="Expand All",
                   command=lambda: self._graph_expand_all(canvas)).pack(side="left", padx=4)
        ttk.Button(buttons, text="Collapse All",
                   command=lambda: self._graph_collapse_all(canvas)).pack(side="left")
        ttk.Button(buttons, text="\u2212", width=3,
                   command=lambda: self._graph_zoom_step(canvas, 1 / 1.25, zoom_label)
                   ).pack(side="left", padx=(12, 0))
        zoom_label.pack(in_=buttons, side="left", padx=3)
        ttk.Button(buttons, text="+", width=3,
                   command=lambda: self._graph_zoom_step(canvas, 1.25, zoom_label)
                   ).pack(side="left")
        ttk.Button(buttons, text="Fit",
                   command=lambda: self._graph_fit(canvas, zoom_label)).pack(side="left", padx=4)
        ttk.Button(buttons, text="100%",
                   command=lambda: self._graph_zoom_to(canvas, 1.0, zoom_label)).pack(side="left")
        ttk.Button(buttons, text="Load SPEC",
                   command=self.load_spec).pack(side="left", padx=4)
        ttk.Button(buttons, text="Build Context",
                   command=self.build_ctx).pack(side="left")
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="right")

    def _reload_node_graph(self, canvas: tk.Canvas) -> None:
        self._reload_quiet()
        self._draw_node_graph(canvas)

    def _draw_node_graph(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        collapsed = self.graph_collapsed if self.graph_collapsed is not None else set()
        z = self.graph_zoom
        positions, edges = _node_graph_layout(
            self.nodes, collapsed=collapsed,
            x_gap=max(60, int(230 * z)), y_gap=max(40, int(130 * z)),
            x_origin=int(120 * z), y_origin=int(70 * z))
        box_w, box_h = max(40, int(170 * z)), max(18, int(54 * z))
        if not positions:
            canvas.create_text(40, 40, anchor="nw", text="No SPEC nodes loaded.", fill="#5f5e5a")
            canvas.configure(scrollregion=(0, 0, 400, 240))
            return

        orphans = _orphan_nodes(self.nodes)
        waiting = inbox.awaiting(self.nodes, self.root_dir)
        hidden = _hidden_counts(self.nodes, positions)
        line_w = max(1, int(round(2 * z)))

        # ownership = solid (the tree); dependency = dashed + arrow (the DAG).
        for parent, child in edges:
            x1, y1 = positions[parent]
            x2, y2 = positions[child]
            canvas.create_line(x1, y1 + box_h // 2, x2, y2 - box_h // 2,
                               fill="#8a8a8a", width=line_w)
        arrow = (max(6, int(10 * z)), max(7, int(12 * z)), max(3, int(4 * z)))
        for src, dst in _dependency_edges(self.nodes, positions):
            x1, y1 = positions[src]
            x2, y2 = positions[dst]
            ax, ay = _box_exit(x1, y1, x2, y2, box_w, box_h)
            bx, by = _box_exit(x2, y2, x1, y1, box_w, box_h)
            canvas.create_line(ax, ay, bx, by, fill="#c2410c", width=line_w, dash=(5, 3),
                               arrow="last", arrowshape=arrow)

        current = self._target()
        for nid, (x, y) in positions.items():
            self._draw_graph_node(canvas, nid, x, y, box_w, box_h,
                                  selected=(nid == current),
                                  orphan=(nid in orphans),
                                  awaiting=(nid in waiting),
                                  hidden=hidden.get(nid, 0))

        max_x = max(x for x, _ in positions.values()) + box_w
        max_y = max(y for _, y in positions.values()) + box_h
        canvas.configure(scrollregion=(0, 0, max(960, max_x + 80), max(640, max_y + 80)))

    def _draw_graph_node(
        self,
        canvas: tk.Canvas,
        nid: str,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        selected: bool = False,
        orphan: bool = False,
        hidden: int = 0,
        awaiting: bool = False,
    ) -> None:
        node = self.nodes[nid]
        z = self.graph_zoom
        x0, y0 = x - width // 2, y - height // 2
        x1, y1 = x + width // 2, y + height // 2
        fill = _node_fill(node.get("kind", ""))
        if selected:
            outline, line_w = "#0b5fff", max(2, int(round(3 * z)))
        elif orphan:
            outline, line_w = "#c0392b", max(2, int(round(3 * z)))
        elif awaiting:
            # amber: a request on this node waits for H (see the Requests window)
            outline, line_w = "#d97706", max(2, int(round(3 * z)))
        else:
            outline, line_w = "#2f3337", 1
        tag = f"node::{nid}"
        items = [canvas.create_rectangle(
            x0, y0, x1, y1, fill=fill, outline=outline, width=line_w, tags=(tag, "node")
        )]
        title_font = _scaled_font(MONO, z)
        show_subtitle = z >= 0.7  # below that the box has no room for a second line
        items.append(canvas.create_text(
            x, y - (9 * z if show_subtitle else 0), font=title_font,
            text=_fit_label(nid, width - int(8 * z), title_font[1]),
            fill="#111111", tags=(tag, "node")))
        if show_subtitle:
            if orphan:
                detail, detail_fill = f"parent '{node.get('parent')}' missing", "#c0392b"
            else:
                detail = f"{node.get('kind', '?')}  |  {node.get('status', '?')}"
                detail_fill = "#444444"
            sub_font = _scaled_font(("TkFixedFont", 10), z)
            items.append(canvas.create_text(
                x, y + 12 * z, text=_fit_label(detail, width - int(8 * z), sub_font[1]),
                fill=detail_fill, font=sub_font, tags=(tag, "node")))
        for item in items:
            canvas.tag_bind(item, "<Button-1>", lambda _e, node_id=nid, c=canvas:
                            self._graph_select(c, node_id))
            canvas.tag_bind(item, "<Double-1>", lambda _e, node_id=nid, c=canvas:
                            self._graph_open(c, node_id))

        # collapse badge: "+n" hides n descendants, "-" is an expanded parent.
        if not _node_tree_children(self.nodes).get(nid):
            return
        label = f"+{hidden}" if hidden else "\u2212"
        badge_font = _scaled_font(("TkFixedFont", 9), z)
        pad = max(2, int(4 * z))
        bx1, by1 = x1 - pad, y1 - pad
        bx0 = bx1 - max(12, int((26 if hidden else 18) * z))
        by0 = by1 - max(10, int(15 * z))
        badge = canvas.create_rectangle(bx0, by0, bx1, by1, fill="#ffffff",
                                        outline="#6b7280", width=1)
        badge_text = canvas.create_text((bx0 + bx1) // 2, (by0 + by1) // 2, text=label,
                                        fill="#374151", font=badge_font)
        for item in (badge, badge_text):
            canvas.tag_bind(item, "<Button-1>", lambda _e, node_id=nid, c=canvas:
                            self._graph_toggle(c, node_id))

    def _graph_toggle(self, canvas: tk.Canvas, nid: str) -> None:
        """Collapse/expand one subtree. Selection is kept; state is remembered."""
        if self.graph_collapsed is None:
            self.graph_collapsed = _default_collapsed(self.nodes)
        self.graph_collapsed.symmetric_difference_update({nid})
        self._draw_node_graph(canvas)
        self._save_graph_view()

    def _graph_collapse_all(self, canvas: tk.Canvas) -> None:
        children = _node_tree_children(self.nodes)
        self.graph_collapsed = {nid for nid in self.nodes if children.get(nid)}
        self._draw_node_graph(canvas)
        self._save_graph_view()

    def _graph_expand_all(self, canvas: tk.Canvas) -> None:
        self.graph_collapsed = set()
        self._draw_node_graph(canvas)
        self._save_graph_view()

    # ---- zoom ------------------------------------------------------------
    def _graph_zoom_to(self, canvas: tk.Canvas, zoom: float,
                       label: ttk.Label | None = None) -> None:
        self.graph_zoom = min(max(zoom, appconfig.ZOOM_MIN), appconfig.ZOOM_MAX)
        self._draw_node_graph(canvas)
        if label is not None:
            label.configure(text=f"{self.graph_zoom * 100:3.0f}%")
        self._save_graph_view()

    def _graph_zoom_step(self, canvas: tk.Canvas, factor: float,
                         label: ttk.Label | None = None) -> None:
        self._graph_zoom_to(canvas, self.graph_zoom * factor, label)

    def _graph_fit(self, canvas: tk.Canvas, label: ttk.Label | None = None) -> None:
        """Zoom so the whole graph fits the window. Never magnifies past 100% --
        'fit' on a two-node graph should not blow the boxes up."""
        collapsed = self.graph_collapsed if self.graph_collapsed is not None else set()
        positions, _ = _node_graph_layout(self.nodes, collapsed=collapsed)  # 1.0 metrics
        if not positions:
            return
        need_w = max(x for x, _ in positions.values()) + 170 + 80
        need_h = max(y for _, y in positions.values()) + 54 + 80
        canvas.update_idletasks()
        avail_w, avail_h = _widget_size(canvas)
        self._graph_zoom_to(canvas, min(avail_w / need_w, avail_h / need_h, 1.0), label)

    def _save_graph_view(self) -> None:
        """Remember collapse state + zoom for THIS spec root (cockpit.json)."""
        if self.graph_collapsed is None:
            return
        appconfig.graph_view_set(self.config_data, self.root_dir,
                                 self.graph_collapsed, self.graph_zoom)
        self._save_config()

    def _load_graph_view(self) -> None:
        """Restore the view for the current root; default-collapse a new one."""
        if self._graph_root == self.root_dir:
            return  # already loaded in this session
        collapsed, zoom = appconfig.graph_view_get(self.config_data, self.root_dir)
        known = set(self.nodes)
        self.graph_collapsed = (collapsed & known if collapsed is not None
                                else _default_collapsed(self.nodes))
        self.graph_zoom = zoom
        self._graph_root = self.root_dir

    def _graph_select(self, canvas: tk.Canvas, nid: str) -> None:
        self.target.set(nid)
        self._draw_node_graph(canvas)
        self._set(
            self.guidance,
            f"Selected node `{nid}` from graph. Double-click to load its SPEC.md.",
        )

    def _graph_open(self, canvas: tk.Canvas, nid: str) -> None:
        self._graph_select(canvas, nid)
        self.load_spec()

    # ---- actions ---------------------------------------------------------
    @staticmethod
    def _has_substance(node: dict) -> bool:
        """Would a fresh draft LOSE something? True once the node says anything of
        its own -- a contract entry, a code glob. A skeleton from New Node says
        nothing (`provides: []`), and asking about that would train the answer."""
        contract = node.get("contract")
        filled = any(v for v in contract.values()) if isinstance(contract, dict) else bool(contract)
        return bool(filled or node.get("code"))

    def draft(self) -> None:
        if self._run_busy("Draft"):
            return
        intent = self._get(self.input)
        if not intent:
            self._set(self.guidance, "Enter an intent first.")
            return
        nid = self._target() or "new.node"
        n = self.nodes.get(nid, {})
        parent = n.get("parent", "")
        kind = n.get("kind", "component")
        # `cli.py draft` refuses an existing node outright ("change its spec with
        # revise"); here a person may legitimately want to start over. But Draft
        # REGENERATES: the layout invariants an archetype seeded into a container,
        # or anything already written, would be gone on Save -- silently, while a
        # project is young and nothing is accepted yet.
        if self._has_substance(n) and not messagebox.askyesno(
                "Draft over an existing spec?",
                f"`{nid}` already has a contract of its own.\n\n"
                "Draft writes a NEW spec from your intent: whatever is there now -- a "
                "container's code-layout invariants, promises, code globs -- is "
                "replaced.\n\nRevise keeps what your change does not touch.\n\n"
                "Draft anyway?", default=messagebox.NO):
            self._set(self.guidance,
                      f"Kept the spec of `{nid}`. Use 'Revise ->' to change it: say what "
                      "this change adds, and P keeps the rest.")
            return
        try:
            spec = planner.draft_spec(
                intent, nid, parent, kind, self._spine(parent),
                architecture=self.arch, model=llm.planner_model(),
                capabilities=capability.build_registry(self.nodes),
                targets=self._request_targets(),
            )
        except RuntimeError as exc:
            self._set(self.guidance, f"Draft unavailable:\n{exc}")
            return
        self._last_intent = (nid, "drafted", intent)   # recorded if it is saved
        self._set(self.view, spec)
        guidance = (
            f"AI draft for `{nid}` is in the editor. Review the contract lines, "
            "then 'Save'."
        )
        # search-before-build: warn if this intent matches an existing capability
        reranker, _ = self._semantic()
        hits = capability.find(capability.build_registry(self.nodes), intent, reranker=reranker)
        hits = [h for h in hits if h["capability"]["node"] != nid and h["score"] >= 0.2]
        if hits:
            top = ", ".join(f"{h['capability']['node']} ({h['score']:.2f})" for h in hits[:3])
            guidance += (
                f"\n\nREUSE? This intent resembles existing capabilities: {top}.\n"
                "Consider 'Registry > Find Capability' and depends_on instead of duplicating."
            )
        assessed = self._assess(nid, spec)
        if assessed:
            guidance += "\n\n" + changeset.report(*assessed)
        # H' draft review at the SOFT gate (draft gate D1+).
        level = self.config_data.get("draft_gate", 1)
        if level >= 1:
            # The draft just came from the same key and provider, so a missing
            # review is never "feature off" here -- say so instead of nothing.
            try:
                review, missing = self._review(intent, spec), "H' gave no usable answer"
            except Exception as exc:  # noqa: BLE001 -- advisory: never lose the draft
                review, missing = None, f"H' review unavailable: {exc}"
            if review:
                if level >= 2:  # D2: H' may auto-clear the gate (or escalate)
                    self._set(self.guidance, self._d2_draft(intent, nid, spec, review))
                    return
                guidance += "\n\n" + self._format_review(review) + self._independence_note()  # D1: advisory
            else:
                guidance += (f"\n\n{missing}. The draft is unreviewed"
                             + (" and D2 did not run" if level >= 2 else "")
                             + " -- review it yourself before Save.")
        self._set(self.guidance, guidance)

    def _review(self, intent: str, spec: str) -> dict | None:
        return reviewer.review_draft(
            intent, spec, architecture=self.arch,
            registry=capability.build_registry(self.nodes),
            model=self._reviewer_model(),
        )

    def _request_targets(self) -> set[str]:
        """What a decision request may point at here: ARCHITECTURE.md or a node
        that exists (engine/decisions)."""
        from engine import decisions
        return set(self.nodes) | {decisions.ARCHITECTURE}

    def _spine(self, parent: str | None) -> dict:
        """The contracts from the root down to `parent`: the planner needs the
        container's code layout, which lives there."""
        if not parent or parent not in self.nodes:
            return {}
        return {a: self.nodes[a].get("contract") for a in graph.spine(self.nodes, parent)}

    def _record_intent(self, nid: str, gate: str | None) -> None:
        """A saved spec is a growth step: record the intent it came from
        (engine/intents.py). A draft that is never saved is not one."""
        last = getattr(self, "_last_intent", None)
        if last and last[0] == nid:
            intents.record(self.root_dir, nid, last[1], last[2],
                           by=llm.planner_model(), gate=gate)
            self._last_intent = None

    def _reviewer_model(self) -> str:
        """The reviewer's model (SGE_REVIEWER_MODEL in cockpit/.env)."""
        return llm.reviewer_model()

    def _independence_note(self) -> str:
        """Said wherever a review is shown: a review by the model that wrote the
        draft is a second pass, not a second opinion."""
        if self._reviewer_model() != llm.planner_model():
            return ""
        return (f"\n  (H' reviewed with {self._reviewer_model()}, the model that drafted "
                "it -- not an independent review. Give SGE_REVIEWER_* in cockpit/.env "
                "another model.)")

    def _assess(self, nid: str, text: str) -> tuple[dict, dict] | None:
        """Change set + consumer impact of saving `text` as nid's SPEC.md
        (AUTONOMY.md 5a), measured against the ACCEPTED state when the project
        tracks one -- so a HARD change an agent left pending is part of what H
        is asked about -- else against the file on disk. None if the text does
        not parse even after repair."""
        repaired, _fixes = specfix.repair_frontmatter(text)
        try:
            before = accepted.before(self.root_dir)
        except accepted.Unreadable:
            before = None   # Validate reports it; the disk is the next best basis
        return changeset.assess(self.nodes, self.root_dir, nid, repaired, before=before)

    def _record_accepted(self, nid: str, by: str, actor: str = "H") -> str:
        """Record nid's saved spec as accepted, when the project tracks a state.
        Returns a guidance line ('' when untracked)."""
        if not accepted.tracked(self.root_dir):
            return ""
        try:
            accepted.accept(self.nodes, self.root_dir, [nid], by=by, actor=actor)
        except (ValueError, accepted.Unreadable) as exc:
            return f"\nNOT recorded as accepted: {exc}"
        return f"\nRecorded as accepted by {actor} ({by})."

    def _d2_draft(self, intent: str, nid: str, spec: str, review: dict) -> str:
        """D2 in the cockpit: engine.autonomy.clear_draft decides (with the planner,
        the reviewer and the change set injected), this method applies the outcome.
        approve -> auto-save (the deterministic gate still runs); revise -> the
        planner applies the findings and H' re-reviews (bounded); a HARD change set,
        reject, low confidence or a declared protected zone -> escalate to the human."""
        def revise(text: str, instruction: str) -> str:
            return planner.revise_spec(text, instruction, architecture=self.arch,
                                       model=llm.planner_model(),
                                       spine=self._spine(self.nodes.get(nid, {}).get("parent")),
                                       consumers=nodeops.dependents_of(self.nodes, nid),
                                       targets=self._request_targets())

        out = autonomy.clear_draft(
            spec, review,
            assess=lambda text: self._assess(nid, text),
            revise=revise,
            rereview=lambda text: self._review(intent, text),
            on_revision=lambda text: self._set(self.view, text),
        )
        change = out["change"]
        gate = change["gate"] if change else None
        if out["action"] == "accept":
            return self._d2_accept(nid, out["spec"], out["review"], out["rounds"], gate=gate)
        show = bool(change) and (gate == "HARD" or change.get("protected"))
        detail = changeset.report(change, out["reach"]) if show else ""
        return self._d2_escalate(nid, out["spec"], out["review"], out["reason"],
                                 gate=gate, detail=detail)

    def _d2_accept(self, nid: str, spec: str, review: dict, rounds: int,
                   gate: str | None = None) -> str:
        self._set(self.view, spec)
        path, _fixes, _ = self._persist_spec(nid, spec)
        self._record_intent(nid, gate)
        report = validate.run(self.nodes, self.root_dir)
        blocked = "gate: BLOCK" in report
        if not blocked:   # like E on the CLI: only a passing gate clears
            self._record_accepted(nid, by=self._reviewer_model(), actor="H'")
        lifecycle.log_autonomy(self.root_dir, {
            "node": nid, "draft_gate": 2, "verdict": review.get("verdict"),
            "confidence": review.get("confidence"), "revise_rounds": rounds, "gate": gate,
            "action": "auto-saved-blocked" if blocked else "auto-saved",
        })
        conf = review.get("confidence") or 0.0
        if blocked:
            hard = "\n".join(ln for ln in report.splitlines() if ln.strip().startswith("[x]"))
            self._set(self.view, report)
            return (f"D2: H' approved & auto-saved {path}, BUT the deterministic gate "
                    f"BLOCKS (the hard floor wins -- fix needed):\n{hard}")
        return (f"D2: H' approved (confidence {conf:.2f}, {rounds} revise round(s)) "
                f"-> auto-saved {path}. Deterministic gate: pass. "
                "Next: 'Codex' (the context is built automatically)."
                + self._independence_note())

    def _d2_escalate(self, nid: str, spec: str, review: dict, reason: str,
                     gate: str | None = None, detail: str = "") -> str:
        self._set(self.view, spec)
        lifecycle.log_autonomy(self.root_dir, {
            "node": nid, "draft_gate": 2, "verdict": review.get("verdict"),
            "confidence": review.get("confidence"), "gate": gate,
            "action": "escalated", "reason": reason,
        })
        detail = f"{detail}\n\n" if detail else ""
        return (f"D2 -> ESCALATED to you: {reason}.\n\n{detail}{self._format_review(review)}"
                f"{self._independence_note()}\n"
                "Review the draft in the editor and Save manually.")

    @staticmethod
    def _format_review(review: dict) -> str:
        conf = review.get("confidence")
        head = f"H' review: {review.get('verdict', '?').upper()}"
        if isinstance(conf, (int, float)):
            head += f" (confidence {conf:.2f})"
        lines = [head]
        for f in review.get("findings", []):
            mark = "[!]" if f.get("severity") == "blocker" else "[-]"
            area = f"{f['area']}: " if f.get("area") else ""
            lines.append(f"  {mark} {area}{f['message']}")
        if not review.get("findings"):
            lines.append("  (no findings)")
        lines.append("  (advisory -- the deterministic gate still runs on Validate/Drift.)")
        return "\n".join(lines)

    def revise(self) -> None:
        """Edit the target node's EXISTING spec with the AI: the current SPEC.md is
        transported in, the Intent box holds the change request, status is preserved."""
        if self._run_busy("Revise"):
            return
        nid = self._target()
        if not nid or nid not in self.nodes:
            self._set(self.guidance, "Pick an existing target node to revise.")
            return
        instruction = self._get(self.input)
        if not instruction:
            self._set(self.guidance, "Describe the change in the box, then '<- Revise'.")
            return
        path = self.nodes[nid].get("_path")
        try:
            current = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self._set(self.guidance, f"Cannot read current SPEC.md: {exc}")
            return
        try:
            spec = planner.revise_spec(
                current, instruction,
                architecture=self.arch, model=llm.planner_model(),
                spine=self._spine(self.nodes[nid].get("parent")),
                consumers=nodeops.dependents_of(self.nodes, nid),
                targets=self._request_targets(),
            )
        except RuntimeError as exc:
            self._set(self.guidance, f"Revise unavailable:\n{exc}")
            return
        self._last_intent = (nid, "revised", instruction)   # recorded if it is saved
        self._set(self.view, spec)
        assessed = self._assess(nid, spec)
        self._set(
            self.guidance,
            f"Revised draft for `{nid}` is in the editor (status preserved). Review the "
            "diff against the current spec, then 'Save'. Then Validate / Drift."
            + ("\n\n" + changeset.report(*assessed) if assessed else ""),
        )

    def load_arch(self) -> None:
        path = Path(self.root_dir) / parser.ARCH_NAME
        text = path.read_text(encoding="utf-8") if path.exists() else (
            "# Architecture (cross-cutting)\n\n"
            "## Invariants (apply everywhere)\n"
            "- Implementation language: Python 3 (stdlib only).\n\n"
            "## Decisions (ADRs)\n- TODO\n"
        )
        self._set(self.view, text)
        self._set(self.guidance, f"Editing {path}.\nChange it, then 'Save ARCH'.")

    def save_arch(self) -> None:
        text = self._get(self.view)
        if not text:
            self._set(self.guidance, "Editor is empty - nothing to save.")
            return
        if _looks_like_spec(text):  # guard: that's a SPEC, not ARCHITECTURE.md
            if not messagebox.askyesno(
                "Save ARCH",
                "The editor content looks like a SPEC.md (has 'id:' frontmatter). "
                "Overwrite ARCHITECTURE.md with it anyway?",
            ):
                return
        path = Path(self.root_dir) / parser.ARCH_NAME
        path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
        self.reload_nodes()  # refresh self.arch
        self._set(self.guidance, f"Wrote {path}.\nThe invariants now feed every Spine bundle.")

    def load_spec(self) -> None:
        nid = self._target()
        if not nid or nid not in self.nodes:
            self._set(self.guidance, "Pick an existing target node first.")
            return
        path = self.nodes[nid]["_path"]
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self._set(self.guidance, f"Load SPEC failed: {exc}")
            return
        self._set(self.view, text)
        self._set(
            self.guidance,
            f"Loaded {path} into the editor.\nEdit it, then 'Save'.",
        )

    def _unsaved_spec(self) -> str:
        """The id of the spec in the editor when its SPEC.md does not hold it -- a
        draft or a revision nobody saved, or a hand edit. "" when there is nothing
        to lose: an empty editor, a bundle, a report, or a spec as it is on disk."""
        text = self._get(self.view)
        nid = _spec_id(text)
        if not nid:
            return ""
        node = self.nodes.get(nid)
        try:
            on_disk = Path(node["_path"]).read_text(encoding="utf-8") if node else ""
        except OSError:
            on_disk = ""
        return "" if on_disk.strip() == text else nid

    def _target_picked(self) -> None:
        """A node picked in the Target box: load its SPEC.md -- but not over a spec
        nobody saved without asking; the draft would be gone."""
        nid = self._target()
        unsaved = self._unsaved_spec()
        if unsaved and not messagebox.askyesno(
                "Unsaved spec",
                f"The editor holds a spec of {unsaved} that is not saved.\n\n"
                f"Load {nid}'s SPEC.md and discard it?"):
            if unsaved in self.nodes:
                self.target.set(unsaved)  # back to the node the draft belongs to
            self._set(self.guidance,
                      f"Kept the unsaved spec of {unsaved} in the editor; the target is "
                      f"{self._target() or 'unset'}.\n'Save' writes it there.")
            return
        self.load_spec()

    def save_spec(self) -> None:
        nid = self._target()
        text = self._get(self.view)
        if not (nid and text):
            self._set(self.guidance, "Need a target node and editor content.")
            return
        if not _looks_like_spec(text):  # guard: don't clobber a SPEC with non-SPEC text
            if not messagebox.askyesno(
                "Save -> SPEC.md",
                f"The editor content has no 'id:' frontmatter and does not look like a "
                f"SPEC.md. Overwrite {nid}'s SPEC.md anyway?",
            ):
                return
        assessed = self._assess(nid, text)
        if assessed and assessed[0]["gate"] == "HARD":
            basis = ("the ACCEPTED state (it includes changes nobody has accepted yet)"
                     if accepted.tracked(self.root_dir) else "the file on disk")
            if not messagebox.askyesno(
                "Save -> SPEC.md: HARD gate",
                f"{changeset.report(*assessed)}\n\nMeasured against {basis}. This change "
                "is a HARD gate: it needs your approval. Save it?",
            ):
                self._set(self.guidance, "Not saved.\n\n" + changeset.report(*assessed))
                return
        path, fixes, repaired = self._persist_spec(nid, text)
        self._record_intent(nid, assessed[0]["gate"] if assessed else None)
        msg = f"Wrote {path}\nNext: 'Codex' (the context is built automatically)."
        if fixes:
            self._set(self.view, repaired)  # reflect the repaired text back into the editor
            quoted = "\n".join(f"  line {ln}: {c}" for ln, c in fixes)
            msg = (f"Wrote {path}\nAuto-quoted {len(fixes)} YAML line(s) (colon/backtick "
                   f"in an unquoted scalar):\n{quoted}\n"
                   "Next: 'Codex' (the context is built automatically).")
        if assessed:
            msg += "\n" + changeset.summary(assessed[0])
            msg += self._record_accepted(nid, by=getpass.getuser())
        self._set(self.guidance, msg)

    def _persist_spec(self, nid: str, text: str):
        """Repair YAML, write the node's SPEC.md, reload nodes. Returns (path, fixes,
        final_text). No guidance side effects -- shared by Save and D2 auto-accept."""
        text, fixes = specfix.repair_frontmatter(text)
        node = self.nodes.get(nid)
        path = Path(node["_path"]) if node else Path(self.root_dir) / nid.replace(".", "/") / "SPEC.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
        self.reload_nodes()
        self.target["values"] = sorted(self.nodes)
        return path, fixes, text

    def build_ctx(self) -> None:
        nid = self._target()
        if not nid:
            self._set(self.guidance, "Pick a target node.")
            return
        bundle = self._context_bundle(nid)
        if bundle is None:
            return
        self._preview(bundle)
        self._set(self.guidance,
                  f"Context bundle for `{nid}` -- a preview, read-only: what 'Codex' gives "
                  "C, built again from the saved specs when you press it. To change what C "
                  "gets, change the spec (or ARCHITECTURE.md) and save.")

    def _preview(self, text: str) -> None:
        """Show text that is not for editing -- an edit would go nowhere. Anything
        written to the editor after it (a spec loaded, a draft) makes it writable."""
        self._set(self.view, text)
        self.view.configure(state="disabled")

    def _context_bundle(self, nid: str) -> str | None:
        """Context(N) from what is on disk; None, said in Guidance, if it fails."""
        self._reload_quiet()  # reflect on-disk truth (coder / external edits)
        try:
            return context.assemble(self.nodes, self.arch, nid, self.root_dir)
        except Exception as exc:  # surface, never fail silently
            self._set(self.guidance, f"Build context FAILED: {type(exc).__name__}: {exc}")
            return None

    def run_validate(self) -> None:
        self._reload_quiet()  # reflect on-disk truth (coder / external edits)
        try:
            report = validate.run(self.nodes, self.root_dir)
        except Exception as exc:
            self._set(self.guidance, f"Validate FAILED: {type(exc).__name__}: {exc}")
            return
        self._set(self.view, report)
        waiting = inbox.pending(self.nodes, self.root_dir)
        if waiting:
            self._set(self.guidance,
                      f"Structure validated -- but {len(waiting)} request(s) await YOUR "
                      "decision. Open 'Requests' to grant, accept or reject them.")
        else:
            self._set(self.guidance, "Structure validated (spec-side intent graph).")

    def run_drift(self) -> None:
        self._reload_quiet()  # reflect on-disk truth (coder / external edits)
        try:
            report = drift.run(self.nodes, self.root_dir)
        except Exception as exc:
            self._set(self.guidance, f"Drift FAILED: {type(exc).__name__}: {exc}")
            return
        self._set(self.view, report)
        self._set(self.guidance, "Code drift checked (evidence graph vs declared deps).")

    # ---- capability registry (horizontal reuse axis) --------------------
    def _semantic(self):
        """Build the reranker+judge (the planner's model) if enabled and configured.
        Returns (reranker, judge); either may be None -> lexical fallback."""
        if not self.config_data.get("semantic_match"):
            return None, None
        model = llm.planner_model()
        try:
            return semantic.make_reranker(model), semantic.make_judge(model)
        except Exception:
            return None, None

    def show_requests(self) -> None:
        """H's inbox: requested waivers, decision requests and pending HARD changes,
        with the actions that resolve them. The channel back to agents -- before
        this, H had to press Validate, spot the warnings, and hand-edit YAML.
        A HARD change comes with a brief from H' (Prepare); Accept / Reject record
        whether H followed it (engine/assist.py)."""
        import datetime as _dt
        from tkinter import simpledialog

        self._reload_quiet()
        win = tk.Toplevel(self)
        win.title(f"Requests awaiting your decision - {self.root_dir}")
        win.geometry("1000x580")
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)

        cols = ("type", "node", "subject")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=8, selectmode="browse")
        for col, width in (("type", 90), ("node", 240), ("subject", 300)):
            tree.heading(col, text=col)
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="x")
        detail = ScrolledText(frame, height=12, wrap="word", font=MONO)
        detail.pack(fill="both", expand=True, pady=(8, 0))
        status = ttk.Label(frame, text="", foreground="#5f5e5a")
        status.pack(fill="x", pady=(4, 0))

        bar = ttk.Frame(win, padding=(8, 0, 8, 8))
        bar.pack(fill="x")
        items: list[dict] = []

        def current() -> dict | None:
            sel = tree.selection()
            return items[int(sel[0])] if sel else None

        def run(action, done: str) -> None:
            if self._run_busy("Deciding now", parent=win):
                return
            try:
                action()
            except ValueError as exc:
                messagebox.showerror("Not done", str(exc), parent=win)
                refresh()
                return
            refresh(done)
            self._set(self.guidance, done)

        def grant() -> None:
            it = current()
            owner = simpledialog.askstring(
                "Grant waiver", f"Owner of the waiver on {it['node']}\n"
                "(the person accepting the risk):",
                initialvalue=getpass.getuser(), parent=win)
            if owner is None:
                return
            default = it.get("proposed_expiry") or \
                (_dt.date.today() + _dt.timedelta(days=90)).isoformat()
            expires = simpledialog.askstring(
                "Grant waiver", "Expires (YYYY-MM-DD) -- after that it blocks the gate:",
                initialvalue=default, parent=win)
            if expires is None:
                return
            run(lambda: inbox.grant_waiver(self.nodes, it["node"], owner, expires),
                f"Granted the waiver on {it['node']} to {owner} until {expires}.")

        def accept() -> None:
            it = current()
            if not messagebox.askyesno(
                    "Accept decision",
                    f"Record this as a dated ADR in ARCHITECTURE.md and remove the "
                    f"request from {it['node']}?\n\n{it['text']}", parent=win):
                return
            run(lambda: inbox.accept_decision(self.nodes, self.root_dir, it["node"],
                                              it["index"], it["text"]),
                f"Accepted: ADR recorded in ARCHITECTURE.md, request removed from {it['node']}.")

        def open_target() -> None:
            it = current()
            if it["subject"] not in self.nodes:
                return
            self.target.set(it["subject"])
            self.load_spec()
            # the change, prepared for P: Revise turns the proposal into the contract
            self._set(self.input,
                      f"Apply this decision, requested by {it['node']}: {it['text']}\n"
                      f"Reason: {it.get('reason', '')}\n"
                      "Change only what the decision requires; keep everything else.")
            self._set(self.guidance,
                      f"Proposal from {it['node']} for {it['subject']}:\n  {it['text']}\n"
                      f"Reason: {it.get('reason', '')}\n\n"
                      f"{it['subject']}'s spec is in the editor, and the change is prepared "
                      "in the Intent box. To resolve it:\n"
                      "  1. Revise ->  P rewrites the contract as the proposal says.\n"
                      "  2. Read the result and its change set; change what you mean "
                      "differently.\n"
                      "  3. Save      a container's contract is a HARD change: it asks first.\n"
                      "  4. Resolved  in the Requests window -- removes the request from "
                      f"{it['node']}.\n"
                      "Or edit the spec by hand instead of step 1. Decided against it? "
                      "Reject, in the Requests window.")

        def resolve() -> None:
            it = current()
            if not messagebox.askyesno(
                    "Resolve decision",
                    f"Have you changed {it['subject']} as you decided? This removes the "
                    f"request from {it['node']}.", parent=win):
                return
            run(lambda: inbox.resolve_decision(self.nodes, it["node"], it["index"], it["text"]),
                f"Resolved: request removed from {it['node']}.")

        def prepare() -> None:
            if self._run_busy("A brief", parent=win):
                return
            it = current()
            arch = self.arch
            model = self._reviewer_model()
            try:
                done = assist.prepare(
                    self.nodes, self.root_dir,
                    lambda report, old, cur: reviewer.brief_hard_change(
                        report, old, cur, architecture=arch, model=model),
                    only={it["node"]})
            except RuntimeError as exc:
                messagebox.showerror("Not prepared", f"H' is unavailable: {exc}\n\nYou can "
                                     "still decide without a brief.", parent=win)
                return
            if not done or done[0][1] is None:
                messagebox.showerror("Not prepared", "H' gave no usable brief. You can "
                                     "still decide without it.", parent=win)
                return
            refresh(f"H' prepared the change on {it['node']}.")

        def accept_hard() -> None:
            it = current()
            expected = {it["node"]: it["fingerprint"]} if it["fingerprint"] else None
            run(lambda: assist.decide(self.nodes, self.root_dir, [it["node"]],
                                      decision="accept", by=getpass.getuser(),
                                      expected=expected),
                (f"Confirmed what H' accepted on {it['node']}." if it["type"] == "delegated"
                 else f"Accepted the HARD change on {it['node']}."))

        def reject() -> None:
            it = current()
            if it["type"] in ("HARD", "delegated"):
                verb = "overruled" if it["type"] == "delegated" else "rejected"
                reason = simpledialog.askstring(
                    "Reject HARD change",
                    f"Why is the change on {it['node']} {verb}? The agent reads this in "
                    "the gate, which blocks until the node is restored or changed "
                    "differently.", parent=win)
                if not reason:
                    return
                expected = {it["node"]: it["fingerprint"]} if it["fingerprint"] else None
                run(lambda: assist.decide(self.nodes, self.root_dir, [it["node"]],
                                          decision="reject", by=getpass.getuser(),
                                          reason=reason, expected=expected),
                    f"{verb.capitalize()} the change on {it['node']}: {reason}")
                return
            if it["type"] == "waiver":
                if not messagebox.askyesno(
                        "Reject waiver",
                        f"Reject the waiver on {it['node']}? The node then has to meet "
                        "the rule it asked to deviate from.", parent=win):
                    return
                run(lambda: inbox.reject_waiver(self.nodes, it["node"]),
                    f"Rejected the waiver on {it['node']}.")
                return
            record = messagebox.askyesnocancel(
                "Reject decision",
                "Record the rejection as an ADR in ARCHITECTURE.md, so the next agent "
                "does not ask the same question again?", parent=win)
            if record is None:
                return
            run(lambda: inbox.reject_decision(self.nodes, self.root_dir, it["node"],
                                              it["index"], it["text"], record=record),
                f"Rejected the decision request from {it['node']}"
                + (" and recorded it as an ADR." if record else "."))

        buttons = {
            "grant": ttk.Button(bar, text="Grant...", command=grant),
            "accept": ttk.Button(bar, text="Accept (record ADR)", command=accept),
            "open": ttk.Button(bar, text="Open target", command=open_target),
            "resolve": ttk.Button(bar, text="Resolved", command=resolve),
            "prepare": ttk.Button(bar, text="Prepare (H')", command=prepare),
            "accept_hard": ttk.Button(bar, text="Accept change", command=accept_hard),
            "reject": ttk.Button(bar, text="Reject...", command=reject),
        }
        for b in buttons.values():
            b.pack(side="left", padx=(0, 4))
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")

        def on_select(_event=None) -> None:
            it = current()
            for b in buttons.values():
                b.state(["disabled"])
            if it is None:
                self._set(detail, "Select a request to see what is being asked." if items
                          else "Nothing awaits your decision.")
                return
            if it["type"] == "HARD":
                change = it["change"]
                in_scope, why = autonomy.delegable_scope(change)
                scope = f"delegable: {'yes' if in_scope else 'no'} ({why})"
                if in_scope:
                    mig = migration.check(self.nodes, self.root_dir, change)
                    scope += ("\nmigrated: yes" if mig["migrated"]
                              else "\nmigrated: no -- " + "; ".join(mig["missing"]))
                self._set(detail,
                          f"HARD CHANGE pending on {it['node']}\n\n"
                          + changeset.report(change, changeset.impact(
                              self.nodes, self.root_dir, change))
                          + f"\n\n{scope}\ndelegation: "
                          f"{'on' if autonomy.delegated(self.root_dir) else 'off'}"
                          + "\n\n" + assist.format_brief(it["brief"], stale=it["stale"])
                          + "\n\nAccept change   record it as accepted; the nodes it held"
                          "\n                may become verified again."
                          "\nReject          with a reason: the gate BLOCKS until the node is"
                          "\n                restored or changed differently.")
                enabled = ("prepare", "accept_hard", "reject") if it["brief"] is None \
                    else ("accept_hard", "reject")
            elif it["type"] == "delegated":
                rec = it["record"]
                self._set(detail,
                          f"ACCEPTED BY H' under the delegation: {it['node']}\n"
                          f"by {rec.get('by')} at {rec.get('at')}\n\n"
                          "H' accepted a breaking change inside the scope you delegated, "
                          "after E found every consumer migrated.\n\n"
                          "Accept change   confirm it: the acceptance becomes yours.\n"
                          "Reject...       overrule it, with a reason: the node's accepted "
                          "spec goes back\n                to what it was, and the gate "
                          "BLOCKS until the node is restored.")
                enabled = ("accept_hard", "reject")
            elif it["type"] == "waiver":
                self._set(detail,
                          f"WAIVER requested on {it['node']}    (kind: {it['subject']})\n"
                          f"proposed expiry: {it.get('proposed_expiry') or '-'}\n\n"
                          f"Reason:\n  {it['text']}\n\n"
                          "Grant    accept the deviation, with an owner and an expiry.\n"
                          "Reject   the node has to meet the rule.")
                enabled = ("grant", "reject")
            else:
                to_arch = it["subject"] == "ARCHITECTURE.md"
                how = ("Accept   record the proposal as a dated ADR in ARCHITECTURE.md."
                       if to_arch else
                       "Open target   load that contract, with the change prepared for\n"
                       "              Revise: P rewrites it, you check and Save -- a\n"
                       "              proposal in prose is never merged unseen.\n"
                       "Resolved      after you have saved your change.")
                self._set(detail,
                          f"DECISION requested by {it['node']}\n"
                          f"target: {it['subject']}\n\n"
                          f"Proposal:\n  {it['text']}\n\nReason:\n  {it.get('reason', '')}\n\n"
                          f"{how}\nReject   decide against it (optionally recorded as an ADR).")
                enabled = ("accept", "reject") if to_arch else ("open", "resolve", "reject")
            for key in enabled:
                buttons[key].state(["!disabled"])

        def refresh(message: str = "") -> None:
            nonlocal items
            self._reload_quiet()
            items = inbox.pending(self.nodes, self.root_dir)
            tree.delete(*tree.get_children())
            for i, it in enumerate(items):
                tree.insert("", "end", iid=str(i), values=(it["type"], it["node"], it["subject"]))
            status.configure(text=message or (f"{len(items)} request(s) await your decision."
                                              if items else "Nothing awaits your decision."))
            if items:
                tree.selection_set("0")
            on_select()

        tree.bind("<<TreeviewSelect>>", on_select)
        refresh()

    def _report_window(self, title: str, text: str) -> None:
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("820x520")
        out = ScrolledText(win, font=MONO, wrap="word")
        out.pack(fill="both", expand=True)
        ttk.Button(win, text="Close", command=win.destroy).pack(anchor="e", padx=4, pady=4)
        out.insert("end", text)

    def find_capability(self) -> None:
        """Search-before-build: query existing capabilities before creating one."""
        from tkinter import simpledialog
        seed = self._get(self.input) or ""
        query = simpledialog.askstring(
            "Find capability", "Describe the capability you need:",
            initialvalue=seed.splitlines()[0] if seed else "", parent=self)
        if not query:
            return
        reg = capability.build_registry(self.nodes)
        reranker, _ = self._semantic()
        hits = capability.find(reg, query, reranker=reranker)
        if not hits:
            self._report_window(
                f"Find capability: {query}",
                f"No existing capability matches '{query}'.\n\n"
                "-> No match: create it as a SHARED node so the next slice finds it.\n"
                "   (Mark the node `shared: true` in its SPEC.md frontmatter.)\n")
            return
        mode = "semantic+lexical" if any("semantic" in h for h in hits) else "lexical"
        lines = [f"Capabilities matching '{query}'  ({mode}):\n"]
        for h in hits:
            c = h["capability"]
            tag = " [shared]" if c["shared"] else ""
            detail = f"  (lex {h.get('lexical', 0):.2f}"
            detail += f", sem {h['semantic']:.2f})" if "semantic" in h else ")"
            lines.append(f"  {h['score']:.2f}  {c['id']}  (node: {c['node']}{tag}){detail}")
            lines.append(f"        role: {c['role']}")
            lines.append(f"        provides: {', '.join(c['provides'])}\n")
        lines.append("-> Match found: REUSE it via `depends_on: [" + hits[0]["capability"]["node"] + "]`")
        lines.append("   instead of building a duplicate.")
        self._report_window(f"Find capability: {query}", "\n".join(lines))

    def show_duplicates(self) -> None:
        """Duplicate detector: surface probable duplicate capabilities."""
        _, judge = self._semantic()
        try:
            dups = capability.duplicates(self.nodes, self.root_dir, judge=judge)
        except Exception as exc:
            self._set(self.guidance, f"Duplicates FAILED: {type(exc).__name__}: {exc}")
            return
        if not dups:
            self._report_window("Capability duplicates",
                                "No probable duplicate capabilities found.\n")
            self._set(self.guidance, "Duplicate scan: clean.")
            return
        mode = "semantic-confirmed" if any("semantic" in d for d in dups) else "lexical"
        lines = [f"Probable duplicate capabilities ({mode}; consolidate on 2nd occurrence):\n"]
        for d in dups:
            verdict = ""
            if "semantic" in d:
                same = d["semantic"]["same"]
                verdict = "  [LLM: SAME]" if same else "  [LLM: similar, NOT same]"
            lines.append(
                f"  [{d['confidence'].upper()}  {d['score']:.2f}]  {d['a']}  ~  {d['b']}{verdict}")
            for r in d["reasons"]:
                lines.append(f"        - {r}")
            lines.append("")
        lines.append("Consolidation: choose/create a SHARED node with the union contract,")
        lines.append("migrate consumers to depend_on it, remove the duplicate implementation.")
        self._report_window("Capability duplicates", "\n".join(lines))
        self._set(self.guidance, f"Found {len(dups)} probable duplicate(s) - see report window.")

    def claim_capability(self) -> None:
        """Register an intent-level claim; detect concurrent-capability-creation."""
        from tkinter import simpledialog
        cap_id = simpledialog.askstring(
            "Claim capability", "Capability id (e.g. cap:pdf-to-text):", parent=self)
        if not cap_id:
            return
        sketch = simpledialog.askstring(
            "Claim capability", "Contract sketch (e.g. path -> Text):", parent=self) or ""
        owner = self._target() or "unassigned"
        claim, conflicts = capability.add_claim(
            self.root_dir, cap_id, sketch, owner=owner, nodes=self.nodes)
        lines = [f"Claim registered: {claim['id']}  (owner: {claim['owner']})\n"]
        if conflicts:
            lines.append("!! CONCURRENT-CAPABILITY-CREATION - coordinate before building:\n")
            for c in conflicts:
                w = c["with"]
                who = w.get("owner") or w.get("node")
                lines.append(f"  ~ {c['similarity']:.2f}  {w['id']}  ({c['kind']}: {who})")
            lines.append("\n-> One side builds the SHARED node; the other depends_on it.")
        else:
            lines.append("No conflict: you are the first to claim this capability.")
        self._report_window(f"Claim: {cap_id}", "\n".join(lines))
        self._set(self.guidance,
                  f"Claim '{cap_id}' registered ({len(conflicts)} conflict(s)).")

    def generate_index(self) -> None:
        """Generate project.index.json (spec graph + capabilities + edges + evidence)."""
        self._reload_quiet()
        try:
            path = index_mod.write_index(self.root_dir)
        except Exception as exc:
            self._set(self.guidance, f"Generate index FAILED: {type(exc).__name__}: {exc}")
            return
        self._set(self.guidance, f"Wrote {path}\n(spec graph + capabilities + edges + test evidence).")

    def install_git_hook(self) -> None:
        """Wire .git/hooks/pre-commit to the offline gate for the current root."""
        import io
        import contextlib
        import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.cmd_install_hook(self.root_dir, force=False)
        out = buf.getvalue().strip()
        if code != 0 and "not ours" in out:
            if messagebox.askyesno("Install git hook", out + "\n\nOverwrite it?"):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    code = cli.cmd_install_hook(self.root_dir, force=True)
                out = buf.getvalue().strip()
        (messagebox.showinfo if code == 0 else messagebox.showerror)("Install git hook", out)
        self._set(self.guidance, out)

    # ---- a run: the third switch (AUTONOMY.md), started here ------------
    _RUN_ENDED = {
        "done": "The goal is met, as far as E and H' can tell: a green floor, no gap, "
                "and nothing waiting for you.",
        "asking": "Something waits for YOU: the floor is green, but the graph carries an "
                  "open decision request, or the task rests on a decision only you may "
                  "make. It is in Requests.",
        "blocked": "The intent author stopped and said why -- the last lines of the run "
                   "window are its reason. E measured the floor anyway.",
        "stalled": "A round passed with talk and no command, so the run stopped.",
        "limit": "The round limit was reached with gaps still open.",
        "unchecked": "H' could not be reached, so nobody checked the goal. The work stands "
                     "unjudged.",
        "error": "The run could not go on -- the reason is in the window.",
    }

    def edit_goal(self) -> None:
        """TASK.md of this project, in an editor -- with P to propose a fuller goal
        from what is there. Nothing is written until Save: the goal is H's prose
        (SPEC-GROWTH-ENGINE.md 3.12), and P only proposes it."""
        if self._run_busy("The goal"):
            return
        path = Path(self.root_dir) / "TASK.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else groundwork.task_text(
            groundwork.WriteTask("", "", "", ""))
        win = tk.Toplevel(self)
        win.title(f"Goal - {path}")
        win.geometry("900x700")
        bar = ttk.Frame(win, padding=(8, 6))
        bar.pack(side="bottom", fill="x")
        status = ttk.Label(win, anchor="w", foreground="#5f5e5a", padding=(8, 4),
                           text="The goal a run is measured against. P can propose a "
                                "fuller one from what is here; nothing is saved until Save.")
        status.pack(side="bottom", fill="x")
        editor = ScrolledText(win, font=MONO, wrap="word", undo=True)
        editor.pack(side="top", fill="both", expand=True)
        editor.insert("1.0", text)
        editor.edit_reset()

        def suggest() -> None:
            if llm.missing("planner"):
                status.config(foreground="#b00000",
                              text="P is not configured: " + ", ".join(llm.missing("planner")))
                return
            current = groundwork.goal_of(editor.get("1.0", "end"))
            stack = groundwork._values(Path(self.root_dir)).get("CONTAINER", "")
            button.state(["disabled"])
            status.config(foreground="#5f5e5a", text="P is proposing ...")

            def work():
                try:
                    proposal = groundwork.suggest_goal(
                        current["purpose"], current["behaviours"], current["always"],
                        current["out_of_scope"], planner, architecture=self.arch, stack=stack)
                    error = None if proposal else "P gave no usable proposal."
                except Exception as exc:  # noqa: BLE001 -- said in the window
                    proposal, error = None, f"P is unavailable: {exc}"
                self.after(0, done, current, proposal, error)
            threading.Thread(target=work, daemon=True).start()

        def done(current: dict, proposal: dict | None, error: str | None) -> None:
            try:
                button.state(["!disabled"])
            except tk.TclError:
                return                               # the window was closed meanwhile
            if error:
                status.config(foreground="#b00000", text=error)
                return
            editor.edit_separator()
            editor.delete("1.0", "end")
            editor.insert("1.0", groundwork.task_text(groundwork.WriteTask(
                proposal["behaviours"], proposal["always"], proposal["out_of_scope"],
                current["purpose"])))
            editor.edit_separator()
            status.config(foreground="#0a7d00",
                          text="P's proposal -- edit it, then Save. Undo (Cmd/Ctrl+Z) brings "
                               "back what was there; Close without saving keeps TASK.md.")

        def save() -> None:
            path.write_text(editor.get("1.0", "end").rstrip("\n") + "\n", encoding="utf-8")
            status.config(foreground="#0a7d00", text=f"Saved {path}.")
            self._set(self.guidance, f"Goal saved: {path}. A run is measured against it.")

        button = ttk.Button(bar, text="Suggest with P", command=suggest)
        button.pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="Save", command=save).pack(side="right", padx=4)
        win._suggest, win._done, win._save, win._editor = suggest, done, save, editor

    def start_run(self) -> None:
        """Hand the AUTHORSHIP of intent to an agent, for this project, now.

        Not a setting like the slider and the delegation: a run has a lifetime.
        It goes in rounds (engine/iteration.py) and ends with a verdict, so the
        cockpit starts it, shows it, and says how it ended -- it does not offer
        an on/off switch for something that stops by itself. What it offers is
        HOW it runs: supervised (on), or unsupervised -- H' answers for you
        between rounds, and you review it afterwards (engine/unsupervised.py)."""
        if self._run:
            self._set(self.guidance, "A run is already in progress in this cockpit.")
            return
        dialog = RunDialog(self, self.root_dir, orchestrate.blockers(self.root_dir),
                           delegated=autonomy.delegated(self.root_dir))
        self.wait_window(dialog)
        if not dialog.result:
            return
        task, prompt, rounds, unsupervised = dialog.result
        argv = [sys.executable, str(Path(__file__).resolve().parent / "orchestrate.py"),
                self.root_dir, "--task", task, "--max-rounds", str(rounds),
                *(["--unsupervised"] if unsupervised else []), prompt]
        try:
            proc = subprocess.Popen(argv, cwd=self.root_dir, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
        except OSError as exc:
            self._set(self.guidance, f"The run could not start: {exc}")
            return
        self._open_run_window(proc, task, rounds, unsupervised)

    def _open_run_window(self, proc, task: str, rounds: int,
                         unsupervised: bool = False) -> None:
        win = tk.Toplevel(self)
        win.title(f"Run - {self.root_dir}")
        win.geometry("1000x700")
        status = ttk.Label(win, anchor="w", font=MONO, foreground="#0a7d00")
        status.pack(side="top", fill="x", padx=4, pady=(4, 0))
        bar = ttk.Frame(win)
        bar.pack(side="bottom", fill="x", padx=4, pady=4)
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        out = ScrolledText(win, font=MONO, wrap="none")
        out.pack(side="top", fill="both", expand=True)
        out.insert("end", f"===== RUN{' (UNSUPERVISED)' if unsupervised else ''}   "
                          f"root: {self.root_dir}   goal: {task}   "
                          f"at most {rounds} round(s)   pid: {proc.pid} =====\n")
        st = {"proc": proc, "win": win, "out": out, "status": status, "round": 0,
              "rounds": rounds, "outcome": None, "start": time.monotonic(),
              "last_output": time.monotonic(), "review": []}
        self._run = st
        self._lock_for_run(True)
        self._set(self.guidance,
                  "A run is in progress. It is unattended by definition: it writes specs "
                  "through P and code through C, and E and H' check every round.\n"
                  "Your way in is the Requests window, after a round -- Draft and Revise "
                  "are locked while it writes.")
        threading.Thread(target=self._run_read, args=(proc.stdout, st), daemon=True).start()
        self._monitor_run(st)

    def _run_read(self, stream, st: dict) -> None:
        """Render the run's stream into its window (runlog.py -- the same lines
        the run's own log in the project holds), and let the cockpit catch up after
        every round: a round writes specs, records tests, and may leave a
        question behind."""
        for line in stream:
            st["last_output"] = time.monotonic()
            try:
                event = json.loads(line)
            except ValueError:   # stderr, merged in: it belongs in the window verbatim
                self.after(0, self._append_out, st["out"], line.rstrip("\n") + "\n")
                continue
            for text in runlog.lines(event) or []:
                self.after(0, self._append_out, st["out"], text + "\n")
            if event.get("type") == "sge.round":
                self.after(0, self._run_round, st, event)
            elif runlog.outcome(event):
                st["outcome"] = runlog.outcome(event)
                st["review"] = event.get("review") or []
        st["proc"].wait()
        self.after(0, self._run_finished, st)

    def _run_round(self, st: dict, event: dict) -> None:
        """A round is over: the graph on disk moved, so the cockpit re-reads it."""
        st["round"] = event.get("round") or st["round"]
        self._reload_quiet()

    def _monitor_run(self, st: dict) -> None:
        """~1/s: which round, how long, whether anything is still happening."""
        proc = st["proc"]
        elapsed = self._fmt(time.monotonic() - st["start"])
        try:
            if proc.poll() is None:
                idle = self._fmt(time.monotonic() - st["last_output"])
                st["status"].config(
                    foreground="#0a7d00",
                    text=f"RUNNING  round {max(st['round'], 1)}/{st['rounds']}   "
                         f"pid {proc.pid}   elapsed {elapsed}   last output {idle} ago")
                st["win"].after(1000, self._monitor_run, st)
        except tk.TclError:
            return  # the window was closed; the run itself goes on

    def _run_finished(self, st: dict) -> None:
        rc = st["proc"].returncode
        outcome = st["outcome"] or ("done" if rc == 0 else "error")
        self._run = None
        self._lock_for_run(False)
        self._append_out(st["out"], f"\n===== RUN {outcome.upper()}   after "
                                    f"{st['round']} round(s), exit {rc} =====\n")
        try:
            st["status"].config(foreground="#000000" if outcome == "done" else "#b00000",
                                text=f"{outcome.upper()}   after {st['round']} round(s)   "
                                     f"elapsed {self._fmt(time.monotonic() - st['start'])}")
        except tk.TclError:
            pass
        self._reload_quiet()
        said = self._RUN_ENDED.get(outcome, f"The run ended: {outcome}.")
        review = st.get("review") or []
        if review:
            said += (f"\nUnsupervised, H' decided {len(review)} thing(s) in your place -- "
                     "each waits in Requests for your review: accept to confirm, reject to "
                     "take it back.")
        self._set(self.guidance, f"Run {outcome.upper()}.\n{said}\n\n"
                                 f"{self.requests_button.cget('text')} -- and the gate is "
                                 f"what the next run reads, so check Validate too.")
        if outcome == "asking" or review:
            self.show_requests()

    def _lock_for_run(self, locked: bool) -> None:
        """Draft, Revise and Save write the same SPEC.md files the run writes. While
        it runs they are off -- not to protect the engine (the gate would catch it)
        but so nobody edits under a writer they cannot see. The slider goes with
        them: a run drafts through the command line, which no slider reaches, so
        while one runs the draft gate decides nothing."""
        for button in (getattr(self, "draft_button", None), getattr(self, "revise_button", None),
                       getattr(self, "save_button", None)):
            try:
                button.configure(state="disabled" if locked else "normal")
            except (AttributeError, tk.TclError):
                pass
        scale = getattr(self, "autonomy_scale", None)
        if scale is not None:
            try:
                scale.state(["disabled"] if locked else ["!disabled"])
            except tk.TclError:
                pass
        self._render_autonomy()

    def _run_busy(self, what: str, parent=None) -> bool:
        """True, and says so, while a run is in progress."""
        if not self._run:
            return False
        message = (f"A run is in progress (round {max(self._run['round'], 1)}). {what} would "
                   "write the same files. Wait for the run to end -- its window says when.")
        if parent is not None:
            messagebox.showinfo("A run is in progress", message, parent=parent)
        else:
            self._set(self.guidance, message)
        return True

    def run_agent(self) -> None:
        if self._run_busy("The coder"):
            return
        nid = self._target()
        if nid not in self.nodes:
            self._set(self.guidance, "Pick an existing target node first.")
            return
        # C gets Context(N) built NOW from the saved specs -- never the editor's text,
        # as `cli.py code` and every run do: C must implement what the gate measures,
        # and an edit of the bundle would be recorded nowhere
        unsaved = self._unsaved_spec()
        if unsaved:
            self._set(self.guidance,
                      f"The editor holds a spec of {unsaved} that is not saved, and C "
                      "implements the SAVED SPEC.md. 'Save' first -- or pick the node "
                      "again to discard it.")
            return
        bundle = self._context_bundle(nid)
        if bundle is None:
            return
        self._preview(bundle)  # what C got, to read
        node = self.nodes.get(nid)
        broot = coder.build_root_for_node(node, self.root_dir) if node else None

        # C on its own endpoint (cockpit/.env: SGE_CODER_*), as `cli.py code` runs it
        try:
            command, env = coder.command()
        except RuntimeError as exc:
            self._set(self.guidance, f"The coder cannot start: {exc}")
            return
        # launch first so the monitor has the pid (codex can sit silent after an
        # `exec` for a while; the status bar shows it is still alive + working).
        try:
            proc = coder.implement(
                bundle, nid, node=node, project_root=self.root_dir,
                command=command, env=env,
            )
        except OSError as exc:
            self._set(self.guidance, f"Could not launch coder: {exc}")
            return

        # separate output window (keeps the right View pane clean)
        win = tk.Toplevel(self)
        win.title(f"Codex output - {nid}   (cwd: {broot})")
        win.geometry("960x720")
        status = ttk.Label(win, anchor="w", font=MONO, foreground="#0a7d00")
        status.pack(side="top", fill="x", padx=4, pady=(4, 0))

        # follow-up input bar at the bottom: ask Codex more; the prior output is
        # replayed with the question (codex exec is single-shot, no live session).
        bar = ttk.Frame(win)
        bar.pack(side="bottom", fill="x", padx=4, pady=4)
        entry = tk.Text(bar, font=MONO, height=3, wrap="word")  # 3-line follow-up input
        entry.pack(side="left", fill="both", expand=True)
        btncol = ttk.Frame(bar)
        btncol.pack(side="left", fill="y", padx=(4, 0))
        send_btn = ttk.Button(btncol, text="Ask Codex")
        send_btn.pack(side="top", fill="x")
        clear_btn = ttk.Button(btncol, text="Clear")
        clear_btn.pack(side="top", fill="x", pady=(4, 0))
        ttk.Button(btncol, text="Close", command=win.destroy).pack(side="top", fill="x", pady=(4, 0))

        out = ScrolledText(win, font=MONO, wrap="none")
        out.pack(side="top", fill="both", expand=True)
        out.insert("end", f"===== CODER OUTPUT  (node: {nid}, cwd: {broot}, pid: {proc.pid}) =====\n")

        st = {
            "start": time.monotonic(), "last_output": time.monotonic(),
            "transcript": "", "bundle": bundle, "nid": nid, "cwd": str(broot) if broot else None,
            "command": command, "env": env, "running": False,
            "win": win, "status": status, "out": out, "entry": entry, "send_btn": send_btn,
        }
        send_btn.configure(command=lambda: self._codex_followup(st))
        clear_btn.configure(command=lambda: self._codex_clear(st))
        # Enter inserts a newline (3-line box); send with the button or Cmd/Ctrl+Enter.
        entry.bind("<Control-Return>", lambda _e: (self._codex_followup(st), "break")[1])
        entry.bind("<Command-Return>", lambda _e: (self._codex_followup(st), "break")[1])
        self._set(self.guidance,
                  f"Built the context bundle for `{nid}` from the saved specs -- it is in "
                  f"the editor.\nCoding agent running in {broot} ...\n"
                  "(see the Codex output window)")
        self._start_codex_stream(proc, st)

    def _start_codex_stream(self, proc, st: dict) -> None:
        st["running"] = True
        try:
            st["send_btn"].configure(state="disabled")  # no concurrent runs
        except tk.TclError:
            pass
        threading.Thread(target=self._agent_read, args=(proc, st), daemon=True).start()
        self._monitor_codex(proc, st)

    def _agent_read(self, proc, st: dict) -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            st["last_output"] = time.monotonic()
            st["transcript"] += line
            self.after(0, self._append_out, st["out"], line)
        proc.wait()
        self.after(0, self._append_out, st["out"], f"\n===== finished (exit {proc.returncode}) =====\n")
        self.after(0, self._codex_finished, proc.returncode, st)

    def _codex_finished(self, returncode: int, st: dict) -> None:
        st["running"] = False
        try:
            st["send_btn"].configure(state="normal")
        except tk.TclError:
            pass
        self._coder_done(returncode)

    def _codex_clear(self, st: dict) -> None:
        """Reset the replayed conversation: the next 'Ask Codex' starts fresh from the
        node bundle only (drops accumulated output). The bundle prefix is kept."""
        st["transcript"] = ""
        try:
            st["out"].delete("1.0", "end")
            st["out"].insert(
                "end", "===== context cleared -- next 'Ask Codex' starts fresh "
                "from the node bundle =====\n")
            st["entry"].delete("1.0", "end")
        except tk.TclError:
            pass

    def _codex_followup(self, st: dict) -> None:
        """Send a follow-up: replay context + prior output + the new message as a
        fresh codex exec run, streamed into the same window."""
        if st.get("running"):
            return  # a run is already in progress
        msg = st["entry"].get("1.0", "end").strip()
        if not msg:
            return
        st["entry"].delete("1.0", "end")
        self._append_out(st["out"], f"\n\n>>> YOU: {msg}\n\n")
        prompt = coder.followup_prompt(st["bundle"], st["nid"], st["transcript"][-20000:], msg)
        try:
            proc = coder.run_prompt(prompt, st["cwd"], st["command"], st["env"])
        except OSError as exc:
            self._append_out(st["out"], f"(could not launch coder: {exc})\n")
            return
        st["start"] = time.monotonic()
        st["last_output"] = time.monotonic()
        self._start_codex_stream(proc, st)

    def _monitor_codex(self, proc, st: dict) -> None:
        """Refresh the status bar ~1/s: state, elapsed, process-tree CPU, idle time.
        Lets you tell 'working silently' (CPU>0) from 'possibly stuck' (CPU~0, idle)."""
        rc = proc.poll()
        elapsed = self._fmt(time.monotonic() - st["start"])
        try:
            if rc is None:
                cpu = self._proc_tree_cpu(proc.pid)
                cpu_s = f"{cpu:.0f}%" if cpu is not None else "n/a"
                idle = self._fmt(time.monotonic() - st["last_output"])
                st["status"].config(
                    foreground="#0a7d00",
                    text=f"RUNNING  pid {proc.pid}   elapsed {elapsed}   "
                         f"CPU(tree) {cpu_s}   last output {idle} ago",
                )
                st["win"].after(1000, self._monitor_codex, proc, st)
            else:
                st["status"].config(
                    foreground="#000000" if rc == 0 else "#b00000",
                    text=f"FINISHED  exit {rc}   elapsed {elapsed}   (Ask Codex to continue)",
                )
        except tk.TclError:
            return  # output window was closed; stop polling

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = int(seconds)
        return f"{s // 60:02d}:{s % 60:02d}"

    @staticmethod
    def _proc_tree_cpu(pid: int) -> float | None:
        """Summed %CPU of `pid` and all its descendants (codex + mvn/java/...)."""
        try:
            text = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,pcpu="],
                capture_output=True, text=True, timeout=2,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        kids: dict[int, list[int]] = {}
        cpu: dict[int, float] = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                p, pp, c = int(parts[0]), int(parts[1]), float(parts[2])
            except ValueError:
                continue
            kids.setdefault(pp, []).append(p)
            cpu[p] = c
        total, stack, seen = 0.0, [pid], set()
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            total += cpu.get(x, 0.0)
            stack.extend(kids.get(x, []))
        return total

    @staticmethod
    def _append_out(widget: ScrolledText, text: str) -> None:
        try:  # the user may have closed the output window
            widget.insert("end", text)
            widget.see("end")
        except tk.TclError:
            pass

    def run_tests_action(self) -> None:
        if self._run_busy("A test run"):
            return
        nid = self._target()
        node = self.nodes.get(nid) or {"_dir": self.root_dir}
        try:
            proc, root, cmd = testrun.run_tests(node, self.root_dir)
        except ValueError as exc:
            self._set(self.guidance, f"Run tests: {exc}")
            return
        except OSError as exc:
            self._set(self.guidance, f"Run tests could not launch ({exc}). Is the tool on PATH?")
            return
        win = tk.Toplevel(self)
        win.title(f"Tests: {' '.join(cmd)}   (cwd: {root})")
        win.geometry("960x640")
        out = ScrolledText(win, font=MONO, wrap="none")
        out.pack(fill="both", expand=True)
        ttk.Button(win, text="Close", command=win.destroy).pack(anchor="e", padx=4, pady=4)
        out.insert("end", f"$ {' '.join(cmd)}   (cwd: {root})\n\n")
        # nodes covered by this run = all whose build root is the one we test in;
        # the verdict is recorded as their test evidence (backs status 'verified').
        started = testrun.now()   # a file changed during the run was not tested
        self._set(self.guidance, f"Running tests: {' '.join(cmd)} ...")
        threading.Thread(target=self._tests_thread,
                         args=(proc, out, started, " ".join(cmd), str(root)), daemon=True).start()

    def _tests_thread(self, proc, out: ScrolledText, started: str,
                      cmd: str, root: str) -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            self.after(0, self._append_out, out, line)
        proc.wait()
        passed = proc.returncode == 0
        verdict = "PASS" if passed else f"FAIL (exit {proc.returncode})"
        self.after(0, self._append_out, out, f"\n===== tests {verdict} =====\n")
        self.after(0, self._record_test_evidence, started, passed, cmd, root)

    def _record_test_evidence(self, started: str, passed: bool,
                              cmd: str, root: str) -> None:
        msg = f"Tests finished: {'PASS' if passed else 'FAIL'}."
        covered = testrun.record(self.nodes, self.root_dir, root, passed, cmd, started)
        if covered:
            msg += (f"\nEvidence recorded for: {', '.join(covered)} "
                    f"({'backs' if passed else 'BLOCKS'} status 'verified').")
        self._set(self.guidance, msg)

    def _coder_done(self, returncode: int) -> None:
        heal = self._heal_specs()  # the coder may have written a SPEC.md with broken YAML
        self.reload_nodes()
        self.target["values"] = sorted(self.nodes)
        msg = (f"Coder finished (exit {returncode}). Reloaded.\n"
               "Verify: 'Build context' (own code should appear) and 'Drift (code)'.")
        if heal:
            msg += "\nSPEC YAML check:\n  " + "\n  ".join(heal)
        self._set(self.guidance, msg)


class NewNodeDialog(tk.Toplevel):
    """Modal dialog to create a node: pick parent, segment name, and kind.

    On OK, `result` is set to (parent_id, segment, kind, layout_key); layout_key is
    only meaningful for kind=container (seeds its code-layout invariants), '' otherwise.
    The caller computes the final dotted id (see engine.nodes.new_node).
    """

    def __init__(self, parent: tk.Tk, node_ids: list[str], default_parent: str) -> None:
        super().__init__(parent)
        self.title("New node")
        self.resizable(False, False)
        self.result: tuple[str, str, str, str] | None = None
        self._layout_keys = [k for k, _ in layouts.labels()]

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Parent:").grid(row=0, column=0, sticky="w", pady=3)
        self.parent_cb = ttk.Combobox(body, values=node_ids, state="readonly", width=32)
        self.parent_cb.grid(row=0, column=1, pady=3)
        if default_parent in node_ids:
            self.parent_cb.set(default_parent)
        elif node_ids:
            self.parent_cb.current(0)

        ttk.Label(body, text="Segment (last id part):").grid(row=1, column=0, sticky="w", pady=3)
        self.segment_entry = ttk.Entry(body, width=34)
        self.segment_entry.grid(row=1, column=1, pady=3)

        ttk.Label(body, text="Kind:").grid(row=2, column=0, sticky="w", pady=3)
        self.kind_cb = ttk.Combobox(body, values=KINDS, state="readonly", width=32)
        self.kind_cb.grid(row=2, column=1, pady=3)
        self.kind_cb.set("component")
        self.kind_cb.bind("<<ComboboxSelected>>", lambda _e: self._sync_layout())

        # code-layout convention -- only relevant for a container (it sets this
        # container subtree's language + layout as invariants, carried down the Spine).
        ttk.Label(body, text="Code layout (container):").grid(row=3, column=0, sticky="w", pady=3)
        self.layout_cb = ttk.Combobox(
            body, values=[label for _, label in layouts.labels()], state="readonly", width=32
        )
        self.layout_cb.grid(row=3, column=1, pady=3)
        self.layout_cb.current(0)

        ttk.Label(
            body,
            text="id = segment (under the system root) or <parent>.<segment>.\n"
            "Code layout applies only to containers; components inherit it via the Spine.",
            foreground="#5f5e5a",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=3)
        ttk.Button(buttons, text="Create", command=self._ok).pack(side="right", padx=3)

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.transient(parent)
        self.grab_set()
        self._sync_layout()
        self.segment_entry.focus_set()

    def _sync_layout(self) -> None:
        # the layout picker is only meaningful for a container
        state = "readonly" if self.kind_cb.get().strip() == "container" else "disabled"
        self.layout_cb.configure(state=state)

    def _ok(self) -> None:
        parent_id = self.parent_cb.get().strip()
        segment = self.segment_entry.get().strip()
        kind = self.kind_cb.get().strip()
        if not (parent_id and segment):
            messagebox.showwarning("New node", "Parent and segment are required.", parent=self)
            return
        layout_key = ""
        if kind == "container":
            idx = self.layout_cb.current()
            layout_key = self._layout_keys[idx] if 0 <= idx < len(self._layout_keys) else ""
        self.result = (parent_id, segment, kind, layout_key)
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class GroundworkDialog(tk.Toplevel):
    """Lay the floor of a new project: the root, one container with its layout and
    build manifest, the invariants, and the accepted state (groundwork.py).

    One window rather than a sequence of them: the four questions are short, and
    a person deciding what holds everywhere should see all of it at once. Nothing
    is written while it is open -- OK returns the answers, the caller plans, shows
    what would be written, and only then applies.

    `result` is the answers dict, or None.

    The form scrolls: with the goal fields open it is taller than a laptop
    screen, and a dialog that grows past the screen hides its own buttons. The
    buttons sit outside the scrolled part, so they are always in reach.
    """

    def __init__(self, parent: tk.Tk, initial_dir: str) -> None:
        super().__init__(parent)
        self.title("New project")
        self.result: dict | None = None
        self._planner = None          # set by the caller when P has an endpoint

        buttons = ttk.Frame(self, padding=(12, 6, 12, 10))
        buttons.pack(side="bottom", fill="x")
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=3)
        ttk.Button(buttons, text="Lay the floor", command=self._ok).pack(side="right", padx=3)
        ttk.Separator(self, orient="horizontal").pack(side="bottom", fill="x")

        area = ttk.Frame(self)
        area.pack(side="top", fill="both", expand=True)
        self._canvas = tk.Canvas(area, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(self._canvas, padding=12)
        self._body = body
        window = self._canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(
            window, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel)            # macOS, Windows
        self.bind_all("<Button-4>", lambda _e: self._canvas.yview_scroll(-1, "units"))
        self.bind_all("<Button-5>", lambda _e: self._canvas.yview_scroll(1, "units"))
        self.bind("<Destroy>", self._unbind_wheel)
        row = 0

        def field(label: str, value: str = "", width: int = 44) -> ttk.Entry:
            nonlocal row
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(body, width=width)
            entry.grid(row=row, column=1, columnspan=2, sticky="we", pady=3)
            entry.insert(0, value)
            row += 1
            return entry

        self.dir_entry = field("Target directory:", initial_dir)
        ttk.Button(body, text="Browse...", command=self._browse).grid(row=0, column=3, padx=4)
        self.id_entry = field("System id:", "app")
        self.purpose_entry = field("What is it? (one sentence)")
        self.container_entry = field("First container:", "core")

        ttk.Label(body, text="Code layout:").grid(row=row, column=0, sticky="w", pady=3)
        self._layout_keys = [k for k, _ in layouts.labels()]
        self.layout_box = ttk.Combobox(body, values=[label for _, label in layouts.labels()],
                                       state="readonly", width=42)
        self.layout_box.current(self._layout_keys.index("python-uv-src")
                                if "python-uv-src" in self._layout_keys else 0)
        self.layout_box.grid(row=row, column=1, columnspan=2, sticky="we", pady=3)
        row += 1

        ttk.Label(body, text="These hold everywhere. Keep what you mean:",
                  font=(MONO[0], MONO[1], "bold")).grid(row=row, column=0, columnspan=3,
                                                        sticky="w", pady=(10, 2))
        row += 1
        self.defaults: list[tuple[tk.BooleanVar, str]] = []
        for line in groundwork.DEFAULT_INVARIANTS:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(body, text=line, variable=var).grid(
                row=row, column=0, columnspan=4, sticky="w")
            self.defaults.append((var, line))
            row += 1

        ttk.Label(body, text="And four the defaults cannot know (skip what does not apply):",
                  font=(MONO[0], MONO[1], "bold")).grid(row=row, column=0, columnspan=3,
                                                        sticky="w", pady=(10, 2))
        row += 1
        self.answers: list[tuple[groundwork.Question, ttk.Entry]] = []
        for question in groundwork.QUESTIONS:
            ttk.Label(body, text=question.ask).grid(row=row, column=0, columnspan=4, sticky="w")
            row += 1
            entry = ttk.Entry(body, width=60)
            entry.grid(row=row, column=0, columnspan=3, sticky="we", padx=(16, 0))
            ttk.Label(body, text=question.hint, foreground="#5f5e5a").grid(
                row=row + 1, column=0, columnspan=4, sticky="w", padx=(16, 0))
            self.answers.append((question, entry))
            row += 2

        self.wants_run = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, variable=self.wants_run, command=self._toggle_goal,
                        text="An AGENT will build this -- write the goal (TASK.md) now"
                        ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(12, 2))
        row += 1
        self.goal_frame = ttk.Frame(body)
        self.goal_frame.grid(row=row, column=0, columnspan=4, sticky="we")
        self.goal_frame.grid_remove()          # only when the box is ticked
        self.goal: dict[str, tk.Text] = {}
        for i, (key, ask, hint) in enumerate(groundwork.TASK_PROMPTS):
            ttk.Label(self.goal_frame, text=ask).grid(row=i * 3, column=0, sticky="w")
            ttk.Label(self.goal_frame, text=hint, foreground="#5f5e5a").grid(
                row=i * 3 + 1, column=0, sticky="w", padx=(16, 0))
            box = tk.Text(self.goal_frame, height=3, width=70, font=MONO, wrap="word")
            box.grid(row=i * 3 + 2, column=0, sticky="we", padx=(16, 0), pady=(0, 6))
            self.goal[key] = box
        ttk.Label(self.goal_frame, foreground="#5f5e5a",
                  text="One line each. 'Done means' is filled in for you -- it is the "
                       "method's standard, not yours to invent.").grid(
            row=len(groundwork.TASK_PROMPTS) * 3, column=0, sticky="w", padx=(16, 0))
        suggest = ttk.Frame(self.goal_frame)
        suggest.grid(row=len(groundwork.TASK_PROMPTS) * 3 + 1, column=0, sticky="w",
                      padx=(16, 0), pady=(6, 0))
        self.suggest_button = ttk.Button(suggest, text="Suggest with P",
                                         command=self._suggest_goal)
        self.suggest_button.pack(side="left")
        self.suggest_status = ttk.Label(
            suggest, foreground="#5f5e5a",
            text="P turns your few words into a fuller goal -- you edit it; it stays yours.")
        self.suggest_status.pack(side="left", padx=(8, 0))
        row += 1

        self.bind("<Escape>", lambda _e: self._cancel())
        self._fit_to_screen()
        self.transient(parent)
        self.grab_set()
        self.id_entry.focus_set()

    def _fit_to_screen(self) -> None:
        """As tall as the form, but never taller than the screen allows."""
        self.update_idletasks()
        width = self._body.winfo_reqwidth()
        height = min(self._body.winfo_reqheight(), self.winfo_screenheight() - 200)
        self._canvas.configure(width=width, height=max(height, 200))

    def _wheel(self, event) -> None:
        """Scroll the form with the wheel or the trackpad. macOS reports small
        deltas, Windows multiples of 120."""
        steps = -event.delta if abs(event.delta) < 120 else -event.delta // 120
        self._canvas.yview_scroll(int(steps) or (-1 if event.delta > 0 else 1), "units")

    def _unbind_wheel(self, event) -> None:
        if event.widget is self:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.unbind_all(sequence)

    def _goal_context(self) -> tuple[str, str]:
        """(architecture, stack) as the dialog stands: what P must not contradict."""
        kept = [line for var, line in self.defaults if var.get()]
        kept += [entry.get().strip() for _q, entry in self.answers if entry.get().strip()]
        return "\n".join(f"- {line}" for line in kept), self.layout_box.get()

    def _suggest_goal(self) -> None:
        """Ask P for a fuller goal, in the background; fill the fields with it."""
        if not self._planner:
            self.suggest_status.config(foreground="#b00000",
                                       text="P has no endpoint (SGE_PLANNER_* in cockpit/.env).")
            return
        fields = {key: box.get("1.0", "end").strip() for key, box in self.goal.items()}
        architecture, stack = self._goal_context()
        purpose = self.purpose_entry.get().strip()
        self.suggest_button.state(["disabled"])
        self.suggest_status.config(foreground="#5f5e5a", text="P is proposing ...")

        def work():
            try:
                proposal = groundwork.suggest_goal(
                    purpose, fields["behaviours"], fields["always"], fields["out_of_scope"],
                    self._planner, architecture=architecture, stack=stack)
                error = None if proposal else "P gave no usable proposal."
            except Exception as exc:  # noqa: BLE001 -- said in the dialog, never raised
                proposal, error = None, f"P is unavailable: {exc}"
            self.after(0, self._apply_goal_suggestion, proposal, error)
        threading.Thread(target=work, daemon=True).start()

    def _apply_goal_suggestion(self, proposal: dict | None, error: str | None) -> None:
        try:
            self.suggest_button.state(["!disabled"])
        except tk.TclError:
            return                                   # the dialog was closed meanwhile
        if error:
            self.suggest_status.config(foreground="#b00000", text=error)
            return
        for key, box in self.goal.items():
            box.delete("1.0", "end")
            box.insert("1.0", proposal.get(key, ""))
        self.suggest_status.config(
            foreground="#0a7d00",
            text="P's proposal -- read it, change what you mean differently. It is your goal.")

    def _toggle_goal(self) -> None:
        """Open or close the goal fields -- and, opening them, scroll them into
        view: they appear at the bottom, where a tall form would hide them."""
        if self.wants_run.get():
            self.goal_frame.grid()
            self._fit_to_screen()
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
            self._canvas.yview_moveto(1.0)
        else:
            self.goal_frame.grid_remove()

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(title="New project directory", parent=self)
        if chosen:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, chosen)

    def _invariants(self) -> list[str]:
        """The kept defaults, then one line per answered question -- worded by P
        when it is reachable, and by the person otherwise."""
        lines = [line for var, line in self.defaults if var.get()]
        for question, entry in self.answers:
            said = entry.get().strip()
            if said:
                lines.append(groundwork.propose(question, said, self._planner)
                             if self._planner else said)
        return lines

    def _ok(self) -> None:
        directory, system_id = self.dir_entry.get().strip(), self.id_entry.get().strip()
        container = self.container_entry.get().strip()
        if not (directory and system_id and container):
            messagebox.showerror("New project",
                                 "A directory, a system id and a container are needed.",
                                 parent=self)
            return
        why = groundwork.refuses(directory)
        if why:      # said here, while the dialog -- and what was typed -- is still open
            messagebox.showerror("New project", why, parent=self)
            return
        self.result = {
            "root": directory, "system_id": system_id, "container": container,
            "purpose": self.purpose_entry.get().strip(),
            "archetype": self._layout_keys[self.layout_box.current()],
            "invariants": self._invariants(), "by": getpass.getuser(),
        }
        if self.wants_run.get():
            self.result.update({key: box.get("1.0", "end").strip()
                                for key, box in self.goal.items()})
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class RunDialog(tk.Toplevel):
    """Start a run: the goal it will be measured against, the first prompt, and
    how many rounds it may take.

    `missing` is what this project still lacks (orchestrate.blockers). It is
    shown, and while anything is left the button stays off: a run that starts
    without its goal, its manuals or an endpoint fails slowly, and the failure
    reads like the agent's.

    `delegated` says whether this project's delegation is on: an unsupervised
    run needs it, so without it that choice is offered but off, with the reason.

    `result` is (task, prompt, max_rounds, unsupervised), or None.
    """

    def __init__(self, parent: tk.Tk, root_dir: str, missing: list[str],
                 delegated: bool = False) -> None:
        super().__init__(parent)
        self.title("Start a run")
        self.result: tuple[str, str, int, bool] | None = None

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"An agent writes the intent for {root_dir}. It is unattended: "
                             "it reaches P and C\nthrough the engine, and after every round "
                             "E checks the floor and H' the goal.",
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Label(body, text="Goal (TASK.md):").grid(row=1, column=0, sticky="w", pady=3)
        self.task_entry = ttk.Entry(body, width=58)
        self.task_entry.insert(0, str(Path(root_dir) / "TASK.md"))
        self.task_entry.grid(row=1, column=1, sticky="we", pady=3)
        ttk.Button(body, text="Browse...", command=self._browse).grid(row=1, column=2, padx=4)

        ttk.Label(body, text="At most:").grid(row=2, column=0, sticky="w", pady=3)
        self.rounds = tk.IntVar(value=iteration.MAX_ROUNDS)
        spin = ttk.Frame(body)
        spin.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Spinbox(spin, from_=1, to=20, width=4, textvariable=self.rounds).pack(side="left")
        ttk.Label(spin, text="  round(s) -- after each one the agent is resumed with what "
                             "is missing; 1 means no second try").pack(side="left")

        ttk.Label(body, text="Run:").grid(row=3, column=0, sticky="nw", pady=3)
        self.unsupervised = tk.BooleanVar(value=False)
        modes = ttk.Frame(body)
        modes.grid(row=3, column=1, columnspan=2, sticky="w", pady=3)
        ttk.Radiobutton(modes, text="on -- what is above a node waits for you; the run "
                                    "ends `asking` and you answer",
                        variable=self.unsupervised, value=False,
                        command=self._mode_changed).pack(anchor="w")
        ttk.Radiobutton(modes, text="unsupervised -- H' answers for you between rounds; "
                                    "you review every answer afterwards",
                        variable=self.unsupervised, value=True, command=self._mode_changed,
                        state="normal" if delegated else "disabled").pack(anchor="w")
        if not delegated:
            ttk.Label(modes, text="    (needs the delegation on -- the switch beside the "
                                  "slider)", foreground="#5f5e5a").pack(anchor="w")

        ttk.Label(body, text="First prompt:").grid(row=4, column=0, sticky="nw", pady=3)
        self.prompt = tk.Text(body, font=MONO, height=8, width=70, wrap="word")
        self.prompt.insert("1.0", orchestrate.first_prompt())
        self.prompt.grid(row=4, column=1, columnspan=2, sticky="we", pady=3)

        if missing:
            ttk.Label(body, text="Not ready for a run:", foreground="#b00000",
                      font=(MONO[0], MONO[1], "bold")).grid(row=5, column=0, columnspan=3,
                                                            sticky="w", pady=(10, 2))
            ttk.Label(body, text="\n".join(f"  {line}" for line in missing),
                      foreground="#b00000", justify="left").grid(row=6, column=0, columnspan=3,
                                                                 sticky="w")

        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=3)
        self.start_button = ttk.Button(buttons, text="Start the run", command=self._ok,
                                       state="disabled" if missing else "normal")
        self.start_button.pack(side="right", padx=3)

        self.transient(parent)
        self.grab_set()

    def _mode_changed(self) -> None:
        """Swap the first prompt with the mode -- unless H has edited it."""
        now = self.prompt.get("1.0", "end").strip()
        other = orchestrate.first_prompt(not self.unsupervised.get())
        if now == other:
            self.prompt.delete("1.0", "end")
            self.prompt.insert("1.0", orchestrate.first_prompt(self.unsupervised.get()))

    def _browse(self) -> None:
        path = filedialog.askopenfilename(title="The goal a run is measured against",
                                          filetypes=[("Markdown", "*.md"), ("All files", "*")])
        if path:
            self.task_entry.delete(0, "end")
            self.task_entry.insert(0, path)

    def _ok(self) -> None:
        task = self.task_entry.get().strip()
        prompt = self.prompt.get("1.0", "end").strip()
        if not Path(task).is_file():
            messagebox.showerror("Start a run", f"No goal at {task}.", parent=self)
            return
        if not prompt:
            messagebox.showerror("Start a run", "A run needs a first prompt.", parent=self)
            return
        self.result = (task, prompt, max(1, int(self.rounds.get())),
                       bool(self.unsupervised.get()))
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


if __name__ == "__main__":
    root_arg = sys.argv[1] if len(sys.argv) > 1 else None  # else: last_root from config
    Cockpit(root_arg).mainloop()
