import importlib
import os
import sys


def _fresh_appconfig(tmp_path, monkeypatch):
    monkeypatch.delenv("SGE_PLANNER_MODEL", raising=False)
    monkeypatch.delenv("SGE_CODER_CMD", raising=False)
    monkeypatch.delenv("SGE_SEMANTIC_MATCH", raising=False)
    monkeypatch.delenv("SGE_DRAFT_GATE", raising=False)
    import appconfig
    importlib.reload(appconfig)
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "cockpit.json")
    return appconfig


def test_defaults_when_no_file(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    cfg = ac.load()
    assert cfg["planner_model"] == "z-ai/glm-5.2"
    assert cfg["coder_cmd"] == "codex exec"
    assert cfg["last_root"] == ""


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    ac.save({"planner_model": "m", "coder_cmd": "c x", "last_root": "/p/proj"})
    cfg = ac.load()
    assert cfg["planner_model"] == "m"
    assert cfg["coder_cmd"] == "c x"
    assert cfg["last_root"] == "/p/proj"
    assert cfg["semantic_match"] is True  # default carried through save
    assert cfg["draft_gate"] == 1         # default: D1


def test_load_tolerates_garbage(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    (tmp_path / "cockpit.json").write_text("{ not json", encoding="utf-8")
    cfg = ac.load()  # must not raise, returns defaults
    assert cfg["planner_model"] == "z-ai/glm-5.2"


# ---- graph view state (per spec root) ---------------------------------------

def test_graph_view_unknown_root_falls_back_to_default(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    collapsed, zoom = ac.graph_view_get(ac.load(), str(tmp_path))
    assert collapsed is None  # None = "nothing stored", caller applies its default
    assert zoom == 1.0


def test_graph_view_survives_save_and_load(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    cfg = ac.load()
    ac.graph_view_set(cfg, str(tmp_path), {"sys.api", "sys.web"}, 0.8)
    ac.save(cfg)
    collapsed, zoom = ac.graph_view_get(ac.load(), str(tmp_path))
    assert collapsed == {"sys.api", "sys.web"}
    assert zoom == 0.8


def test_graph_view_is_per_root(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    cfg = ac.load()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    ac.graph_view_set(cfg, str(a), {"x"}, 0.5)
    ac.graph_view_set(cfg, str(b), {"y"}, 2.0)
    assert ac.graph_view_get(cfg, str(a)) == ({"x"}, 0.5)
    assert ac.graph_view_get(cfg, str(b)) == ({"y"}, 2.0)


def test_graph_view_zoom_is_clamped_both_ways(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    cfg = ac.load()
    ac.graph_view_set(cfg, str(tmp_path), set(), 99.0)
    assert ac.graph_view_get(cfg, str(tmp_path))[1] == ac.ZOOM_MAX
    ac.graph_view_set(cfg, str(tmp_path), set(), 0.001)
    assert ac.graph_view_get(cfg, str(tmp_path))[1] == ac.ZOOM_MIN


def test_graph_view_tolerates_corrupt_entries(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    key = ac._root_key(str(tmp_path))
    cfg = {"graph_view": {key: {"collapsed": "not-a-list", "zoom": "nonsense"}}}
    assert ac.graph_view_get(cfg, str(tmp_path)) == (None, 1.0)
    assert ac.graph_view_get({"graph_view": None}, str(tmp_path)) == (None, 1.0)
    assert ac.graph_view_get({}, str(tmp_path)) == (None, 1.0)


def test_graph_view_keeps_only_the_most_recent_roots(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    cfg = ac.load()
    for i in range(ac._GRAPH_VIEW_LIMIT + 5):
        ac.graph_view_set(cfg, str(tmp_path / f"p{i}"), {f"n{i}"}, 1.0)
    store = cfg["graph_view"]
    assert len(store) == ac._GRAPH_VIEW_LIMIT
    assert ac.graph_view_get(cfg, str(tmp_path / "p0"))[0] is None       # evicted
    assert ac.graph_view_get(cfg, str(tmp_path / "p24"))[0] == {"n24"}   # newest kept


def test_defaults_are_not_shared_between_loads(tmp_path, monkeypatch):
    ac = _fresh_appconfig(tmp_path, monkeypatch)
    first = ac.load()
    ac.graph_view_set(first, str(tmp_path), {"x"}, 1.0)
    assert ac.load()["graph_view"] == {}  # the defaults must not have been mutated


def test_the_gui_can_find_tcl_on_this_interpreter():
    """uv's CPython bundles Tcl/Tk under sys.base_prefix, but inside a venv Tcl
    searches sys.prefix and finds nothing -- `uv run python app.py`, the
    documented start command, died with "Can't find a usable init.tcl" while the
    libraries sat right there. app._locate_bundled_tcl fills the gap."""
    import app
    app._locate_bundled_tcl()
    import tkinter
    assert tkinter.TkVersion >= 8.6


def test_locating_tcl_never_overrides_an_explicit_setting(monkeypatch):
    import app
    monkeypatch.setenv("TCL_LIBRARY", "/somewhere/chosen/by/the/user")
    app._locate_bundled_tcl()
    assert os.environ["TCL_LIBRARY"] == "/somewhere/chosen/by/the/user"


def test_locating_tcl_is_silent_when_nothing_is_bundled(monkeypatch, tmp_path):
    """Homebrew and the system framework build locate their own; the helper must
    not invent a path for them."""
    import app
    monkeypatch.delenv("TCL_LIBRARY", raising=False)
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path))
    app._locate_bundled_tcl()
    assert "TCL_LIBRARY" not in os.environ
