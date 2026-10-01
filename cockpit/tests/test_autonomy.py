"""The draft gate at D2: the declared protected zones, the audit log, and the D2 decision
itself -- which may clear only what the change set calls SOFT -- plus Save's HARD
confirm."""
import json

import pytest

import app
from agent import planner, reviewer
from engine import autonomy, lifecycle
from tests.test_assist import _client_answering, _refusing, _Resp


def test_the_draft_gate_offers_d2():
    assert autonomy.DRAFT_MAX == 2  # D2 is selectable on the slider


def test_node_tree_children_orders_ownership_tree():
    nodes = {
        "api.hello": {"parent": "api"},
        "app": {"parent": None},
        "orphan": {"parent": "missing"},
        "api": {"parent": "app"},
        "data": {"parent": "app"},
    }
    children = app._node_tree_children(nodes)
    assert children[""] == ["app", "orphan"]
    assert children["app"] == ["api", "data"]
    assert children["api"] == ["api.hello"]
    assert children["api.hello"] == []


def test_node_graph_layout_places_root_above_children():
    nodes = {
        "api.hello": {"parent": "api"},
        "app": {"parent": None},
        "api": {"parent": "app"},
        "data": {"parent": "app"},
    }
    positions, edges = app._node_graph_layout(nodes)
    assert ("app", "api") in edges
    assert ("api", "api.hello") in edges
    assert positions["app"][1] < positions["api"][1] < positions["api.hello"][1]
    assert positions["data"][1] == positions["api"][1]


def test_log_autonomy_appends_jsonl(tmp_path):
    lifecycle.log_autonomy(str(tmp_path), {"node": "a", "draft_gate": 2, "action": "auto-saved"})
    lifecycle.log_autonomy(str(tmp_path), {"node": "b", "draft_gate": 2,
                                           "action": "escalated", "reason": "low confidence"})
    lines = (tmp_path / ".sge" / "autonomy.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    r0, r1 = json.loads(lines[0]), json.loads(lines[1])
    assert r0["node"] == "a" and r0["action"] == "auto-saved" and "at" in r0
    assert r1["reason"] == "low confidence"


# ---- declared protected zones (AUTONOMY.md 5b) --------------------------------
#
# The keyword scan these replaced is gone: a node is high-stakes or outward
# because its SPEC.md says so (`protected: true`), not because a word matched.

def test_d2_escalates_a_declared_protected_node(graph_root):
    """A protected node's draft goes to H even when the change is SOFT: the
    declaration, not a keyword, is what skips D2."""
    before = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    protected = before.replace("kind: component",
                               "kind: component\nprotected: true", 1)
    (graph_root / "util" / "SPEC.md").write_text(protected, encoding="utf-8")
    draft = protected.replace("log()", "log()\n  - flush()")   # additive -> SOFT
    out = _Cockpit(graph_root)._d2_draft("add a flush", "util", draft, _APPROVE)
    assert "declared protected" in out
    assert (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8") == protected


def test_d2_escalates_a_breaking_change_to_a_declared_outward_component(graph_root):
    """Run 03's hole: svc.cli is a component, so nothing depended on it and a
    breaking contract change read SOFT. Declared outward, it is HARD."""
    before = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    protected = before.replace("kind: component",
                               "kind: component\nprotected: true", 1)
    (graph_root / "util" / "SPEC.md").write_text(protected, encoding="utf-8")
    draft = before.replace("log()", "write(line)")   # breaking; new spec drops the marker
    out = _Cockpit(graph_root)._d2_draft("rename the logger", "util", draft, _APPROVE)
    assert "HARD gate" in out and "declared protected" in out


# ---- D2 clears SOFT only: the change set decides what SOFT is -----------------

class _Cockpit:
    """Just enough of app.Cockpit to run the D2 decision without Tk."""
    _d2_draft = app.Cockpit._d2_draft
    _d2_accept = app.Cockpit._d2_accept
    _d2_escalate = app.Cockpit._d2_escalate
    _assess = app.Cockpit._assess
    _persist_spec = app.Cockpit._persist_spec
    _record_accepted = app.Cockpit._record_accepted
    _format_review = staticmethod(app.Cockpit._format_review)
    _reviewer_model = app.Cockpit._reviewer_model
    _independence_note = app.Cockpit._independence_note
    _record_intent = app.Cockpit._record_intent
    _request_targets = app.Cockpit._request_targets
    _has_substance = staticmethod(app.Cockpit._has_substance)
    _spine = app.Cockpit._spine
    _last_intent = None

    def __init__(self, root):
        self.root_dir, self.arch, self.view = str(root), "", None
        self.config_data, self.target = {"planner_model": "unused"}, {}
        self.reload_nodes()

    def _set(self, *_):
        pass

    def _review(self, *_):
        raise AssertionError("an approving first review needs no second one")

    def reload_nodes(self):
        from engine import parser
        self.nodes = parser.load_nodes(self.root_dir)


_APPROVE = {"verdict": "approve", "confidence": 0.9, "findings": []}


def _log(root):
    path = root / ".sge" / "autonomy.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_d2_escalates_a_breaking_change_to_a_consumed_contract(graph_root):
    """The hole this closes: an approved draft that removed `log()` -- which
    api.hello depends on -- used to be auto-saved with 'gate: pass'."""
    before = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    draft = before.replace("log()", "write(line)")
    out = _Cockpit(graph_root)._d2_draft("rename the logger", "util", draft, _APPROVE)
    assert out.startswith("D2 -> ESCALATED to you: HARD gate")
    assert "consumed by api.hello" in out
    assert (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8") == before
    [entry] = _log(graph_root)
    assert entry["action"] == "escalated" and entry["gate"] == "HARD"


def test_d2_escalates_a_new_container(graph_root):
    draft = "---\nid: web\nparent: app\nkind: container\ncontract:\n  provides: [ui]\n---\n"
    out = _Cockpit(graph_root)._d2_draft("add a web frontend", "web", draft, _APPROVE)
    assert "HARD gate" in out and "new container" in out
    assert not (graph_root / "web").exists()


def test_d2_still_auto_saves_a_soft_draft(graph_root):
    draft = ("---\nid: api.store\nparent: api\nkind: component\n"
             "contract:\n  provides: [\"keep(item)\"]\n"
             "  acceptance_criteria: [\"a kept item can be read back\"]\n"
             "depends_on: []\ncode: [\"api/store/*.py\"]\nstatus: specd\n---\n\n# Store\n")
    out = _Cockpit(graph_root)._d2_draft("keep items", "api.store", draft, _APPROVE)
    assert out.startswith("D2: H' approved"), out
    assert (graph_root / "api" / "store" / "SPEC.md").is_file()
    [entry] = _log(graph_root)
    assert entry["action"].startswith("auto-saved") and entry["gate"] == "SOFT"


def test_d2_escalates_a_draft_that_does_not_parse(graph_root):
    # a tab-indented key: specfix cannot repair it (it rescues `id: [broken`)
    out = _Cockpit(graph_root)._d2_draft("x", "util", "---\nid: a\n\tkind: x\n---\n", _APPROVE)
    assert "does not parse" in out


# ---- manual Save: a HARD change set asks H first (every level) ----------------

class _SaveCockpit(_Cockpit):
    save_spec = app.Cockpit.save_spec

    def __init__(self, root, nid, text):
        super().__init__(root)
        self.guidance, self._nid, self._text, self.said = "guidance", nid, text, ""

    def _target(self):
        return self._nid

    def _get(self, _widget):
        return self._text

    def _set(self, widget, text=""):
        if widget == "guidance":
            self.said = text


@pytest.mark.parametrize("answer", [False, True])
def test_save_asks_before_writing_a_hard_change(graph_root, monkeypatch, answer):
    asked = []
    monkeypatch.setattr(app.messagebox, "askyesno",
                        lambda title, msg: asked.append(msg) or answer)
    spec = graph_root / "util" / "SPEC.md"
    before = spec.read_text(encoding="utf-8")
    cockpit = _SaveCockpit(graph_root, "util", before.replace("log()", "write(line)"))
    cockpit.save_spec()
    [question] = asked
    assert "consumed by api.hello" in question
    assert ("write(line)" in spec.read_text(encoding="utf-8")) is answer
    assert cockpit.said.startswith("Wrote" if answer else "Not saved.")


def test_save_does_not_ask_about_a_soft_change(graph_root, monkeypatch):
    monkeypatch.setattr(app.messagebox, "askyesno",
                        lambda *_: pytest.fail("a SOFT change needs no confirmation"))
    spec = graph_root / "util" / "SPEC.md"
    cockpit = _SaveCockpit(graph_root, "util", spec.read_text(encoding="utf-8")
                           .replace("log()", "log()\n  - flush()"))
    cockpit.save_spec()
    assert "flush()" in spec.read_text(encoding="utf-8")
    assert "change set util: SOFT" in cockpit.said


# ---- engine.autonomy: the decision without Tk and without a model -------------

_SOFT = {"gate": "SOFT", "reasons": [("SOFT", "new component boundary under api")]}
_HARD = {"gate": "HARD", "reasons": [("HARD", "new container")]}
_SOFT_PROTECTED = {"gate": "SOFT", "protected": True,
                   "reasons": [("SOFT", "provides added"), ("NONE", "declared protected")]}


@pytest.mark.parametrize("change,review,action", [
    (None, _APPROVE, "escalate"),
    (_HARD, _APPROVE, "escalate"),
    (_SOFT_PROTECTED, _APPROVE, "escalate"),
    (_SOFT, _APPROVE, "accept"),
    (_SOFT, {"verdict": "approve", "confidence": 0.5, "findings": []}, "escalate"),
    (_SOFT, {"verdict": "approve", "confidence": 0.9,
             "findings": [{"severity": "blocker", "message": "m"}]}, "escalate"),
    (_SOFT, {"verdict": "revise", "confidence": 0.9, "findings": []}, "revise"),
    (_SOFT, {"verdict": "reject", "confidence": 0.9, "findings": []}, "escalate"),
])
def test_decide(change, review, action):
    assert autonomy.decide(change, review, rounds=0)[0] == action


def test_decide_stops_revising_after_the_last_round():
    revise = {"verdict": "revise", "confidence": 0.9, "findings": []}
    assert autonomy.decide(_SOFT, revise,
                           rounds=autonomy.AUTO_MAX_ROUNDS)[0] == "escalate"


def _run(changes, reviews, revise=None, rereview=None):
    """clear_draft with scripted answers: `changes` per round, `reviews` after
    each revision."""
    changes, reviews = iter(changes), iter(reviews)
    return autonomy.clear_draft(
        "spec-0", {"verdict": "revise", "confidence": 0.9,
                   "findings": [{"severity": "suggestion", "message": "tighten it"}]},
        assess=lambda spec: (next(changes), {}),
        revise=revise or (lambda spec, instr: spec[:-1] + str(int(spec[-1]) + 1)),
        rereview=rereview or (lambda spec: next(reviews)),
    )


def test_clear_draft_revises_then_accepts():
    out = _run([_SOFT, _SOFT], [_APPROVE])
    assert out["action"] == "accept" and out["rounds"] == 1 and out["spec"] == "spec-1"


def test_clear_draft_reassesses_after_a_revision():
    """A revision that turns a SOFT draft into a HARD one is escalated."""
    out = _run([_SOFT, _HARD], [_APPROVE])
    assert out["action"] == "escalate" and "HARD gate" in out["reason"]
    assert out["change"] is _HARD


def test_clear_draft_escalates_when_the_planner_is_unavailable():
    def down(spec, instr):
        raise RuntimeError("no key")
    out = _run([_SOFT], [], revise=down)
    assert out["action"] == "escalate" and out["reason"] == "revise unavailable: no key"


def test_clear_draft_escalates_when_the_re_review_is_unavailable():
    out = _run([_SOFT], [None])
    assert out["action"] == "escalate"
    assert out["reason"] == "re-review unavailable: H' gave no usable answer"


def test_clear_draft_escalates_with_the_reason_when_the_re_review_raises():
    """H' raises RuntimeError when the provider refuses; that used to escape
    clear_draft -- and the cockpit's Draft callback -- as a traceback."""
    def refused(spec):
        raise RuntimeError("the provider refused: Error code: 401")
    out = _run([_SOFT], [], rereview=refused)
    assert out["action"] == "escalate"
    assert out["reason"] == "re-review unavailable: the provider refused: Error code: 401"


# ---- with an accepted state: the cockpit measures against it, and records ----

def _track(root):
    from engine import accepted, parser
    accepted.accept_all(parser.load_nodes(root), root, by="setup")


def _agent_breaks_util(root):
    """What an agent does headless: edit the file, no Save, no dialog."""
    spec = root / "util" / "SPEC.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("log()", "write(line)"),
                    encoding="utf-8")


def test_save_asks_about_a_hard_change_an_agent_left_pending(graph_root, monkeypatch):
    """On disk the edit is a typo fix (NONE). Against the accepted state it still
    carries the agent's unaccepted removal of log() -- that is what H must see."""
    _track(graph_root)
    _agent_breaks_util(graph_root)
    asked = []
    monkeypatch.setattr(app.messagebox, "askyesno",
                        lambda title, msg: asked.append(msg) or True)
    text = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    cockpit = _SaveCockpit(graph_root, "util", text.rstrip() + "\nTypo fixed.\n")
    cockpit.save_spec()
    [question] = asked
    assert "log()" in question and "ACCEPTED state" in question
    assert "Recorded as accepted by H" in cockpit.said
    from engine import accepted, parser
    assert accepted.pending(parser.load_nodes(graph_root), graph_root) == []


def test_d2_records_what_h_prime_cleared(graph_root):
    _track(graph_root)
    draft = ("---\nid: api.store\nparent: api\nkind: component\n"
             "contract:\n  provides: [\"keep(item)\"]\n"
             "depends_on: []\ncode: [\"api/store/*.py\"]\nstatus: specd\n---\n\n# Store\n")
    _Cockpit(graph_root)._d2_draft("keep items", "api.store", draft, _APPROVE)
    [entry] = [e for e in _log(graph_root) if e.get("action") == "accepted"]
    assert entry["actor"] == "H'" and entry["node"] == "api.store"


def test_d2_escalates_a_draft_over_a_pending_hard_change(graph_root):
    """An approved, harmless-looking draft must not launder the agent's change."""
    _track(graph_root)
    _agent_breaks_util(graph_root)
    text = (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    out = _Cockpit(graph_root)._d2_draft("tidy", "util", text + "\nTidied.\n", _APPROVE)
    assert "HARD gate" in out and "consumed by api.hello" in out


# ---- a failed model call ends as guidance, not a traceback (stub clients) ----

class _DraftCockpit(_Cockpit):
    """app.Cockpit.draft without Tk, with the real planner and H' behind stub
    clients: a fixed intent and target, and everything it says."""
    draft = app.Cockpit.draft
    _review = app.Cockpit._review
    _semantic = app.Cockpit._semantic
    _run = None                      # no run in progress: Draft is not locked
    _chain = None                    # nor Codex Affected
    _run_busy = app.Cockpit._run_busy

    def __init__(self, root, level):
        super().__init__(root)
        self.config_data.update(draft_gate=level, semantic_match=False)
        self.input, self.guidance, self.view, self.said = "input", "guidance", "view", {}

    def _target(self):
        return "api.store"

    def _get(self, _widget):
        return "keep items"

    def _set(self, widget, text=""):
        self.said[widget] = text


_STORE = json.dumps({"contract": {"provides": ["keep(item)"]}, "code": ["api/store/*.py"],
                     "body": "# Store"})


def _planner_answers(monkeypatch):
    monkeypatch.setattr(planner, "_client",
                        lambda *_: _client_answering(_Resp(_STORE, "tool_calls")))


def test_draft_says_why_the_planner_is_unavailable(graph_root, monkeypatch):
    monkeypatch.setattr(planner, "_client", _refusing)
    cockpit = _DraftCockpit(graph_root, level=1)
    cockpit.draft()
    said = cockpit.said["guidance"]
    assert said.startswith("Draft unavailable:\nthe provider refused")
    assert "User not found" in said


@pytest.mark.parametrize("level", [1, 2])
def test_draft_says_why_h_prime_did_not_review_it(graph_root, monkeypatch, level):
    """It used to say nothing: the draft looked reviewed-and-fine, and at D2 the
    missing auto-clear went unexplained."""
    _planner_answers(monkeypatch)
    monkeypatch.setattr(reviewer, "_client", _refusing)
    cockpit = _DraftCockpit(graph_root, level)
    cockpit.draft()
    said = cockpit.said["guidance"]
    assert "AI draft for `api.store`" in said
    assert "H' review unavailable: the provider refused" in said
    assert ("D2 did not run" in said) is (level == 2)


@pytest.mark.parametrize("answer,said", [
    (_Resp('{"verdict": "appr', "length"),
     "H' review unavailable: the answer was cut off at the model's output limit"),
    (_Resp(None, "stop"), "H' gave no usable answer. The draft is unreviewed"),
])
def test_draft_says_what_became_of_the_review(graph_root, monkeypatch, answer, said):
    _planner_answers(monkeypatch)
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_answering(answer))
    cockpit = _DraftCockpit(graph_root, level=1)
    cockpit.draft()
    assert said in cockpit.said["guidance"]


@pytest.mark.parametrize("refused,step", [("planner", "revise"), ("reviewer", "re-review")])
def test_d2_escalates_with_the_providers_reason(graph_root, monkeypatch, refused, step):
    """H' asks for a revision; then P (revise) or H' itself (re-review) is refused."""
    if refused == "planner":
        monkeypatch.setattr(planner, "_client", _refusing)
    else:
        _planner_answers(monkeypatch)
    monkeypatch.setattr(reviewer, "_client", _refusing)
    draft = ("---\nid: api.store\nparent: api\nkind: component\n"
             "contract:\n  provides: [\"keep(item)\"]\n"
             "depends_on: []\ncode: [\"api/store/*.py\"]\nstatus: specd\n---\n\n# Store\n")
    revise = {"verdict": "revise", "confidence": 0.9,
              "findings": [{"severity": "suggestion", "message": "name the error"}]}
    out = _DraftCockpit(graph_root, level=2)._d2_draft("keep items", "api.store", draft, revise)
    assert out.startswith(f"D2 -> ESCALATED to you: {step} unavailable: the provider refused")


# ---- the two controls in the cockpit ---------------------------------------------
#
# The slider is the DRAFT gate (D0..D2) and nothing else. The delegation acts on
# PENDING HARD changes and is a per-project switch; a run is not a level at all.

def test_the_slider_offers_the_draft_gate_and_nothing_else():
    import inspect
    build = inspect.getsource(app.Cockpit.__init__)
    assert "to=autonomy.DRAFT_MAX" in build, "the slider must end at the draft gate"
    assert "range(autonomy.DRAFT_MAX + 1)" in build, "one tick per offered level"
    label = inspect.getsource(app.Cockpit._render_autonomy)
    assert "not built" not in label, "runs are built; the cockpit must not say otherwise"
    assert "(the draft gate)" in label
    snap = inspect.getsource(app.Cockpit._on_autonomy)
    assert "min(lvl, autonomy.DRAFT_MAX)" in snap


class _DelegationCockpit:
    """Just enough of app.Cockpit to work the delegation switch without Tk."""
    _on_delegation = app.Cockpit._on_delegation
    _render_delegation = app.Cockpit._render_delegation

    class _Var:
        def __init__(self, value=False):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class _Label:
        def __init__(self):
            self.text = ""

        def config(self, text):
            self.text = text

    def __init__(self, root, wanted):
        self.root_dir = str(root)
        self.delegation = self._Var()
        self.delegation_box, self.delegation_label = object(), self._Label()
        self.guidance, self.said = object(), ""
        self._render_delegation()
        self.delegation.set(wanted)

    def _set(self, _where, text):
        self.said = text


def test_h_delegates_from_the_cockpit_and_it_is_recorded(graph_root, monkeypatch):
    monkeypatch.setattr(app.messagebox, "askyesno", lambda *a, **k: True)
    cockpit = _DelegationCockpit(graph_root, True)
    cockpit._on_delegation()
    assert autonomy.delegated(graph_root)
    assert _log(graph_root)[-1]["action"] == "delegation" and _log(graph_root)[-1]["actor"] == "H"
    assert "H' may accept" in cockpit.delegation_label.text
    assert "Requests" in cockpit.said


def test_a_declined_delegation_changes_nothing(graph_root, monkeypatch):
    asked = []
    monkeypatch.setattr(app.messagebox, "askyesno",
                        lambda *a, **k: asked.append(a) or False)
    cockpit = _DelegationCockpit(graph_root, True)
    cockpit._on_delegation()
    assert asked, "delegating must be asked for, once"
    assert not autonomy.delegated(graph_root) and cockpit.delegation.get() is False


def test_taking_it_back_is_not_asked_about(graph_root, monkeypatch):
    autonomy.set_delegation(graph_root, True, by="setup")
    monkeypatch.setattr(app.messagebox, "askyesno",
                        lambda *a, **k: pytest.fail("revoking needs no confirmation"))
    cockpit = _DelegationCockpit(graph_root, False)
    cockpit._on_delegation()
    assert not autonomy.delegated(graph_root)
    assert "yours" in cockpit.delegation_label.text


def test_the_switch_shows_what_the_project_says_not_what_was_clicked(graph_root):
    """`cli.py delegate` and a run's setup write the same file; opening a project
    must read it."""
    autonomy.set_delegation(graph_root, True, by="cli")
    cockpit = _DelegationCockpit(graph_root, False)
    cockpit._render_delegation()
    assert cockpit.delegation.get() is True


# ---- Draft over an existing spec (the newcomer's first container) ---------------

@pytest.mark.parametrize("node,asks", [
    ({"contract": {"provides": []}, "code": []}, False),          # a fresh skeleton
    ({"contract": {}, "code": []}, False),
    ({"contract": {"invariants": ["code layout ..."]}, "code": []}, True),   # seeded container
    ({"contract": {"provides": ["log()"]}, "code": []}, True),
    ({"contract": {}, "code": ["svc/pyproject.toml"]}, True),
])
def test_only_a_spec_with_substance_is_worth_asking_about(node, asks):
    """A question asked about every new node is a question nobody reads."""
    assert app.Cockpit._has_substance(node) is asks


class _DraftOver:
    """Just enough of the cockpit to press Draft on a node that has a spec."""
    draft = app.Cockpit.draft
    _has_substance = staticmethod(app.Cockpit._has_substance)
    _run = None                      # no run in progress: Draft is not locked
    _chain = None                    # nor Codex Affected
    _run_busy = app.Cockpit._run_busy

    def __init__(self, nodes, intent="log things"):
        self.nodes, self.intent, self.said = nodes, intent, ""
        self.input = self.view = self.guidance = object()
        self.config_data = {"planner_model": "m"}
        self._last_intent = None

    def _get(self, _w):
        return self.intent

    def _target(self):
        return "util"

    def _set(self, where, text):
        self.said = text


def test_draft_over_a_seeded_container_asks_first(graph_root, monkeypatch):
    """Run 12's floor: a container whose layout invariants came from the archetype.
    Drafting regenerates, and on a young project nothing is accepted yet, so the
    lines would vanish with no change set to catch it."""
    asked = []
    monkeypatch.setattr(app.messagebox, "askyesno",
                        lambda *a, **k: asked.append(k.get("default")) or False)
    called = []
    monkeypatch.setattr(planner, "draft_spec", lambda *a, **k: called.append(1) or "x")
    cockpit = _DraftOver({"util": {"contract": {"invariants": ["code layout ..."]},
                                   "parent": "app", "kind": "container"}})
    cockpit.draft()
    assert asked and not called, "the planner must not run when the answer is no"
    assert "Revise" in cockpit.said and "util" in cockpit.said


def test_draft_on_an_empty_skeleton_just_drafts(graph_root, monkeypatch):
    monkeypatch.setattr(app.messagebox, "askyesno",
                        lambda *a, **k: pytest.fail("an empty skeleton loses nothing"))
    monkeypatch.setattr(planner, "draft_spec", lambda *a, **k: "---\nid: util\n---\n")
    monkeypatch.setattr(app.capability, "build_registry", lambda _n: [])
    monkeypatch.setattr(app.capability, "find", lambda *a, **k: [])
    cockpit = _DraftOver({"util": {"contract": {"provides": []}, "parent": "app",
                                   "kind": "component"}})
    cockpit._semantic = lambda: (None, None)
    cockpit._spine = lambda _p: {}
    cockpit._request_targets = lambda: {"ARCHITECTURE.md"}
    cockpit._assess = lambda _nid, _spec: None       # the change set has its own tests
    cockpit._review = lambda *_a, **_k: None
    cockpit.autonomy = type("V", (), {"get": staticmethod(lambda: 0)})()
    cockpit.arch = ""
    cockpit.draft()
    assert "AI draft for `util`" in cockpit.said
