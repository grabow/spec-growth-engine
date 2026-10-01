"""Import-edge detection per language (Java, Kotlin, Dart, Python, TS).

Each test builds a tiny owned-file set and asserts which cross-file import
edges the evidence scanner recovers. Edges are (importer_abs, imported_abs)."""
from pathlib import Path

import pytest

from engine import evidence
from tests.conftest import write_spec


def _edge_names(ev, root):
    """Return edges as ('rel/importer', 'rel/imported') for readable asserts."""
    out = set()
    for a, b in ev["edges"]:
        ra = str(a).replace(str(root) + "/", "")
        rb = str(b).replace(str(root) + "/", "")
        out.add((ra, rb))
    return out


# --------------------------------------------------------------------- Java --
def test_java_fqn_and_wildcard_imports(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["cli", "greet"]}, code=[])
    write_spec(tmp_path / "cli", id="cli", parent="app", kind="container",
               contract={"provides": ["run()"]}, code=["src/app/App.java"])
    write_spec(tmp_path / "greet", id="greet", parent="app", kind="component",
               contract={"provides": ["greet()"]}, code=["src/app/greet/**"])
    (tmp_path / "src" / "app" / "greet").mkdir(parents=True)
    (tmp_path / "src" / "app" / "App.java").write_text(
        "package app;\n"
        "import app.greet.Greeter;\n"
        "public final class App { public static void main(String[] a){ Greeter.run(); } }\n",
        encoding="utf-8")
    (tmp_path / "src" / "app" / "greet" / "Greeter.java").write_text(
        'package app.greet;\npublic final class Greeter { public static void run(){} }\n',
        encoding="utf-8")
    nodes = {"cli": {"code": ["src/app/App.java"]},
             "greet": {"code": ["src/app/greet/**"]}}
    ev = evidence.build_evidence(nodes, tmp_path)
    edges = _edge_names(ev, tmp_path)
    assert ("src/app/App.java", "src/app/greet/Greeter.java") in edges

    # wildcard import resolves to every owned file in the package
    (tmp_path / "src" / "app" / "App.java").write_text(
        "package app;\nimport app.greet.*;\npublic final class App {}\n", encoding="utf-8")
    ev = evidence.build_evidence(nodes, tmp_path)
    assert ("src/app/App.java", "src/app/greet/Greeter.java") in _edge_names(ev, tmp_path)


# ------------------------------------------------------------------- Kotlin --
def test_kotlin_import_by_decl_name(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Main.kt").write_text(
        "package app\nimport app.greet.greeter\nfun main(){ greeter() }\n", encoding="utf-8")
    (tmp_path / "src" / "Greet.kt").write_text(
        "package app.greet\nfun greeter() { println(\"hi\") }\n", encoding="utf-8")
    nodes = {"main": {"code": ["src/Main.kt"]}, "greet": {"code": ["src/Greet.kt"]}}
    ev = evidence.build_evidence(nodes, tmp_path)
    assert ("src/Main.kt", "src/Greet.kt") in _edge_names(ev, tmp_path)


# --------------------------------------------------------------------- Dart --
def test_dart_relative_and_package_imports(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    (tmp_path / "lib" / "src").mkdir(parents=True)
    (tmp_path / "lib" / "main.dart").write_text(
        "import 'src/greet.dart';\nimport 'package:demo/util.dart';\n"
        "void main(){ greet(); }\n", encoding="utf-8")
    (tmp_path / "lib" / "src" / "greet.dart").write_text(
        "void greet(){ print('hi'); }\n", encoding="utf-8")
    (tmp_path / "lib" / "util.dart").write_text("int x = 1;\n", encoding="utf-8")
    nodes = {"main": {"code": ["lib/main.dart"]},
             "greet": {"code": ["lib/src/greet.dart"]},
             "util": {"code": ["lib/util.dart"]}}
    ev = evidence.build_evidence(nodes, tmp_path)
    edges = _edge_names(ev, tmp_path)
    assert ("lib/main.dart", "lib/src/greet.dart") in edges   # relative
    assert ("lib/main.dart", "lib/util.dart") in edges        # package:demo/...


# ------------------------------------------------------------------- Python --
def test_python_absolute_and_relative_imports(tmp_path):
    pkg = tmp_path / "app"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "main.py").write_text(
        "from app.greet import greeter\nfrom .sub import helper\n", encoding="utf-8")
    (pkg / "greet.py").write_text("def greeter():\n    pass\n", encoding="utf-8")
    (pkg / "sub" / "helper.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    nodes = {"main": {"code": ["app/main.py"]},
             "greet": {"code": ["app/greet.py"]},
             "helper": {"code": ["app/sub/helper.py"]}}
    ev = evidence.build_evidence(nodes, tmp_path)
    edges = _edge_names(ev, tmp_path)
    assert ("app/main.py", "app/greet.py") in edges          # absolute from-import
    assert ("app/main.py", "app/sub/helper.py") in edges     # relative from . import


def test_python_plain_import(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "main.py").write_text("import app.greet\n", encoding="utf-8")
    (tmp_path / "app" / "greet.py").write_text("x = 1\n", encoding="utf-8")
    nodes = {"main": {"code": ["app/main.py"]}, "greet": {"code": ["app/greet.py"]}}
    ev = evidence.build_evidence(nodes, tmp_path)
    assert ("app/main.py", "app/greet.py") in _edge_names(ev, tmp_path)


# ------------------------------------------ external imports must be ignored --
def test_external_imports_ignored(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "import os\nimport requests\nfrom collections import defaultdict\n", encoding="utf-8")
    nodes = {"main": {"code": ["app/main.py"]}}
    ev = evidence.build_evidence(nodes, tmp_path)
    assert ev["edges"] == []


# ---- build output is never owned --------------------------------------------
#
# Found by an agent run: a `**` glob owned 12 .pyc files and inflated the report
# from 21 owned files to 33. The orphan scan already skipped those directories;
# glob resolution did not, so the two disagreed about what a file is.

def _node(globs):
    return {"id": "n", "kind": "component", "parent": "app", "code": globs}


def test_ownership_skips_build_output(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("X = 1\n", encoding="utf-8")
    cache = tmp_path / "src" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-312.pyc").write_bytes(b"\x00\x01")
    owned = evidence.resolve_node_files(_node(["src/**"]), str(tmp_path))
    assert [p.rsplit("/", 1)[-1] for p in owned] == ["a.py"]


def test_running_the_tests_must_not_change_what_a_node_owns(tmp_path):
    """The property behind the rule: ownership is about AUTHORED files. If a
    generated .pyc counted, a node's ownership -- and the gate's numbers --
    would depend on whether the test suite had been run yet."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("X = 1\n", encoding="utf-8")
    before = evidence.resolve_node_files(_node(["src/**"]), str(tmp_path))
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "a.pyc").write_bytes(b"\x00")
    assert evidence.resolve_node_files(_node(["src/**"]), str(tmp_path)) == before


@pytest.mark.parametrize("directory", ["node_modules", ".venv", "target", "dist", ".sge"])
def test_every_excluded_directory_is_really_skipped(directory, tmp_path):
    d = tmp_path / "src" / directory
    d.mkdir(parents=True)
    (d / "x.py").write_text("X = 1\n", encoding="utf-8")
    assert evidence.resolve_node_files(_node(["src/**"]), str(tmp_path)) == []


def test_spec_files_stay_owned_so_over_claiming_is_still_visible(tmp_path):
    """Deliberately NOT excluded: claiming a spec file is an authoring mistake,
    and the `code: ["**"]` detection in drift depends on seeing it."""
    (tmp_path / "SPEC.md").write_text("---\nid: n\n---\n", encoding="utf-8")
    owned = evidence.resolve_node_files(_node(["**"]), str(tmp_path))
    assert any(p.endswith("SPEC.md") for p in owned)


def test_the_exclusion_list_has_exactly_one_definition():
    """It had two, and they had already diverged: one knew `.sge` and `venv`,
    the other did not."""
    from engine import attribution, drift
    assert drift._EXCLUDE is evidence.EXCLUDED_DIRS
    source = Path(attribution.__file__).read_text(encoding="utf-8")
    assert "_EXCLUDE = {" not in source, "attribution redefines the exclusion list"


# ---- one ownership line: the most specific owner wins ---------------------------

def _line(tmp_path, sub_parent="svc.rules"):
    """svc.rules owns svc/rules/**; a second node owns one file inside it."""
    def spec(rel, body):
        p = tmp_path / rel / "SPEC.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\n{body}---\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("# A\n", encoding="utf-8")
    spec(".", "id: app\nparent: null\nkind: system\ncontract: {purpose: x}\ncode: []\n")
    spec("svc", "id: svc\nparent: app\nkind: container\ncontract: {purpose: y}\ncode: []\n")
    spec("svc/rules", "id: svc.rules\nparent: svc\nkind: component\n"
                      "contract: {provides: ['step()']}\ncode: ['svc/rules/**/*.py']\n")
    spec("svc/angle", f"id: svc.angle\nparent: {sub_parent}\nkind: component\n"
                      "contract: {provides: ['angle()']}\ncode: ['svc/rules/src/angle.py']\n")
    src = tmp_path / "svc" / "rules" / "src"
    src.mkdir(parents=True)
    (src / "angle.py").write_text("def angle():\n    return 45\n", encoding="utf-8")
    (src / "step.py").write_text("from .angle import angle\n", encoding="utf-8")
    from engine import parser
    return parser.load_nodes(tmp_path)


def test_a_sub_component_carves_its_file_out_of_its_parent(tmp_path):
    """core.rules.angle owning one file of core/src/**/rules/** must not need
    core.rules' glob narrowed by hand: on one ownership line the deeper wins."""
    from engine import context, drift
    nodes = _line(tmp_path)
    owners = evidence.ownership_map(nodes, str(tmp_path))
    angle = str((tmp_path / "svc/rules/src/angle.py").resolve())
    step = str((tmp_path / "svc/rules/src/step.py").resolve())
    assert owners[angle] == {"svc.angle"} and owners[step] == {"svc.rules"}
    report = drift.run(nodes, str(tmp_path))
    assert "ownership conflict" not in report and "HARD errors: 0" in report
    parent = context.assemble(nodes, "", "svc.rules", str(tmp_path))
    own = parent.split("# Own code", 1)[1].split("# Dependency contracts", 1)[0]
    assert "step.py" in own and "angle.py" not in own        # the sub-component's now
    child = context.assemble(nodes, "", "svc.angle", str(tmp_path))
    assert "def angle()" in child


def test_owners_on_different_lines_still_conflict(tmp_path):
    """Not related -- a sibling claiming the same file -- stays a HARD conflict."""
    from engine import drift
    nodes = _line(tmp_path, sub_parent="svc")                # svc.angle: a sibling now
    report = drift.run(nodes, str(tmp_path))
    assert "ownership conflict: svc/rules/src/angle.py owned by ['svc.angle', 'svc.rules']" \
        in report
