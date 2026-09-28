"""Per-container code-layout conventions (light 'archetypes').

A container is the C4 technology boundary: it declares its language + build tool +
code-layout convention as `contract.invariants`, which the Spine carries down to
its components (so the planner derives each component's `code` globs from it). When
you create a container node, the cockpit can seed those invariant lines from this
catalog.

The text is language-specific but lives only as invariant *prose* -- the engine
stays agnostic. `{container}` is substituted (by engine.nodes) with the container's
project-root-relative path. A system may be polyglot: each container picks its own.

A COMPONENT OWNS ITS OWN TESTS. Every entry therefore says where that language
puts them, because a test file no node owns is an orphan and blocks the gate --
and because per-node test attribution (engine/attribution.py) uses ownership as
its first route. Where the tests live differs per language and sometimes per
project, which is exactly why it is a container decision and not a global rule.
"""
from __future__ import annotations

FREEFORM = "freeform"

# key -> (label, [invariant line templates with {container}])
CATALOG: dict[str, tuple[str, list[str]]] = {
    "java-maven-single": ("Java / Maven (single module)", [
        "Implementation language is Java, built with Maven (this container's stack).",
        "`{container}` is ONE Maven module (`{container}/pom.xml`, packaging jar); no Maven submodules.",
        "Code layout (code tree separate from spec tree) -- component `{container}.<name>` owns "
        "`{container}/src/main/java/**/<name>/**`; globs are project-root-relative.",
        "A component owns its own tests: component `{container}.<name>` also owns "
        "`{container}/src/test/java/**/<name>/**`.",
        "An entry-point class in the ROOT package (`{container}/src/main/java/<pkg>/Main.java`, "
        "the Spring-Boot `Application.java` pattern) sits above the component directories and is "
        "covered by no component glob: the component that owns the entry point names it "
        "explicitly. A main class inside a component package needs nothing extra.",
        "The container owns only its build manifest (`{container}/pom.xml`); a component never has an empty code glob.",
    ]),
    "python-uv-src": ("Python / uv (src layout)", [
        "Implementation language is Python, managed with uv (this container's stack).",
        "`{container}` is ONE uv project (`{container}/pyproject.toml`).",
        "Code layout (code tree separate from spec tree) -- component `{container}.<name>` owns "
        "`{container}/src/**/<name>/**`; globs are project-root-relative.",
        "A component owns its own tests. Flat pytest layout (the common one): component "
        "`{container}.<name>` also owns `{container}/tests/test_<name>*.py`. If this project "
        "groups tests per component instead, it owns `{container}/tests/<name>/**` -- pick ONE "
        "and keep it; a test file no component owns is an orphan.",
        "Package-root files (`{container}/src/<pkg>/__init__.py`, `__main__.py`) are covered by "
        "no component glob, so the component that owns the entry point names them explicitly in "
        "its own `code`. Leaving them unowned makes them orphans and blocks the gate.",
        "The container owns only its build manifest (`{container}/pyproject.toml`); a component never has an empty code glob.",
    ]),
    "node-react": ("TypeScript/JavaScript / npm (React)", [
        "Implementation language is TypeScript/JavaScript, built with npm (this container's stack).",
        "`{container}` is ONE npm package (`{container}/package.json`).",
        "Code layout (code tree separate from spec tree) -- component `{container}.<name>` owns "
        "`{container}/src/<name>/**`; globs are project-root-relative.",
        "A component owns its own tests. Tests are CO-LOCATED here (`foo.test.tsx` next to "
        "`foo.tsx`), so the glob above already covers them. If this project uses a separate "
        "`{container}/tests/` tree instead, the component must own its part of it explicitly.",
        "The package entry point (`{container}/src/index.ts(x)`) is covered by no component glob: "
        "the component that owns the entry point names it explicitly in its own `code`.",
        "The container owns only its build manifest (`{container}/package.json`); a component never has an empty code glob.",
    ]),
    "rust-cargo": ("Rust / Cargo (single crate)", [
        "Implementation language is Rust, built with Cargo (this container's stack).",
        "`{container}` is ONE crate (`{container}/Cargo.toml`).",
        "Code layout (code tree separate from spec tree) -- component `{container}.<name>` owns "
        "`{container}/src/<name>/**`; globs are project-root-relative.",
        "A component owns its own tests. Unit tests are INLINE (`#[cfg(test)] mod tests`), so the "
        "glob above covers them; integration tests live at the crate root, where component "
        "`{container}.<name>` also owns `{container}/tests/<name>*.rs`.",
        "The crate root (`{container}/src/main.rs` or `lib.rs`) is covered by no component glob: "
        "the component that owns the entry point names it explicitly in its own `code`.",
        "The container owns only its build manifest (`{container}/Cargo.toml`); a component never has an empty code glob.",
    ]),
    FREEFORM: ("Freeform (fill in the invariants yourself)", []),
    # NOTE for FREEFORM: nothing is seeded, so remember the rule the other entries
    # encode -- a component owns its own tests, or they become orphans.
}


# key -> (file name, content template). The SAME decision as the invariant lines
# above, written a second time in the build tool's own language: the layout says
# "component `x.<name>` owns `x/src/**/<name>/**`" in prose, the manifest says
# where the package root is in TOML/XML/JSON. Two spellings of one choice, and
# nothing checks that they agree -- so they are seeded together, from here.
#
# This is a FIRST FILE, not a maintained one: the moment C runs, the manifest is
# code like any other, and C owns it -- it sits in the container's own `code`
# glob, which is what "owns" means here. So a seeded manifest is NOT one of the
# files given to a run: run 10 was told it was, needed one line in it (a console
# script the archetype cannot guess -- Cargo derives its binary from the file
# layout, a React container has no console script at all, and Maven needs plugin
# configuration), and correctly stopped rather than edit a given file. Keep each
# template minimal (no pinned versions beyond what a test run needs), because a
# stale template is worse than none.
# `{container}` is the project-root-relative path, `{package}` its last segment.
MANIFESTS: dict[str, tuple[str, str]] = {
    "python-uv-src": ("pyproject.toml", """\
[project]
name = "{package}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package}"]
"""),
    "rust-cargo": ("Cargo.toml", """\
[package]
name = "{package}"
version = "0.1.0"
edition = "2021"

[dependencies]
"""),
    "node-react": ("package.json", """\
{{
  "name": "{package}",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {{
    "test": "vitest run"
  }}
}}
"""),
    "java-maven-single": ("pom.xml", """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>{package}</groupId>
  <artifactId>{package}</artifactId>
  <version>0.1.0</version>
  <properties>
    <maven.compiler.release>21</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
</project>
"""),
}


def manifest(key: str, container_path: str) -> tuple[str, str] | None:
    """(file name, content) for the container's build manifest, or None where the
    archetype seeds none (Freeform, or an unknown key). `container_path` is the
    project-root-relative path of the container, as in the invariant lines."""
    entry = MANIFESTS.get(key)
    if entry is None:
        return None
    name, text = entry
    package = container_path.rsplit("/", 1)[-1].replace("-", "_")
    return name, text.format(container=container_path, package=package)


def labels() -> list[tuple[str, str]]:
    """(key, label) pairs in catalog order, for a picker."""
    return [(key, entry[0]) for key, entry in CATALOG.items()]


def template(key: str) -> list[str]:
    """Raw invariant line templates (with `{container}`) for `key`, or [] if unknown
    / freeform. engine.nodes performs the `{container}` substitution."""
    entry = CATALOG.get(key)
    return list(entry[1]) if entry else []
