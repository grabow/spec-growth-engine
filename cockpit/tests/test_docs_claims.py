"""A drift gate for the method documents.

validate/drift/lifecycle compare spec against code IN A TARGET PROJECT. Nothing
watches the method documents themselves, so AUTONOMY.md 4 once claimed a D2
auto-clear that was never built while correctly naming the functions around it.

This closes the narrow, checkable part of that hole: every code symbol the
document names must resolve, and every constant it quotes must equal the value
in the code. Prose stays unchecked -- see AUTONOMY.md 8.
"""
import importlib
import re
from pathlib import Path

import pytest

COCKPIT = Path(__file__).resolve().parents[1]
DOC = COCKPIT.parent / "spec-growth-engine" / "AUTONOMY.md"
STATUS = COCKPIT / "STATUS.md"
AGENTS_TEMPLATE = COCKPIT.parent / "spec-growth-engine" / "AGENTS.template.md"


def _implemented_section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## 4. What is implemented today")
    return text[start:text.index("## 5. ", start)]


def _resolve(dotted: str):
    """'agent.reviewer.review_draft' / 'app.Cockpit._d2_draft' -> the object."""
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        for attr in parts[split:]:
            obj = getattr(obj, attr)   # AttributeError = the claim is stale
        return obj
    raise ImportError(f"no importable module prefix in {dotted!r}")


SYMBOLS = re.findall(r"^\S.*?\s{2,}((?:app|agent|engine|capability|cli|orchestrate|runlog)\.[\w.]+)\s*$",
                     _implemented_section(), re.M)
CONSTANTS = re.findall(r"^((?:app|engine)\.[\w.]*[A-Z][A-Z_]*) = (\S+)$",
                       _implemented_section(), re.M)


def test_the_claim_table_was_actually_found():
    """Guard the parser: a reformat that silently matches nothing would make
    every check below vacuously pass."""
    assert len(SYMBOLS) >= 5, f"claim table not parsed (found {SYMBOLS})"
    assert len(CONSTANTS) >= 3, f"constants block not parsed (found {CONSTANTS})"


@pytest.mark.parametrize("dotted", SYMBOLS)
def test_every_named_symbol_exists(dotted):
    assert _resolve(dotted) is not None


@pytest.mark.parametrize("name,quoted", CONSTANTS)
def test_every_quoted_constant_matches_the_code(name, quoted):
    actual = _resolve(name)
    assert str(actual) == quoted, f"{name}: doc says {quoted}, code says {actual}"


def test_documented_switches_match_the_code():
    """The slider stops at the draft gate's D2; the delegation is a per-project
    switch, not a grade above it; a run is not a level at all."""
    from engine import autonomy
    doc = " ".join(_implemented_section().split())
    assert "the slider offers D0, D1, D2" in doc
    assert "the delegation is a switch per project" in doc
    assert "a run is an operating mode" in doc
    assert autonomy.DRAFT_MAX == 2 and sorted(autonomy.NAMES) == [0, 1, 2]



def test_duplicate_consolidation_is_not_claimed_as_autonomous():
    """The specific false claim this file exists because of: capability
    duplicates are reported to a human, never cleared by H'."""
    import app
    body = DOC.read_text(encoding="utf-8")
    assert "H' never clears it" in body
    # and the code still has no draft-gate branch around the duplicate report
    source = Path(app.__file__).read_text(encoding="utf-8")
    show = source[source.index("def show_duplicates"):]
    show = show[:show.index("\n    def ", 1)]
    assert "autonomy" not in show.lower()


# ---- STATUS.md: the module inventory, checked in BOTH directions ------------
#
# One direction alone is not enough: checking only "listed -> exists" lets the
# list go stale upwards (eight modules were built without ever being added), and
# checking only "exists -> listed" lets a removed module linger.

def _status_module_block() -> str:
    text = STATUS.read_text(encoding="utf-8")
    start = text.index("## Modules")
    return text[start:text.index("\n## ", start + 1)]


def _listed_modules() -> set[str]:
    """Parse the module block. Package headers (`engine/`, `agent/`) sit at
    column 0 and own the indented lines below them; a module at column 0 is a
    top-level one. Headers carry a trailing comment, so match the first token."""
    listed: set[str] = set()
    prefix = ""
    for line in _status_module_block().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        token = stripped.split()[0]
        at_margin = line[:1] not in (" ", "\t")
        if at_margin and token.endswith("/"):
            prefix = token
        elif token.endswith(".py"):
            listed.add(("" if at_margin else prefix) + token)
    return listed


def _real_modules() -> set[str]:
    found = set()
    for path in list(COCKPIT.glob("*.py")) + list(COCKPIT.glob("engine/*.py")) \
            + list(COCKPIT.glob("agent/*.py")):
        if path.name == "__init__.py":
            continue
        found.add(str(path.relative_to(COCKPIT)))
    return found


def test_the_module_block_was_actually_parsed():
    assert len(_listed_modules()) >= 15, f"module block not parsed: {_listed_modules()}"


def test_every_module_listed_in_status_exists():
    missing = sorted(m for m in _listed_modules() if not (COCKPIT / m).exists())
    assert not missing, f"STATUS.md lists modules that do not exist: {missing}"


def test_every_module_that_exists_is_listed_in_status():
    undocumented = sorted(_real_modules() - _listed_modules())
    assert not undocumented, (
        f"modules exist but STATUS.md does not mention them: {undocumented}")


def test_status_does_not_hardcode_a_test_count():
    """The number that rotted last time. It belongs in `uv run pytest -q`."""
    import re
    body = STATUS.read_text(encoding="utf-8")
    counts = re.findall(r"\b(\d+)\s+[Tt]ests?\b", body)
    assert not counts, f"STATUS.md hardcodes a test count ({counts}); quote the command instead"


def test_status_lists_the_real_cli_commands():
    import cli
    body = STATUS.read_text(encoding="utf-8")
    source = Path(cli.__file__).read_text(encoding="utf-8")
    for name in re.findall(r'if args\.cmd == "([a-z-]+)"', source):
        assert name in body, f"cli.py has command {name!r}, STATUS.md does not mention it"


# ---- the glossary: §3.2c must keep saying what the behaviour tests assert ----
#
# The behavioural half lives in test_glossary_behaviour.py. This half binds the
# TEXT to it: if someone builds `excluded` the behaviour test goes red, and if
# someone quietly deletes the NOT BUILT marker instead of updating it, this one
# does. Neither check is enough alone.

GLOSSARY = COCKPIT.parent / "spec-growth-engine" / "SPEC-GROWTH-ENGINE.md"


def _file_classification() -> str:
    text = GLOSSARY.read_text(encoding="utf-8")
    start = text.index("### 3.2c File classification")
    return text[start:text.index("\n### ", start + 1)]


def test_the_file_classification_section_exists():
    assert len(_file_classification()) > 400


@pytest.mark.parametrize("claim", ["owned", "orphan", "conflict"])
def test_built_file_classes_cite_the_code_that_enforces_them(claim):
    block = _file_classification()
    assert claim in block
    assert "engine/evidence.ownership_map" in block and "drift.run" in block


def test_excluded_is_documented_as_built_with_its_code():
    block = _file_classification()
    assert "NOT BUILT -- excluded" not in block, "excluded is built; drop the marker"
    assert "engine/evidence.excluded_map" in block
    assert "never grants" in block, "the REMOVE-not-GRANT semantics must be stated"


def test_tests_are_documented_as_not_an_exclusion_case():
    """The trap this feature invites: excluding tests instead of owning them."""
    assert "NOT a case for `excluded`: TESTS" in _file_classification()


def test_not_yet_specified_is_marked_out_of_scope_not_missing():
    """The fourth class is a DECISION, not a gap. Deleting the note would leave
    the next reader to re-derive whether adoption was rejected or forgotten."""
    assert "OUT OF SCOPE -- not-yet-specified" in _file_classification()


def test_the_hardcoded_exclusion_lists_are_named_correctly():
    """§3.2c names the two hardcoded lists that remain alongside declarable
    exclusions. They must keep existing, or the section describes a mechanism
    that is gone."""
    from engine import drift, evidence
    block = _file_classification()
    for name, value in (("evidence.EXCLUDED_DIRS", evidence.EXCLUDED_DIRS),
                        ("drift._IGNORE_FILES", drift._IGNORE_FILES)):
        assert name.split(".")[1] in block, f"{name} not named in §3.2c"
        assert value, f"{name} is empty"
    # the directories the document lists must be the ones the code excludes
    listed = {d for d in evidence.EXCLUDED_DIRS if d in block}
    missing = sorted(evidence.EXCLUDED_DIRS - listed)
    assert not missing, f"§3.2c does not list excluded directories: {missing}"
    for f in drift._IGNORE_FILES:
        assert f in block, f"§3.2c does not list {f} among the ignored meta files"


def test_kind_is_documented_as_unenforced():
    text = GLOSSARY.read_text(encoding="utf-8")
    section = text[text.index("### 3.2 Node kinds"):text.index("### 3.2a")]
    assert "NOT ENFORCED" in section
    assert "VALID_STATUS" in section   # the contrast it draws


# ---- the waiver model is built: the docs must describe what it enforces --

def _glossary() -> str:
    return GLOSSARY.read_text(encoding="utf-8")


def test_waiver_section_describes_the_enforcement():
    text = _glossary()
    section = text[text.index("### 3.10 Waiver"):text.index("### 3.11")]
    assert "NOT BUILT" not in section, "§3.10 is built; the marker must be gone"
    assert "engine/waivers.issues" in section
    assert "_clean_waiver" in section, "the authorship rule must say where it lives"


@pytest.mark.parametrize("name", ["issues", "open_waivers", "not_done", "summary"])
def test_named_waiver_entry_points_exist(name):
    from engine import waivers
    assert callable(getattr(waivers, name))


def test_every_documented_waiver_type_is_accepted_by_the_code():
    """The four types are canonical in §3.10. A type the code rejects would make
    the documented list a lie in the other direction."""
    from engine import waivers
    text = _glossary()
    section = text[text.index("### 3.10 Waiver"):text.index("### 3.11")]
    for kind in waivers.TYPES:
        assert kind in section, f"{kind} is accepted by the code but not documented"


# ---- STATUS.md: the setup facts, which drift the moment a dependency moves ---
#
# These were checked by hand until they were not. Each one is a claim about a
# file that lives two directories away, which is exactly the kind that rots.

def _status() -> str:
    return STATUS.read_text(encoding="utf-8")


def test_status_lists_the_real_dependencies():
    import tomllib
    with (COCKPIT / "pyproject.toml").open("rb") as fh:
        declared = tomllib.load(fh)["project"]["dependencies"]
    names = [d.split(">")[0].split("=")[0].split("[")[0].strip() for d in declared]
    body = _status()
    missing = [n for n in names if f"`{n}`" not in body]
    assert not missing, f"pyproject declares {missing}, STATUS.md does not list them"


def test_status_quotes_the_pinned_python_version():
    pinned = (COCKPIT / ".python-version").read_text(encoding="utf-8").strip()
    assert f"Python {pinned}" in _status()


def test_status_lists_every_persisted_setting():
    """cockpit.json's keys: a new setting that nobody documents is how the last
    STATUS.md went stale."""
    import appconfig
    body = _status()
    described = {
        "last_root": "last root", "semantic_match": "semantic matching",
        "draft_gate": "draft gate D0-D2", "graph_view": "graph view state",
    }
    undocumented = sorted(set(appconfig._DEFAULTS) - set(described))
    assert not undocumented, f"new cockpit.json settings, not described: {undocumented}"
    for key, phrase in described.items():
        assert phrase in body, f"{key} is persisted but STATUS.md does not mention it"


@pytest.mark.parametrize("prefix", ["waivers:", "scan scope:", "excluded:"])
def test_status_quotes_report_lines_that_really_appear(prefix, tmp_path):
    """STATUS shows sample report headers. They must be real output, not a
    description of output."""
    from engine import drift, parser, validate
    (tmp_path / "SPEC.md").write_text(
        "---\nid: a\nparent: null\nkind: system\ncontract: {purpose: x}\n"
        "code: []\nstatus: specd\n---\n\n# a\n", encoding="utf-8")
    nodes = parser.load_nodes(tmp_path)
    produced = validate.run(nodes, str(tmp_path)) + drift.run(nodes, str(tmp_path))
    assert any(line.startswith(prefix) for line in produced.splitlines()), prefix
    assert prefix in _status(), f"{prefix} is produced but STATUS.md does not show it"


def test_the_file_classification_does_not_restate_a_count():
    """It said "two are built" while three were, then "three" while four were.
    The labelled blocks below carry the information; a number beside them is a
    second source of truth that nothing derives."""
    import re
    block = _file_classification()
    counts = re.findall(r"\b(one|two|three|four|five|\d+)\s+(?:\w+\s+){0,2}are built\b",
                        block, re.I)
    assert not counts, f"§3.2c restates a count ({counts}); the BUILT labels are enough"


def test_the_waiver_section_describes_both_states():
    """The split exists because one act was not enough: a rule that forbade the
    RECORD of a deviation hid the deviation instead of preventing it."""
    from engine import waivers
    text = _glossary()
    section = text[text.index("### 3.10 Waiver"):text.index("### 3.11")]
    for state in waivers.STATES:
        assert state in section, f"§3.10 does not describe state {state!r}"
    assert "never implied" in section, "§3.10 must say a missing state is not a default"


def test_the_agent_manual_says_how_to_request_a_waiver():
    body = AGENTS_TEMPLATE.read_text(encoding="utf-8")
    assert "## When you must deviate from a rule" in body
    assert "state: requested" in body
    assert "writing `state: granted` on a waiver" in body   # still forbidden


def test_the_decision_request_section_is_canonical_and_backed_by_code():
    text = _glossary()
    section = text[text.index("### 3.10a Decision request"):text.index("### 3.11")]
    assert "engine/decisions.issues" in section
    assert "Not a waiver" in section, "§3.10a must keep the distinction from §3.10"
    from engine import decisions
    assert decisions.FIELD in section


def test_the_agent_manual_says_how_to_request_a_decision():
    body = AGENTS_TEMPLATE.read_text(encoding="utf-8")
    assert "## When a decision is above you" in body
    assert "decision_requests:" in body
    assert "ask instead" not in body, "the manual still points at a channel that does not exist"


# ---- GOVERNANCE 1: the role table, bound to the code that reads it ----------
#
# The table answers three questions at once -- what a role does, who plays it,
# where it is set. Two of the three are checkable: the roles the code knows and
# the variables it reads. (The third, "a PERSON" vs "a chat call", is prose.)
# It is checked because the same section once called the run "specified, not
# built" for weeks, two sentences after saying it was built.

GOVERNANCE = COCKPIT.parent / "spec-growth-engine" / "GOVERNANCE.md"


def _role_section() -> str:
    text = GOVERNANCE.read_text(encoding="utf-8")
    return text[text.index("## 1. Roles"):text.index("## 1a.")]


def test_the_table_names_every_model_backed_role_and_no_other():
    from agent import llm
    section = _role_section()
    named = set(re.findall(r"SGE_([A-Z]+)_\*", section))
    assert named == {r.upper() for r in llm.ROLES}, "the table and agent/llm.ROLES disagree"


@pytest.mark.parametrize("field", ["BASE_URL", "API_KEY", "MODEL"])
def test_every_setting_the_table_documents_is_one_the_code_reads(field):
    """Each name in the table must appear in the code that resolves it."""
    from agent import llm
    assert f"SGE_<ROLE>_{field}" in _role_section()
    source = Path(llm.__file__).read_text(encoding="utf-8")
    assert field in source, f"the table documents {field}, agent/llm.py does not read it"


def _played_by() -> str:
    """The table's third column, read as a column: its cells wrap over several
    lines, and flattening the whole block would splice the other columns
    between the words."""
    lines = _role_section().splitlines()
    rule = next(ln for ln in lines if ln.startswith("---"))
    spans, at = [], 0
    for dashes in rule.split("  "):
        spans.append((at, at + len(dashes)))
        at += len(dashes) + 2
    start, end = spans[2]
    body = lines[lines.index(rule) + 1:]
    return " ".join(" ".join(ln[start:end].split()) for ln in body if ln.strip())


def test_the_table_says_who_plays_each_role():
    """The question this table exists for: a person, a model, or code."""
    column = _played_by()
    for phrase in ("a PERSON, always", "NEVER a person", "codex exec agent",
                   "a chat call", "CODE. It calls no model, ever"):
        assert phrase in column, f"the played-by column lost {phrase!r}"


def test_the_way_to_ask_the_tool_is_named_and_exists():
    assert "role_agent.py --describe" in _role_section()
    assert (COCKPIT / "role_agent.py").is_file()


def test_governance_does_not_still_call_the_run_unbuilt():
    """It did, in the paragraph that also said the run was built."""
    text = " ".join(GOVERNANCE.read_text(encoding="utf-8").split())
    assert "specified, not built" not in text
    from engine import iteration
    assert iteration.MAX_ROUNDS >= 1        # the thing that makes a run go in rounds


# ---- the eighteen ways to run a project, bound to what they need ------------
#
# Written down because the two axes kept being conflated: how the floor is laid
# (the dialog, or bare) and who does the work (D0-D2 for a draft, the delegation
# for a pending HARD change, a run for the authorship of intent). A reader who
# takes them for a single ladder ends up expecting the delegation to ask before
# it acts.

def _four_ways() -> str:
    text = (COCKPIT / "README.md").read_text(encoding="utf-8")
    return text[text.index("## Eighteen ways to run a project"):text.index("\n## Headless gate")]


_COMBINATIONS = ([(g, d, "off") for g in ("D0", "D1", "D2") for d in ("off", "on")]
                 + [("-", "off", "on"), ("-", "on", "on"), ("-", "on", "unsupervised")])


@pytest.mark.parametrize("floor", ["guided", "bare"])
@pytest.mark.parametrize("gate,delegation,run", _COMBINATIONS)
def test_every_floor_is_listed_with_every_switch(floor, gate, delegation, run):
    """All three switches, spelled out as columns: how the floor was laid does
    not change what a switch does, and a reader should be able to find their own
    combination. A run reaches no slider, so its draft gate is `-`; unsupervised
    needs the delegation, so it has no row with the delegation off."""
    rows = [ln for ln in _four_ways().splitlines()
            if ln.startswith(f"{floor:<6}  {gate:<10}  {delegation:<10}  {run:<12}")]
    assert len(rows) == 1, f"{floor} + {gate} + delegation {delegation} + run {run}: {rows}"


def test_the_table_has_exactly_the_eighteen_rows():
    rows = [ln for ln in _four_ways().splitlines() if ln.startswith(("guided  ", "bare    "))]
    assert len(rows) == 18
    assert not [ln for ln in rows if "off         unsupervised" in ln]


def test_each_row_says_when_it_asks_and_what_it_needs():
    ways = _four_ways()
    assert "you are asked ..." in ways and "and it needs" in ways
    flat = " ".join(ways.split())
    assert "BEFORE every save" in flat                      # D0/D1
    assert "AFTER a SOFT draft saved itself" in flat        # D2
    assert "confirm or overrule" in flat                    # delegation, after the fact
    assert "NEVER before it acts" in flat                   # a run
    assert "AFTER the run, never during it" in flat         # unsupervised


def test_a_newcomer_is_told_what_d0_d1_d2_mean():
    """The table names the settings; a reader new to the method needs them in
    words -- who looks at a draft before it is saved -- and which one to start
    with. The start value must be the one the cockpit starts with."""
    import appconfig
    ways = _four_ways()
    section = ways[ways.index("**What D0, D1 and D2 mean.**"):]
    for line in ("D0  you alone", "D1  you, with a", "D2  H' saves the"):
        assert line in section
    flat = " ".join(section.split())
    assert "SOFT means" in flat and "HARD means" in flat
    assert f"Start with D{appconfig._DEFAULTS['draft_gate']}." in flat
    assert "at most twice" in flat
    from engine import autonomy
    assert autonomy.AUTO_MAX_ROUNDS == 2
    # who writes the draft, and that a hand-written spec is outside the slider:
    # Save asks no model (app.Cockpit.save_spec never calls _review)
    assert "the planner P (a language model" in flat and "**Draft ⟶**" in flat
    assert "The slider applies only to drafts P wrote" in flat
    import inspect
    import app
    assert "_review(" not in inspect.getsource(app.Cockpit.save_spec)


def test_the_two_axes_are_stated_as_independent():
    ways = " ".join(_four_ways().split())
    assert "Every floor combines with every setting" in ways
    assert "The floor does not change how a switch behaves" in ways
    assert "The switches are not one ladder" in ways
    assert "not a level at all" in ways


def test_the_offline_way_claims_no_model_and_the_engine_backs_it():
    """Way 4 promises the first layer works with no key at all. The commands it
    names must be ones the CLI has and the gate must not need a client."""
    import cli
    ways = " ".join(_four_ways().split())
    assert "No key, no endpoint" in ways
    source = Path(cli.__file__).read_text(encoding="utf-8")
    gate = source[source.index("def cmd_gate"):source.index("def cmd_pending")]
    assert "_load_env" not in gate and "agent" not in gate
    engine_gate = (COCKPIT / "engine" / "gate.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import) (agent|\.\w*llm)", engine_gate, re.M)  # no model


# ---- the autonomy switches have one set of names ------------------------------
#
# They were once one ladder, L0..L4: the draft gate, the delegation and the run
# under numbers that suggested a scale. The names are D0..D2, the delegation
# (on | off) and the run (on | off) -- everywhere, so nothing says "L3" again.

_OLD_NAME = re.compile(r"\bL[0-4]\b")


def _named_files():
    root = COCKPIT.parent
    yield from (root / "spec-growth-engine").glob("*.md")
    yield root / "README.md"
    yield from COCKPIT.glob("*.md")
    yield from COCKPIT.glob("*.py")
    yield from (COCKPIT / "engine").glob("*.py")
    yield from (COCKPIT / "agent").glob("*.py")
    yield from (COCKPIT / "tests").glob("*.py")
    yield COCKPIT / ".env.example"


def test_no_file_uses_the_old_level_names():
    this = Path(__file__).resolve()
    hits = [f"{path.relative_to(COCKPIT.parent)}:{n}"
            for path in _named_files() if path.resolve() != this and path.is_file()
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if _OLD_NAME.search(line)]
    assert not hits, "old autonomy names (L0..L4) still used: " + ", ".join(hits)



# ---- nothing local in what could be published ---------------------------------
#
# The install lines once said `cd /Users/<someone>/...`: true on one machine,
# wrong on every other, and a name nobody meant to publish. Generated files
# with local paths (the rendered manuals) live in each project, not here.

_LOCAL_PATH = re.compile(r"/(?:Users|home)/[A-Za-z]")


def test_no_document_or_module_names_a_local_path():
    root = COCKPIT.parent
    files = [*(root / "spec-growth-engine").glob("*.md"), root / "README.md",
             *COCKPIT.glob("*.md"), *COCKPIT.glob("*.py"), COCKPIT / ".env.example",
             *(COCKPIT / "engine").glob("*.py"), *(COCKPIT / "agent").glob("*.py")]
    hits = [f"{path.relative_to(root)}:{n}" for path in files if path.is_file()
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if _LOCAL_PATH.search(line)]
    assert not hits, "a local path in a published file: " + ", ".join(hits)
