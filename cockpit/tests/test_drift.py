from engine import drift, parser
from tests.conftest import write_spec


def test_parent_child_realization_edge_allowed(tmp_path):
    # cli (container) owns the entry App.ts; cli.hello (child) owns its package.
    # App.ts imports the child's code -> realization (ownership line), NOT a dependency.
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n- TS\n", encoding="utf-8")
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["cli"]}, code=[])
    write_spec(tmp_path / "cli", id="cli", parent="app", kind="container",
               contract={"provides": ["run()"]}, design={"children": ["cli.hello"]},
               code=["cli/src/app.ts"])
    write_spec(tmp_path / "cli" / "hello", id="cli.hello", parent="cli", kind="component",
               contract={"provides": ["hello()"]}, code=["cli/src/hello/cmd.ts"])
    (tmp_path / "cli" / "src" / "hello").mkdir(parents=True)
    (tmp_path / "cli" / "src" / "app.ts").write_text(
        'import { hello } from "./hello/cmd";\nhello();\n', encoding="utf-8")
    (tmp_path / "cli" / "src" / "hello" / "cmd.ts").write_text(
        "export function hello(){ console.log('hi'); }\n", encoding="utf-8")

    nodes = parser.load_nodes(tmp_path)
    out = drift.run(nodes, str(tmp_path))
    assert "undeclared dependency" not in out   # cli -> cli.hello is realization
    assert out.strip().endswith("gate: pass")


def test_undeclared_cross_import_blocks(ts_root):
    nodes = parser.load_nodes(ts_root)
    out = drift.run(nodes, str(ts_root))
    assert "undeclared dependency: checkout -> util" in out
    assert out.strip().endswith("gate: BLOCK")


def test_declared_dependency_passes(ts_root):
    nodes = parser.load_nodes(ts_root)
    nodes["checkout"]["depends_on"] = ["payment", "util"]  # declare the real edge
    out = drift.run(nodes, str(ts_root))
    assert out.strip().endswith("gate: pass")


def test_orphan_language_aware_blocks(ts_root):
    nodes = parser.load_nodes(ts_root)
    nodes["checkout"]["depends_on"] = ["payment", "util"]
    nodes["checkout"]["code"] = ["checkout/checkout.ts"]  # explicit -> orphans detectable
    (ts_root / "checkout" / "extra.ts").write_text("export const x = 1;\n", encoding="utf-8")
    out = drift.run(nodes, str(ts_root))
    assert "orphan code" in out and "extra.ts" in out
    assert out.strip().endswith("gate: BLOCK")


def test_agents_md_never_orphaned(ts_root):
    nodes = parser.load_nodes(ts_root)
    nodes["checkout"]["depends_on"] = ["payment", "util"]
    # Force .md into the scan scope by owning a REAL doc -- not via `*.md`, which
    # would also claim the node's own SPEC.md and is over-claiming in its own right.
    (ts_root / "checkout" / "notes.md").write_text("# notes\n", encoding="utf-8")
    nodes["checkout"]["code"] = ["checkout/*.ts", "checkout/notes.md"]
    (ts_root / "checkout" / "AGENT-NOTES.md").write_text("- mvn lives at /opt\n", encoding="utf-8")
    out = drift.run(nodes, str(ts_root))
    assert "AGENT-NOTES.md" not in out          # accelerator memory is ignored entirely
    assert out.strip().endswith("gate: pass")


def test_orphan_detected_via_build_manifest_with_star_glob(tmp_path):
    # A node owns a package via '**' (no extension in the glob) and there is an
    # unowned .java sibling. Without the manifest-derived scope, '.java' would not
    # be "in scope" and the orphan would slip through (the real bug we hit).
    (tmp_path / "ARCHITECTURE.md").write_text("# Arch\n- Java/Maven\n", encoding="utf-8")
    (tmp_path / "pom.xml").write_text("<project/>\n", encoding="utf-8")  # makes .java in scope
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["feat"]}, code=[])
    write_spec(tmp_path / "feat", id="feat", parent="app", kind="component",
               contract={"provides": ["go()"]}, code=["src/app/feat/**"])
    (tmp_path / "src" / "app" / "feat").mkdir(parents=True)
    (tmp_path / "src" / "app" / "feat" / "Feat.java").write_text(
        "package app.feat;\npublic class Feat {}\n", encoding="utf-8")  # owned
    (tmp_path / "src" / "app" / "Stray.java").write_text(
        "package app;\npublic class Stray {}\n", encoding="utf-8")      # ORPHAN
    nodes = parser.load_nodes(tmp_path)
    out = drift.run(nodes, str(tmp_path))
    assert "orphan code" in out and "Stray.java" in out
    assert "Feat.java" not in out          # owned via the ** glob
    assert out.strip().endswith("gate: BLOCK")


def test_no_manifest_no_glob_extension_scans_nothing(tmp_path):
    # Without a manifest AND without an extension-bearing glob, nothing is in
    # scope -> no orphans. The report must SAY so: a silent pass here is
    # indistinguishable from a clean project (loose.java really is unowned).
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["feat"]}, code=[])
    write_spec(tmp_path / "feat", id="feat", parent="app", kind="component",
               contract={"provides": ["go()"]}, code=["src/feat/**"])
    (tmp_path / "src" / "feat").mkdir(parents=True)
    (tmp_path / "loose.java").write_text("class X {}\n", encoding="utf-8")
    nodes = parser.load_nodes(tmp_path)
    out = drift.run(nodes, str(tmp_path))
    assert "orphan code (no spec owner)" not in out    # nothing scanned, nothing found
    assert "scan scope: EMPTY" in out                  # ...and the report admits it
    assert "scan scope is EMPTY" in out                # as a warning, not just a header
    assert "loose.java" not in out
    assert out.strip().endswith("gate: pass")


def test_build_output_dirs_excluded(ts_root):
    nodes = parser.load_nodes(ts_root)
    nodes["checkout"]["depends_on"] = ["payment", "util"]
    built = ts_root / "dist"
    built.mkdir()
    (built / "bundle.ts").write_text("compiled\n", encoding="utf-8")
    out = drift.run(nodes, str(ts_root))
    assert "bundle.ts" not in out
    assert out.strip().endswith("gate: pass")


# ---- scan scope visibility --------------------------------------------------

def test_scope_is_reported_with_its_source(tmp_path):
    """Where the scanned extensions came from, so an unexpectedly narrow scope
    is visible instead of implied."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["feat"]}, code=[])
    write_spec(tmp_path / "feat", id="feat", parent="app", kind="component",
               contract={"provides": ["go()"]}, code=["src/feat/*.ts"])
    (tmp_path / "src" / "feat").mkdir(parents=True)
    out = drift.run(parser.load_nodes(tmp_path), str(tmp_path))
    assert ".ts (declared)" in out
    assert ".py (from build manifests)" in out


def test_empty_graph_does_not_warn_about_an_empty_scope(tmp_path):
    """A freshly bootstrapped root claims no code at all. Nothing to scan is
    correct there, and warning would make every new project start noisy."""
    write_spec(tmp_path, id="app", parent=None, kind="system", code=[])
    out = drift.run(parser.load_nodes(tmp_path), str(tmp_path))
    assert "scan scope is EMPTY" not in out
    assert "gate: pass" in out


# ---- over-claiming: a glob broad enough to swallow the graph -----------------
#
# `code: ["**"]` leaves no file unowned, which makes every orphan disappear.
# The reliable signature is that it also claims the spec files themselves.

def test_claiming_a_spec_file_as_code_is_hard(ts_root):
    nodes = parser.load_nodes(ts_root)
    nodes["checkout"]["code"] = ["**"]
    out = drift.run(nodes, str(ts_root))
    assert "claims the spec file" in out and "not the graph itself" in out
    assert "gate: BLOCK" in out


def test_claiming_agent_scratch_memory_warns_but_does_not_block(ts_root):
    """A mistake, not a subversion: AGENT-NOTES.md is not the graph."""
    (ts_root / "checkout" / "AGENT-NOTES.md").write_text("- note\n", encoding="utf-8")
    nodes = parser.load_nodes(ts_root)
    nodes["checkout"]["depends_on"] = ["payment", "util"]
    nodes["checkout"]["code"] = ["checkout/*.ts", "checkout/AGENT-NOTES.md"]
    out = drift.run(nodes, str(ts_root))
    assert "it is agent scratch memory" in out
    assert "gate: pass" in out


def test_a_wildcard_only_exclusion_is_hard(ts_root):
    """One line would otherwise disable the orphan check, which is a HARD check."""
    for pattern in ("**", "*", "**/*", "*/**"):
        nodes = parser.load_nodes(ts_root)
        nodes["checkout"]["excluded"] = [pattern]
        out = drift.run(nodes, str(ts_root))
        assert f"excluded glob {pattern!r}" in out and "names nothing" in out, pattern
        assert "gate: BLOCK" in out, pattern


def test_a_named_exclusion_is_still_allowed(ts_root):
    (ts_root / "checkout" / "generated.ts").write_text("export const X = 1;\n", encoding="utf-8")
    nodes = parser.load_nodes(ts_root)
    nodes["checkout"]["depends_on"] = ["payment", "util"]
    nodes["checkout"]["excluded"] = ["checkout/generated.ts"]
    out = drift.run(nodes, str(ts_root))
    assert "names nothing" not in out
    assert "gate: pass" in out


def test_more_excluded_than_owned_is_a_warning(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    write_spec(tmp_path, id="app", parent=None, kind="system", code=[])
    write_spec(tmp_path / "a", id="app.a", parent="app", kind="component",
               contract={"provides": ["go()"]}, code=["src/a.py"],
               excluded=["gen/**"])
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "gen").mkdir()
    for i in range(3):
        (tmp_path / "gen" / f"g{i}.py").write_text("X = 1\n", encoding="utf-8")
    out = drift.run(parser.load_nodes(tmp_path), str(tmp_path))
    assert "more files are excluded (3) than owned (1)" in out
    assert "gate: pass" in out      # a shape worth seeing, not a defect


# ---- a declared dependency before the code exists ---------------------------
#
# From the agent run: writing the SPEC first (step 1 of the loop) and gating
# before the code (step 2) produced "declared dependency without code evidence"
# every time -- correct, but it reads as an error at the exact moment the method
# prescribes. The fact is the same; what it MEANS depends on the status.

def _two_nodes(tmp_path, status):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    write_spec(tmp_path, id="app", parent=None, kind="system", code=[])
    write_spec(tmp_path / "a", id="app.a", parent="app", kind="component",
               contract={"provides": ["go()"]}, code=["src/a.py"],
               depends_on=["app.b"], status=status)
    write_spec(tmp_path / "b", id="app.b", parent="app", kind="component",
               contract={"provides": ["helper()"]}, code=["src/b.py"], status=status)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("X = 1\n", encoding="utf-8")   # no import yet
    (tmp_path / "src" / "b.py").write_text("def helper(): return 1\n", encoding="utf-8")
    return parser.load_nodes(tmp_path)


def test_a_dependency_declared_before_the_code_reads_as_expected(tmp_path):
    out = drift.run(_two_nodes(tmp_path, "specd"), str(tmp_path))
    assert "declared dependency not yet realized: app.a -> app.b" in out
    assert "expected before the code exists" in out
    assert "without code evidence" not in out
    assert "gate: pass" in out


def test_the_same_gap_at_implemented_is_still_a_discrepancy(tmp_path):
    out = drift.run(_two_nodes(tmp_path, "implemented"), str(tmp_path))
    assert "declared dependency without code evidence: app.a -> app.b" in out
    assert "not yet realized" not in out
