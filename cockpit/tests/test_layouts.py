"""Code-layout catalog + container invariant seeding in new_node."""
import frontmatter
import pytest

import layouts
from engine import nodes as nodeops, parser
from tests.conftest import write_spec


def test_catalog_has_labels_and_freeform():
    keys = [k for k, _ in layouts.labels()]
    assert "java-maven-single" in keys
    assert layouts.FREEFORM in keys
    assert layouts.template(layouts.FREEFORM) == []          # freeform seeds nothing


def test_template_lines_carry_container_placeholder():
    lines = layouts.template("java-maven-single")
    assert lines and all(isinstance(s, str) for s in lines)
    assert any("{container}" in s for s in lines)            # substituted by new_node


def test_new_container_seeds_layout_invariants(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": []}, code=[])
    nodes = parser.load_nodes(tmp_path)
    nid, path = nodeops.new_node(
        "app", "backend", "container", nodes,
        layout_invariants=layouts.template("java-maven-single"),
    )
    assert nid == "backend"
    inv = frontmatter.load(path).metadata["contract"]["invariants"]
    assert inv, "container should have seeded invariants"
    assert any("backend/pom.xml" in line for line in inv)    # {container} -> path
    assert all("{container}" not in line for line in inv)    # placeholder substituted


def test_new_component_gets_no_layout_invariants(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": []}, code=[])
    nodes = parser.load_nodes(tmp_path)
    _nid, path = nodeops.new_node("app", "thing", "component", nodes, layout_invariants=None)
    assert frontmatter.load(path).metadata["contract"] == {"provides": []}  # plain skeleton


def test_nested_container_substitutes_dotted_path(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["outer"]}, code=[])
    write_spec(tmp_path / "outer", id="outer", parent="app", kind="container",
               design={"children": []})
    nodes = parser.load_nodes(tmp_path)
    nid, path = nodeops.new_node(
        "outer", "inner", "container", nodes,
        layout_invariants=layouts.template("python-uv-src"),
    )
    assert nid == "outer.inner"
    inv = frontmatter.load(path).metadata["contract"]["invariants"]
    assert any("outer/inner/pyproject.toml" in line for line in inv)  # dotted id -> '/'


# ---- a component owns its own tests -----------------------------------------
#
# A test file no node owns is an orphan and blocks the gate; ownership is also
# attribution's first route. So every seeded layout must say where the tests are.

@pytest.mark.parametrize("key", [k for k, _ in layouts.labels() if k != layouts.FREEFORM])
def test_every_layout_says_where_its_tests_live(key):
    lines = layouts.template(key)
    assert any("owns its own tests" in line for line in lines), key


@pytest.mark.parametrize("key", [k for k, _ in layouts.labels() if k != layouts.FREEFORM])
def test_every_layout_states_the_test_location_concretely(key):
    """Not just the principle -- a planner needs a shape to derive a glob from."""
    joined = " ".join(layouts.template(key))
    assert any(marker in joined for marker in
               ("tests/", "src/test/java", "CO-LOCATED", "INLINE")), key


def test_python_layout_covers_the_flat_pytest_convention():
    """The case that blocked a plain project: tests/test_store.py, not tests/store/."""
    joined = " ".join(layouts.template("python-uv-src"))
    assert "tests/test_<name>*.py" in joined
    assert "tests/<name>/**" in joined          # the per-component form is still offered
    assert "pick ONE" in joined                 # ...but not both at once


# ---- the entry point has an owner -------------------------------------------
#
# Found by an agent run: `src/svc/__init__.py` and `__main__.py` are covered by
# no component glob, so they are HARD orphans, and the two ways out are both
# forbidden (widen a glob) or wrong (leave them unowned). Every language has
# some version of this file; the layout must say who owns it.

@pytest.mark.parametrize("key", [k for k, _ in layouts.labels() if k != layouts.FREEFORM])
def test_every_layout_says_who_owns_the_entry_point(key):
    joined = " ".join(layouts.template(key))
    assert "entry point" in joined, key
    assert "explicitly" in joined, f"{key}: it must say the glob is named explicitly"


def test_python_names_the_package_root_files_that_bite():
    joined = " ".join(layouts.template("python-uv-src"))
    assert "__init__.py" in joined and "__main__.py" in joined


def test_java_says_when_the_rule_does_not_apply():
    """A main class inside a component package is already covered -- claiming
    otherwise would send people hunting for a problem they do not have."""
    joined = " ".join(layouts.template("java-maven-single"))
    assert "inside a component package needs nothing extra" in joined


# ---- the build manifest: the same decision, in the build tool's language ------

def test_every_archetype_that_seeds_a_manifest_is_a_real_one():
    """MANIFESTS is keyed like CATALOG; a key in one and not the other is a typo
    that would silently seed nothing."""
    assert set(layouts.MANIFESTS) <= set(dict(layouts.labels()))
    assert layouts.manifest(layouts.FREEFORM, "svc") is None   # seeds nothing, by design
    assert layouts.manifest("no-such-archetype", "svc") is None


@pytest.mark.parametrize("key,name", [("python-uv-src", "pyproject.toml"),
                                      ("rust-cargo", "Cargo.toml"),
                                      ("node-react", "package.json"),
                                      ("java-maven-single", "pom.xml")])
def test_each_manifest_is_named_by_its_own_build_tool(key, name):
    seeded, text = layouts.manifest(key, "svc")
    assert seeded == name
    assert "{container}" not in text and "{package}" not in text   # substituted
    assert "svc" in text


def test_the_manifest_agrees_with_the_layout_line_it_was_seeded_with():
    """The point of seeding both from one entry: the prose says where the package
    root is, and the manifest must say the same."""
    lines = " ".join(layouts.template("python-uv-src"))
    assert "svc/src/**/<name>/**" in lines.replace("{container}", "svc")
    assert 'packages = ["src/svc"]' in layouts.manifest("python-uv-src", "svc")[1]


def test_a_nested_container_names_itself_not_its_path():
    """`a/b` is the path; the package is `b` -- a package name is not a path."""
    text = layouts.manifest("python-uv-src", "app/store")[1]
    assert 'name = "store"' in text and 'packages = ["src/store"]' in text


def test_a_dash_in_the_name_becomes_an_underscore_for_the_package():
    assert 'packages = ["src/my_store"]' in layouts.manifest("python-uv-src", "my-store")[1]


def test_a_new_container_gets_its_manifest_and_owns_it(graph_root):
    """An unowned file is an orphan and blocks the gate, so the container
    declares what was seeded for it."""
    nodes = parser.load_nodes(graph_root)
    nid, path = nodeops.new_node("app", "svc", "container", nodes,
                                 layout_invariants=layouts.template("python-uv-src"),
                                 manifest=layouts.manifest("python-uv-src", "svc"))
    assert (graph_root / "svc" / "pyproject.toml").is_file()
    assert frontmatter.load(path).metadata["code"] == ["svc/pyproject.toml"]
    from engine import drift
    report = drift.run(parser.load_nodes(graph_root), str(graph_root))
    assert "orphan code" not in report and "gate: pass" in report


def test_an_existing_manifest_is_never_overwritten(graph_root):
    """A container created a second time, or over a project that is already
    there: the file on disk wins, always."""
    (graph_root / "svc").mkdir()
    (graph_root / "svc" / "pyproject.toml").write_text("mine\n", encoding="utf-8")
    nodes = parser.load_nodes(graph_root)
    nodeops.new_node("app", "svc", "container", nodes,
                     manifest=layouts.manifest("python-uv-src", "svc"))
    assert (graph_root / "svc" / "pyproject.toml").read_text(encoding="utf-8") == "mine\n"


def test_without_an_archetype_nothing_is_seeded_and_nothing_is_claimed(graph_root):
    nodes = parser.load_nodes(graph_root)
    _nid, path = nodeops.new_node("app", "svc", "container", nodes)
    assert frontmatter.load(path).metadata["code"] == []
    assert not (graph_root / "svc" / "pyproject.toml").exists()
