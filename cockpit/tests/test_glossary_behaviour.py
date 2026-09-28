"""Behavioural checks for the canonical glossary entry §3.2c (file classification).

Symbol-existence checks are not enough here, and §3.2c is the case that proves
it (AUTONOMY.md §8 predicted this shape): `excluded` names no symbol at all, and
`kinds` WOULD have resolved -- via app.KINDS, a GUI combobox that enforces
nothing. So each claim is checked by constructing the situation and asserting
what the gate actually does.

The NOT BUILT claims are checked too, by asserting the absence of the behaviour.
Those tests are meant to go RED the day someone implements the feature: that is
the signal to update the glossary, which is exactly the drift this file exists
to prevent.
"""
import textwrap

import pytest

from engine import drift, evidence, parser, validate

def _spec(**fields) -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"---\n{lines}\n---\n\n# {fields['id']}\n"


@pytest.fixture()
def project(tmp_path):
    """One node owning src/a/**.

    The manifest is not decoration: the orphan scan is language-aware, so
    without a build manifest (or a glob naming an extension) NOTHING is in
    scope and no orphan can be reported -- drift._scanned_extensions.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    (tmp_path / "SPEC.md").write_text(_spec(
        id="app", parent="null", kind="system", code="[]", status="specd",
        contract="{purpose: root}"), encoding="utf-8")
    node_dir = tmp_path / "a"
    node_dir.mkdir()
    (node_dir / "SPEC.md").write_text(_spec(
        id="app.a", parent="app", kind="component", code='["src/a/**"]',
        status="specd", contract="{purpose: a, provides: [reads a]}"), encoding="utf-8")
    src = tmp_path / "src" / "a"
    src.mkdir(parents=True)
    (src / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    return tmp_path


# ---- BUILT: owned ----------------------------------------------------------

def test_owned_a_file_maps_to_exactly_one_node(project):
    nodes = parser.load_nodes(project)
    owners = evidence.ownership_map(nodes, str(project))
    owned = {p.rsplit("/", 1)[-1]: s for p, s in owners.items()}
    assert owned["a.py"] == {"app.a"}
    assert "gate: pass" in drift.run(nodes, str(project))


# ---- BUILT: orphan ---------------------------------------------------------

def test_orphan_an_unowned_in_scope_file_is_a_hard_error(project):
    (project / "src" / "loose.py").write_text("X = 1\n", encoding="utf-8")
    report = drift.run(parser.load_nodes(project), str(project))
    assert "orphan code (no spec owner)" in report and "loose.py" in report
    assert "gate: BLOCK" in report


def test_build_output_is_not_an_orphan(project):
    """drift._EXCLUDE, the exclusion that IS built."""
    out = project / "target" / "generated"
    out.mkdir(parents=True)
    (out / "Gen.py").write_text("X = 1\n", encoding="utf-8")
    assert "gate: pass" in drift.run(parser.load_nodes(project), str(project))


def test_engine_meta_files_are_not_orphans(project):
    """drift._IGNORE_FILES -- SPEC.md itself must not count as unowned code."""
    (project / "AGENT-NOTES.md").write_text("notes\n", encoding="utf-8")
    report = drift.run(parser.load_nodes(project), str(project))
    for name in ("SPEC.md", "ARCHITECTURE.md", "AGENT-NOTES.md"):
        assert f"orphan code (no spec owner): {name}" not in report


# ---- BUILT: ownership conflict ---------------------------------------------

def test_conflict_two_nodes_owning_one_file_is_a_hard_error(project):
    second = project / "b"
    second.mkdir()
    (second / "SPEC.md").write_text(_spec(
        id="app.b", parent="app", kind="component", code='["src/a/**"]',
        status="specd", contract="{purpose: b, provides: [also a]}"), encoding="utf-8")
    report = drift.run(parser.load_nodes(project), str(project))
    assert "ownership conflict" in report
    assert "['app.a', 'app.b']" in report
    assert "gate: BLOCK" in report


# ---- BUILT: excluded --------------------------------------------------------

def _with_exclusion(project, globs, extra_code='["src/a/**"]'):
    (project / "a" / "SPEC.md").write_text(_spec(
        id="app.a", parent="app", kind="component", code=extra_code,
        excluded=globs, status="specd",
        contract="{purpose: a, provides: [reads a]}"), encoding="utf-8")
    return parser.load_nodes(project)


def test_excluded_removes_a_file_from_the_orphan_scan(project):
    """Generated sources, project scripts, fixtures in the project's own
    language: declared outside the graph, therefore not orphans."""
    (project / "src" / "generated.py").write_text("# generated\nX = 1\n", encoding="utf-8")
    before = drift.run(parser.load_nodes(project), str(project))
    assert "orphan code (no spec owner): src/generated.py" in before

    after = drift.run(_with_exclusion(project, '["src/generated.py"]'), str(project))
    assert "orphan code (no spec owner)" not in after
    assert "gate: pass" in after


def test_exclusions_are_always_counted_in_the_report(project):
    """Permanent by design, so they stay VISIBLE -- otherwise `excluded` becomes
    the quiet way to make the gate stop complaining."""
    assert "excluded: none" in drift.run(parser.load_nodes(project), str(project))
    (project / "src" / "generated.py").write_text("X = 1\n", encoding="utf-8")
    out = drift.run(_with_exclusion(project, '["src/generated.py"]'), str(project))
    assert "excluded: 1 file(s) via 1 declaration(s)" in out


def test_an_exclusion_that_matches_nothing_is_reported(project):
    """A typo or a leftover otherwise stops meaning anything, silently."""
    out = drift.run(_with_exclusion(project, '["src/typo/**"]'), str(project))
    assert "excluded glob matches no file: app.a -> 'src/typo/**'" in out
    assert "gate: pass" in out          # a stale line is a warning, not a blocker


def test_owning_and_excluding_the_same_file_warns_and_ownership_wins(project):
    nodes = _with_exclusion(project, '["src/a/**"]')
    out = drift.run(nodes, str(project))
    assert "is both owned by ['app.a'] and excluded by ['app.a']" in out
    assert "ownership wins" in out and "gate: pass" in out
    owners = evidence.ownership_map(nodes, str(project))
    assert any(f.endswith("a.py") for f in owners)      # still owned


def test_excluding_a_file_does_not_make_it_part_of_the_graph(project):
    """Exclusion REMOVES, it never grants. An excluded file has no owner, so it
    carries no contract and takes part in no import edge."""
    (project / "src" / "gen.py").write_text("from src.a.a import VALUE\n", encoding="utf-8")
    nodes = _with_exclusion(project, '["src/gen.py"]')
    owners = evidence.ownership_map(nodes, str(project))
    assert not any(f.endswith("gen.py") for f in owners)
    ev = evidence.build_evidence(nodes, str(project))
    assert not any("gen.py" in a for a, _ in ev["edges"])


# ---- OUT OF SCOPE: not-yet-specified (a decision, not a gap) ---------------

def test_unmigrated_code_is_indistinguishable_from_a_defect(project):
    """§3.2c: adopting existing code and forgetting a declaration produce the
    SAME hard error with the SAME wording. There is no 'not yet under spec', and
    that is deliberate -- adoption is out of scope (CONCEPT §7b).

    RED here = an adoption class exists. Update §3.2c."""
    legacy = project / "src" / "legacy"
    legacy.mkdir()
    (legacy / "old.py").write_text("X = 1\n", encoding="utf-8")
    (project / "src" / "forgotten.py").write_text("Y = 2\n", encoding="utf-8")
    lines = [l for l in drift.run(parser.load_nodes(project), str(project)).splitlines()
             if "orphan code" in l]
    shapes = {l.split(":")[0].strip() for l in lines}
    assert len(shapes) == 1, f"the two cases are now reported differently: {shapes}"
    assert len(lines) == 2


# ---- NOT ENFORCED: kind ----------------------------------------------------

def test_kind_is_a_convention_not_an_enforced_enum(tmp_path):
    """§3.2 says the four-value list is NOT ENFORCED.

    RED here = kind validation was added. Update §3.2 (and say where it lives)."""
    (tmp_path / "SPEC.md").write_text(_spec(
        id="app", parent="null", kind="banana", code="[]", status="specd",
        contract="{purpose: x}"), encoding="utf-8")
    nodes = parser.load_nodes(tmp_path)
    assert nodes["app"]["kind"] == "banana"
    assert "gate: pass" in validate.run(nodes, str(tmp_path))


def test_status_by_contrast_does_have_an_enforced_enum(tmp_path):
    """The contrast §3.2 draws: status is checked, kind is not."""
    (tmp_path / "SPEC.md").write_text(_spec(
        id="app", parent="null", kind="system", code="[]", status="banana",
        contract="{purpose: x}"), encoding="utf-8")
    report = validate.run(parser.load_nodes(tmp_path), str(tmp_path))
    assert "unknown status 'banana'" in report


# ---- shared is a node property, not a file class ---------------------------

def test_shared_changes_nothing_about_ownership_or_the_gate(project):
    """§3.6: shared is computed for the REGISTRY view only."""
    from engine import capability
    (project / "a" / "SPEC.md").write_text(_spec(
        id="app.a", parent="app", kind="component", code='["src/a/**"]',
        shared="true", status="specd",
        contract="{purpose: a, provides: [reads a]}"), encoding="utf-8")
    nodes = parser.load_nodes(project)
    assert evidence.ownership_map(nodes, str(project))  # still owns its file
    assert "gate: pass" in drift.run(nodes, str(project))
    entry = [e for e in capability.build_registry(nodes) if e["node"] == "app.a"]
    assert entry and entry[0]["shared"] is True


def test_shared_is_also_derived_from_the_id_segment(project):
    from engine import capability
    d = project / "shared"
    d.mkdir()
    (d / "SPEC.md").write_text(_spec(
        id="app.shared", parent="app", kind="component", code="[]",
        status="specd", contract="{purpose: s, provides: [logging]}"), encoding="utf-8")
    reg = capability.build_registry(parser.load_nodes(project))
    assert [e for e in reg if e["node"] == "app.shared"][0]["shared"] is True


# ---- coexistence: the spec root IS the scan root ---------------------------
#
# CONCEPT §7b documents this as the supported way to use the method inside an
# existing repository. It is a property of how the root is chosen, not a
# feature -- which is exactly why it needs a test: nothing in the code says
# "coexistence", so nothing would notice if it broke.

def test_a_sub_root_hides_the_rest_of_the_repository(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='repo'\n", encoding="utf-8")
    for name in ("a.py", "b.py", "c.py"):
        (legacy / name).write_text("X = 1\n", encoding="utf-8")

    new = tmp_path / "apps" / "newthing"
    (new / "src").mkdir(parents=True)
    (new / "pyproject.toml").write_text("[project]\nname='new'\n", encoding="utf-8")
    (new / "src" / "thing.py").write_text("VALUE = 1\n", encoding="utf-8")
    (new / "SPEC.md").write_text(_spec(
        id="new", parent="null", kind="system", code="[]", status="specd",
        contract="{purpose: root}"), encoding="utf-8")
    (new / "thing").mkdir()
    (new / "thing" / "SPEC.md").write_text(_spec(
        id="new.thing", parent="new", kind="component", code='["src/**"]',
        status="specd", contract="{purpose: t, provides: [a value]}"), encoding="utf-8")

    assert "gate: pass" in drift.run(parser.load_nodes(new), str(new))

    # the same tree, scanned from the repository root, is the ADOPTION case
    (tmp_path / "SPEC.md").write_text(_spec(
        id="repo", parent="null", kind="system", code='["legacy/**"]',
        status="specd", contract="{purpose: repo}"), encoding="utf-8")
    whole = drift.run(parser.load_nodes(tmp_path), str(tmp_path))
    assert "gate: BLOCK" in whole and "orphan code (no spec owner)" in whole
