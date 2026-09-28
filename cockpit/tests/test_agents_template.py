"""The agent operating manuals: the method's generic templates, and what a new
project gets from them.

The manuals belong to the METHOD, not to one project. They are kept generic in
spec-growth-engine/AGENTS.template.md and ORCHESTRATOR.template.md, and rendered
into each project by groundwork -- New Project..., `cli.py init`, and `cli.py
manuals` to refresh them. No rendered copy lives in this repository: these
tests render one, the way a new project gets it, and hold the relationship --
no placeholder may survive, none may be undocumented.
"""
import re
from pathlib import Path

import pytest

import cli
import groundwork
import orchestrate
from engine import nodes as nodeops

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "spec-growth-engine" / "AGENTS.template.md"

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


@pytest.fixture(scope="module")
def laid(tmp_path_factory):
    """A project as New Project... lays it: a root, a container, the floor."""
    root = tmp_path_factory.mktemp("laid")
    groundwork.apply(root, groundwork.plan({
        "system_id": "shop", "container": "api", "archetype": "python-uv-src",
        "invariants": list(groundwork.DEFAULT_INVARIANTS), "by": "t"}))
    return root


@pytest.fixture(scope="module")
def bare(tmp_path_factory):
    """A root and nothing else: no container is given, so proposing one is the
    run's -- the greenfield case."""
    root = tmp_path_factory.mktemp("bare")
    nodeops.bootstrap_root(str(root), "shop", "")
    return root


@pytest.fixture(scope="module")
def manual(laid):
    return (laid / "AGENTS.md").read_text(encoding="utf-8")


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_the_template_exists_and_is_generic():
    """No absolute path and no project name may leak into the generic half."""
    body = _template()
    generic = body[body.index("## The one rule"):]
    assert "/Users/" not in generic, "an absolute path leaked into the generic body"
    assert "svc" not in generic, "a project-specific container name leaked in"


def test_every_placeholder_is_documented_in_the_header():
    body = _template()
    header = body[: body.index("## This project")]
    used = set(PLACEHOLDER.findall(body))
    assert used, "the template has no placeholders -- it is not generic"
    undocumented = sorted(p for p in used if "{{" + p + "}}" not in header)
    assert not undocumented, f"placeholders not listed in the header: {undocumented}"


@pytest.mark.parametrize("project", ["laid", "bare"])
def test_groundwork_has_a_value_for_every_placeholder(project, request):
    root = request.getfixturevalue(project)
    for name, text in groundwork.manuals(root).items():
        assert not PLACEHOLDER.search(text), f"{name} kept a placeholder ({project})"
        assert "/Users/" not in text.split("## This project")[0], name


def test_a_new_project_gets_both_manuals_saying_they_are_generated(laid):
    for name, template in (("AGENTS.md", "AGENTS.template.md"),
                           ("ORCHESTRATOR.md", "ORCHESTRATOR.template.md")):
        head = (laid / name).read_text(encoding="utf-8")[:400]
        assert "GENERATED for this project" in head and template in head
        assert "cli.py manuals" in head, "the copy must say how it is refreshed"


def test_a_stale_manual_is_refreshed_from_the_template(laid, capsys):
    """Editing the template changes nothing in a project until it is refreshed --
    `cli.py manuals`, or Refresh Manuals in the cockpit."""
    path = laid / "AGENTS.md"
    path.write_text("stale\n", encoding="utf-8")
    assert cli.main(["manuals", str(laid)]) == 0
    assert "AGENTS.md: refreshed" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == groundwork.manuals(laid)["AGENTS.md"]


@pytest.mark.parametrize("rule", [
    "The SPEC comes first",
    "PROJECT-ROOT-relative",
    "owns its own tests",
    "USAGE edge",
    "Status is earned",
    "Forbidden",
    "does NOT check",
])
def test_the_manual_carries_every_rule_the_gate_enforces(rule, manual):
    """A manual that omits a rule sets the agent up to fail the gate for a
    reason it was never told about."""
    assert rule in manual, rule


# ---- the manual must lead back to the method --------------------------------
#
# An agent started in the project directory sees only AGENTS.md. Without a
# pointer it cannot look anything up, cannot see WHY a rule exists, and has no
# recourse when the gate blocks it for a reason the summary does not cover.

def test_the_manual_points_at_the_method_documents(manual):
    body = manual
    assert "## The method itself" in body
    assert "SPEC-GROWTH-ENGINE.md" in body and "SPEC-GROWTH-ENGINE-CONCEPT.md" in body


def test_every_document_the_manual_names_exists(manual):
    """A reading list pointing at a moved file is worse than no reading list:
    the agent follows it, finds nothing, and proceeds by guessing."""
    body = manual
    section = body[body.index("## The method itself"):body.index("## The one rule")]
    docs_dir = REPO / "spec-growth-engine"
    # only the list ENTRIES (indented, at line start) -- not every mention of a
    # filename in the surrounding prose, which includes "your first SPEC.md"
    named = sorted(set(re.findall(r"^\s{2,}([A-Z][A-Z-]+\.md)\b", section, re.M)))
    assert len(named) >= 5, f"the reading list looks empty: {named}"
    missing = [d for d in named if not (docs_dir / d).is_file()]
    assert not missing, f"the manual sends the agent to files that do not exist: {missing}"


def test_the_mandatory_reading_is_named_and_small(manual):
    """'Read everything' is not an instruction anyone follows. The manual must
    say which sections are required before the first SPEC.md."""
    body = manual
    assert "Minimum before your first SPEC.md" in body


def test_the_method_path_is_a_placeholder_not_a_hardcoded_path():
    template = _template()
    generic = template[template.index("## The method itself"):]
    assert "{{METHOD_DOCS}}" in template
    assert "/Users/" not in generic, "an absolute path leaked into the generic body"


@pytest.mark.parametrize("doc,heading", [
    ("SPEC-GROWTH-ENGINE.md", "## 3. Canonical glossary"),
    ("SPEC-GROWTH-ENGINE-CONCEPT.md", "## 3."),
    ("SPEC-GROWTH-ENGINE-CONCEPT.md", "## 4."),
    ("SPEC-GROWTH-ENGINE-CONCEPT.md", "## 7a."),
    ("GOVERNANCE.md", "## 8. Waivers"),
])
def test_the_sections_the_manual_sends_the_agent_to_exist(doc, heading):
    """Naming a section is more useful than naming a document -- and more
    fragile: renumbering silently points the agent at nothing."""
    body = (REPO / "spec-growth-engine" / doc).read_text(encoding="utf-8")
    assert any(line.startswith(heading) for line in body.splitlines()), f"{doc} {heading}"


# ---- the intent author's manual (orchestrated runs): the same contract -------

ORCH_TEMPLATE = REPO / "spec-growth-engine" / "ORCHESTRATOR.template.md"


def test_the_orchestrator_template_is_generic_and_documented():
    body = ORCH_TEMPLATE.read_text(encoding="utf-8")
    generic = body[body.index("## Your role"):]
    assert "/Users/" not in generic and "svc" not in generic
    header = body[: body.index("## This project")]
    used = set(PLACEHOLDER.findall(body))
    assert used and not [p for p in used if "{{" + p + "}}" not in header]


def test_the_orchestrator_manual_forbids_writing_and_names_every_command():
    """The role exists for the separation; the commands are how it keeps it."""
    body = ORCH_TEMPLATE.read_text(encoding="utf-8")
    assert "Never write or edit a SPEC.md, a source file or a test yourself" in body
    import cli
    source = Path(cli.__file__).read_text(encoding="utf-8")
    for command in ("draft", "revise", "code", "test", "gate", "pending", "decide"):
        assert f'args.cmd == "{command}"' in source, command
        assert command in body, command


@pytest.mark.parametrize("claim", [
    "ITERATIVE over slices",                  # outside: slice after slice
    "RECURSIVE, but only",                    # inside: along the path only
    "decompose as far as you KNOW",           # known now, guessed later
    "Drafting early is not the failure",      # the line is guessed vs known
    "GOVERNANCE.md` §10.1",                   # a child only when it earns it
    "Implement bottom-up",                    # providers before consumers
    "frontier-stub",                          # no quiet fakes
    "Growth is yours",                        # I decides; P formalizes
])
def test_the_orchestrator_manual_grows_the_graph_in_slices(claim):
    """The intent author's growth method (LIFECYCLE §3-§7). It replaced "one
    node at a time"; a rewrite must not shrink it back."""
    assert claim in ORCH_TEMPLATE.read_text(encoding="utf-8")


# ---- the same rule, for the same role, wherever its player reads ------------
#
# "Iterative outside, recursive along the path" lived in ONE file: the agent's
# manual. A person doing the identical job in the cockpit was never told, and
# LIFECYCLE -- the method itself -- named no role at all, so nothing said whose
# judgement this is. These three places must keep saying it.

METHOD = REPO / "spec-growth-engine"


def test_the_method_says_whose_judgement_the_slice_workflow_is():
    section = (METHOD / "LIFECYCLE.md").read_text(encoding="utf-8")
    section = section[section.index("## 6. The slice workflow"):]
    section = section[:section.index("## 7.")]
    assert "INTENT AUTHOR" in section and "GOVERNANCE.md" in section
    assert "H typing in the cockpit, or an agent" in section
    assert "ITERATIVE over slices" in section and "RECURSIVE, but only" in section


def test_the_role_definition_says_growth_is_the_intent_authors():
    glossary = (METHOD / "SPEC-GROWTH-ENGINE.md").read_text(encoding="utf-8")
    role = glossary[glossary.index("I  Intent author"):glossary.index("P  Planner Agent")]
    assert "HOW the graph\n                     grows" in role
    assert "LIFECYCLE.md" in role, "the definition must point at the method, not restate it"


def test_the_cockpit_tells_the_person_at_the_keyboard_the_same_thing():
    """Prose wraps, so compare with the whitespace collapsed: a reflow is
    formatting, a lost sentence is not."""
    readme = " ".join((REPO / "cockpit" / "README.md")
                      .read_text(encoding="utf-8").split())
    assert "In the cockpit you are the INTENT AUTHOR (role I)" in readme
    assert "one working vertical slice at a time" in readme
    assert "decomposing as far as you know" in readme
    assert "not early drafting" in readme
    assert "LIFECYCLE.md" in readme


# ---- a project without a container -------------------------------------------
#
# The greenfield case: a root and its invariants, and nothing else. The same
# templates, other values -- the agent proposes the container, and the engine
# holds that proposal for H without blocking the run.

def test_without_a_container_the_manual_says_none_is_given(bare):
    values = groundwork._values(bare)
    assert "none yet" in values["CONTAINER"]
    given = values["GIVEN"]
    assert "SPEC.md" in given and "ARCHITECTURE.md" in given
    assert "pyproject" not in given, "no project is given: creating one is the work"


def test_the_intent_author_uses_the_engine_and_does_not_read_it():
    """Runs 08-11 each read the engine's source -- because the prompt named the
    directory and the rules said "you may read everything". Reading the checker
    teaches an agent to pass it; worse, it hides the documentation gap that sent
    it looking. Diagnosis is a finding to report, not a detour to take."""
    body = ORCH_TEMPLATE.read_text(encoding="utf-8")
    assert "The ENGINE is a tool you USE" in body
    assert "do not read its source" in body and "that is a FINDING" in body
    prompt = orchestrate.first_prompt()
    assert "is not yours to read" in prompt
    assert "the engine and its CLI in ../cockpit" not in prompt


def test_a_given_file_stays_given_even_when_a_gap_demands_it():
    """Run 11 had P rewrite both given specs -- the root's status and the
    container's contract -- after the reviewer named "the container is still
    specd" as a gap. Nothing stopped it: no gate knows the word "given". The
    manual has to, and it has to say that a gap is a finding, not a permission."""
    body = ORCH_TEMPLATE.read_text(encoding="utf-8")
    section = " ".join(body[body.index("**A GIVEN file is not yours"):].split())
    assert "not even through P" in section
    assert "no gate knows the word" in section
    assert "raise the decision request" in section
    assert "STOP NORMALLY" in section          # waiting for H is not being blocked
    assert "A gap is a finding, not an authorisation" in section


def test_a_request_between_the_authors_own_nodes_is_a_revise():
    """Run 11 raised nine requests; three went to sibling nodes it grows itself
    (track.cli -> track.store, track.report -> track.sessions and -> track.cli).
    The manual allowed "another node's contract" as a target without saying it
    means a node H holds, which inflated the count by a third and left three
    nodes waiting on a decision nobody had to make."""
    manual = " ".join(ORCH_TEMPLATE.read_text(encoding="utf-8").split())
    assert "Between your OWN nodes there is no question to ask" in manual
    assert "revise `a.sessions` and say why" in manual
    glossary = " ".join((METHOD / "SPEC-GROWTH-ENGINE.md").read_text(encoding="utf-8").split())
    section = glossary[glossary.index("3.10a Decision request"):]
    assert "a node the asker may not grow itself" in section
    assert "NOT a node the asker grows" in section


def test_given_covers_the_spec_and_not_the_node_s_code():
    """Runs 10, 11, 12 and the reading-list run each asked H for a `[project.scripts]`
    line in a container's manifest -- a file in that container's own code glob,
    which `code <container>` may change without touching the given spec. Run 10
    stopped for it."""
    manual = " ".join(ORCH_TEMPLATE.read_text(encoding="utf-8").split())
    assert "A given SPEC.md does not make that node's CODE given" in manual
    assert "The list names specs, not directories" in manual
    assert 'code <container> --instruction' in manual
