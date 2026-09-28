"""Laying the floor of a new project: the root, a container, the invariants.

A newcomer's first hour goes into things that are not judgement: bootstrapping a
root, picking a code layout, writing a build manifest, remembering to record the
starting state. What IS judgement -- which invariants hold everywhere -- is four
lines they have no way to guess at yet. This module walks both, and writes
nothing the caller has not shown to a person first.

  plan(answers)      -> [Action]   what WOULD be written. Pure, so it is testable
                                   and so a caller can display it before it acts.
  apply(root, ...)   -> [str]      writes it, and says what it did.
  propose(...)                     P words an answer as an invariant line. Every
                                   step works without it: then H types the line.

It stops at the floor, and renders the two manuals an agent run would read with
THIS project's paths -- mechanics either way, and the values all follow from the
graph it just wrote. When a run is intended it also writes TASK.md, from the
method's template (spec-growth-engine/TASK.template.md) and the person's own
words. What it does NOT do is decide anything below the container, word the
goal, or start a run: the graph belongs to whoever grows it, and the goal is H's
prose (SPEC-GROWTH-ENGINE.md 3.12, 5).

It records the answers it was given (<root>/.sge/groundwork.json), so the same
floor can be laid again, elsewhere -- `like(root)`, "New Project Like..." in the
cockpit, `cli.py init NEW --like OLD`. A second attempt at the same task starts
from the same place, in a new directory, instead of resetting the first.

The only place in the tool where a model writes into a layer-1 artefact, and it
does so ONLY through an answer a person gave and confirmed. If that ever stops
being true, this file is where the boundary moved.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import layouts
from engine import accepted, nodes as nodeops, parser

# The floor two early experiments arrived at almost word for word, so it is a
# DEFAULT, not a discovery. Shown line by line, each one kept or dropped.
DEFAULT_INVARIANTS = (
    "Secrets only via environment variables, never in code or committed files.",
    "No network access at test time; tests must be green offline.",
    "Every public behaviour has at least one test that would fail if the behaviour broke.",
    "Errors are raised as exceptions with a message naming the offending input.",
)
DEFAULT_QUALITY = (
    "Readable over clever. A reviewer reads this once and understands it.",
    "Deterministic: same input, same output, no hidden state.",
)


@dataclass(frozen=True)
class Question:
    """One thing the defaults cannot know. The answer becomes ONE invariant
    line -- typed, or worded by P from what the person said. Skipping is a
    legitimate answer: an invariant nobody decided is better raised by the
    first run as a decision request than guessed at here."""
    key: str
    ask: str
    hint: str


# Four, deliberately. Each one an invariant that reaches every node, and each
# one a question the runs actually raised when nobody had answered it.
QUESTIONS = (
    Question("persistence", "Where does data live between runs -- or does none?",
             "e.g. one file under a directory the user names; or: nothing is kept"),
    Question("concurrency", "May two of these run at the same time?",
             "e.g. no, one at a time; or: yes, and writes are serialised"),
    Question("network", "May it reach the network while it runs?",
             "tests are already offline; this is about run time"),
    Question("anything_else", "Anything else that must hold EVERYWHERE?",
             "a platform, a data rule, a limit -- one line, or skip"),
)


@dataclass
class WriteRoot:
    system_id: str
    purpose: str


@dataclass
class AddContainer:
    segment: str
    archetype: str


@dataclass
class WriteFloor:
    invariants: list[str]
    quality: list[str] = field(default_factory=lambda: list(DEFAULT_QUALITY))


@dataclass
class AcceptAll:
    by: str


@dataclass
class WriteTask:
    """TASK.md: the goal, in prose, for a run (SPEC-GROWTH-ENGINE.md 3.12). Only
    when a run is intended -- H at the cockpit needs none, the goal is in their
    head. The person's own words go in; the standard "Done means" is prefilled,
    because it is the method's and not theirs to invent."""
    behaviours: str
    always: str
    out_of_scope: str = ""
    purpose: str = ""


@dataclass
class CopyTask:
    """TASK.md, copied verbatim from the project this one is laid like: the goal
    that project was measured against, including every edit made to it since."""
    source: Path


@dataclass
class RecordAnswers:
    """<root>/.sge/groundwork.json: what the person answered, so the same floor
    can be laid again (`like`). The invariants as they were written -- worded by P
    or not -- so laying it again asks no model."""
    answers: dict


@dataclass
class RenderManuals:
    """ORCHESTRATOR.md and AGENTS.md for THIS project, from the method's
    templates. Rendering them by hand was the one manual step left in a
    newcomer's path, and every value follows from the graph (see `_values`)."""


Action = (WriteRoot | AddContainer | WriteFloor | AcceptAll | WriteTask | CopyTask
          | RecordAnswers | RenderManuals)

ANSWERS_FILE = Path(".sge") / "groundwork.json"
_RECORDED = ("system_id", "purpose", "container", "archetype", "invariants", "quality",
             "by", "behaviours", "always", "out_of_scope")


def plan(answers: dict) -> list[Action]:
    """What laying this floor would write, in order. Nothing is read or written
    here: a caller shows this, a person confirms it, and only then `apply` runs.

    `answers` carries what the person said: system_id, purpose, container,
    archetype, invariants (the kept defaults plus one line per answered
    question), quality, by.
    """
    invariants = [line.strip() for line in answers.get("invariants") or [] if line.strip()]
    quality = [q.strip() for q in answers.get("quality") or DEFAULT_QUALITY]
    recorded = {k: answers.get(k) for k in _RECORDED if answers.get(k) is not None}
    recorded.update(invariants=invariants, quality=quality)
    return [
        WriteRoot(answers["system_id"].strip(), answers.get("purpose", "").strip()),
        AddContainer(answers["container"].strip(), answers.get("archetype") or layouts.FREEFORM),
        WriteFloor(invariants, quality),
        AcceptAll(answers.get("by") or "setup"),
        RecordAnswers(recorded),
        RenderManuals(),
    ] + ([WriteTask(answers.get("behaviours", ""), answers.get("always", ""),
                    answers.get("out_of_scope", ""), answers.get("purpose", ""))]
         if answers.get("behaviours") or answers.get("always") else [])


def answers_of(root: str | Path) -> dict:
    """What was answered when `root`'s floor was laid. Raises ValueError when it
    was not laid here -- by hand, or before the answers were recorded."""
    path = Path(root) / ANSWERS_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{root} records no answers to lay a floor like it "
                         f"({ANSWERS_FILE} is missing or unreadable)") from exc


def like(source: str | Path, by: str | None = None) -> list[Action]:
    """The plan for a floor laid like `source`'s: the same answers, and -- when
    `source` has one -- its TASK.md verbatim, as it reads NOW. A second attempt
    at a task is a new directory laid like the first, not the first one reset."""
    answers = dict(answers_of(source))
    if by:
        answers["by"] = by
    actions = [a for a in plan(answers) if not isinstance(a, WriteTask)]
    task = Path(source) / "TASK.md"
    if task.is_file():
        actions.append(CopyTask(task))
    elif answers.get("behaviours") or answers.get("always"):
        actions += [a for a in plan(answers) if isinstance(a, WriteTask)]
    return actions


def refuses(root: str | Path) -> str | None:
    """Why this is not a new project, or None. A floor is laid once: over an
    existing root it would replace decisions someone already made."""
    path = Path(root)
    spec = path / "SPEC.md"
    if spec.is_file():
        try:
            import frontmatter
            if frontmatter.load(spec).metadata.get("id"):
                return f"{spec} already holds a root node -- this project has a floor"
        except Exception:
            return f"{spec} exists and could not be read; move it aside first"
    arch = path / "ARCHITECTURE.md"
    if arch.is_file() and [ln for ln in arch.read_text(encoding="utf-8").splitlines()
                           if ln.strip() and not ln.startswith("#")
                           and ln.strip() not in ("- TODO",)]:
        return f"{arch} already says something -- laying a floor would replace it"
    return None


def apply(root: str | Path, actions: list[Action]) -> list[str]:
    """Write the planned actions, in order; return one line per artefact. Raises
    ValueError when the root is not a new project (see `refuses`)."""
    root = Path(root)
    why = refuses(root)
    if why:
        raise ValueError(why)
    done: list[str] = []
    for action in actions:
        if isinstance(action, WriteRoot):
            spec = nodeops.bootstrap_root(str(root), action.system_id, action.purpose)
            done.append(f"root node `{action.system_id}` -> {spec}")
        elif isinstance(action, AddContainer):
            nodes = parser.load_nodes(root)
            parent = next(nid for nid, n in nodes.items() if n.get("parent") is None)
            path = str(root / action.segment).replace(str(root) + "/", "")
            nid, spec = nodeops.new_node(
                parent, action.segment, "container", nodes,
                layout_invariants=layouts.template(action.archetype),
                manifest=layouts.manifest(action.archetype, path))
            done.append(f"container `{nid}` -> {spec}")
            seeded = layouts.manifest(action.archetype, path)
            if seeded:
                done.append(f"build manifest -> {action.segment}/{seeded[0]} "
                            "(the container's own code, C maintains it)")
        elif isinstance(action, WriteFloor):
            (root / "ARCHITECTURE.md").write_text(_floor(action), encoding="utf-8")
            done.append(f"{len(action.invariants)} invariant(s) -> ARCHITECTURE.md")
        elif isinstance(action, WriteTask):
            (root / "TASK.md").write_text(task_text(action), encoding="utf-8")
            done.append("TASK.md -- the goal a run is measured against; its "
                        "'Done means' is the method's standard, edit it if you mean "
                        "something else")
        elif isinstance(action, CopyTask):
            shutil.copyfile(action.source, root / "TASK.md")
            done.append(f"TASK.md -- copied from {action.source}, as it reads now")
        elif isinstance(action, RecordAnswers):
            path = root / ANSWERS_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(action.answers, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            done.append(f"the answers -> {ANSWERS_FILE} (to lay this floor again, "
                        "elsewhere: --like)")
        elif isinstance(action, RenderManuals):
            for name, text in manuals(root).items():
                (root / name).write_text(text, encoding="utf-8")
                done.append(f"{name} -- the manual a run reads, with this project's paths")
        elif isinstance(action, AcceptAll):
            n = accepted.accept_all(parser.load_nodes(root), root, by=action.by)
            done.append(f"recorded the floor as the accepted state ({n} node(s), by "
                        f"{action.by}): every change is measured against it from now on")
    return done


def _floor(action: WriteFloor) -> str:
    lines = ["# Architecture", "", "## Invariants (hold everywhere)"]
    lines += [f"- {i}" for i in action.invariants] or ["- TODO"]
    lines += ["", "## Quality goals"] + [f"- {q}" for q in action.quality]
    lines += ["", "## Decisions (ADRs)",
              "- (the container states its own stack; record decisions above node "
              "level here, or accept a decision request from the Requests window)", ""]
    return "\n".join(lines)


# ---- the goal, when a run is intended ------------------------------------------

# The template: its structure and its "Done means" are the METHOD's, not the
# person's -- the same in every project, which is why a newcomer should not have
# to invent them. The first "Done means" line is the one E cannot check, so it is
# what gives H' its job (SPEC-GROWTH-ENGINE.md 3.12).
TASK_TEMPLATE = Path(__file__).resolve().parent.parent / "spec-growth-engine" / "TASK.template.md"
_TASK_MARKER = "<!-- TASK.md starts here -->"


def _task_body() -> str:
    text = TASK_TEMPLATE.read_text(encoding="utf-8")
    return text[text.index(_TASK_MARKER) + len(_TASK_MARKER):].lstrip("\n")


def _section(text: str, heading: str) -> str:
    start = text.index(heading) + len(heading)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


DONE_MEANS = tuple(ln[2:].strip() for ln in _section(_task_body(), "## Done means").splitlines()
                   if ln.startswith("- "))

TASK_PROMPTS = (
    ("behaviours", "What must it do?",
     "one line per command or behaviour, with an example -- and what it refuses"),
    ("always", "What must always be true?",
     "the sentences no single command owns: survives a restart, offline, "
     "deterministic, how a failure behaves"),
    ("out_of_scope", "What is out of scope?",
     "optional -- what you do NOT want built, so nobody grows it"),
)


def _bullets(text: str) -> str:
    """The person's lines, as written. A wish may be a sentence or a list; it is
    not reworded here -- TASK.md is prose, and prose is theirs (3.12)."""
    lines = [ln.strip().lstrip("-*").strip() for ln in (text or "").splitlines()]
    return "\n".join(f"- {ln}" for ln in lines if ln)


def task_text(action: WriteTask) -> str:
    """TASK.md from the template and the answers. Deterministic: the structure and
    the standard are the method's (spec-growth-engine/TASK.template.md), every
    word of substance is the person's. A section left empty is left out."""
    values = {"PURPOSE": (action.purpose or "").strip(),
              "MUST_DO": _bullets(action.behaviours) or "- TODO",
              "ALWAYS": _bullets(action.always),
              "OUT_OF_SCOPE": _bullets(action.out_of_scope)}
    body = _task_body()
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", value)
    head, *sections = body.split("\n## ")
    kept = [head.rstrip()] + ["## " + sec.rstrip() for sec in sections
                              if sec.split("\n", 1)[1:] and sec.split("\n", 1)[1].strip()]
    return "\n\n".join(part for part in kept if part.strip()) + "\n"


# ---- the manuals a run reads, rendered for THIS project ------------------------

_TEMPLATES = {"ORCHESTRATOR.md": "ORCHESTRATOR.template.md", "AGENTS.md": "AGENTS.template.md"}
_METHOD = Path(__file__).resolve().parent.parent / "spec-growth-engine"
_ARCHETYPE_BY_MANIFEST = {name: key for key, (name, _text) in layouts.MANIFESTS.items()}


def _archetype(container_dir: Path) -> str:
    """Which archetype this container was laid with, read back from the manifest
    beside its spec. Nothing records the key, and nothing needs to: the file name
    is the choice (pyproject.toml, Cargo.toml, package.json, pom.xml)."""
    for name, key in _ARCHETYPE_BY_MANIFEST.items():
        if (container_dir / name).is_file():
            return key
    return layouts.FREEFORM


def _values(root: Path) -> dict:
    """The placeholders of the manuals, derived from the graph. No new field: the
    container is the one node of that kind, its stack is its manifest, and the
    test command is what `test` would run (testrun)."""
    import testrun
    nodes = parser.load_nodes(root)
    containers = [nid for nid, n in nodes.items() if n.get("kind") == "container"]
    container = containers[0] if containers else ""
    node = nodes.get(container, {})
    path = container.replace(".", "/")
    directory = Path(node.get("_dir") or (root / path))
    key = _archetype(directory)
    label = dict(layouts.labels()).get(key, "freeform")
    command = testrun.test_command(testrun.build_root_for_node(node, str(root))) if node else None
    cockpit = Path(__file__).resolve().parent
    lines = layouts.template(key)
    code_dir = next((ln for ln in lines if ln.startswith("Code layout")), "")
    test_dir = next((ln for ln in lines if ln.startswith("A component owns its own tests")), "")
    return {
        "SGE_CLI": f"uv run --project {cockpit} python {cockpit}/cli.py",
        "SPEC_ROOT": str(root),
        "CONTAINER": f"{container}  ({label})" if container else "none yet -- propose one",
        "CODE_DIR": code_dir.replace("{container}", path) or "the container's layout invariant",
        "TEST_DIR": test_dir.replace("{container}", path) or "the container's layout invariant",
        "TEST_CMD": f"cd {path} && {' '.join(command)}" if command
                    else "none yet: no build manifest, so `test` finds no build root",
        "GIVEN": f"SPEC.md, ARCHITECTURE.md, {path}/SPEC.md" if container
                 else "SPEC.md, ARCHITECTURE.md",
        "METHOD_DOCS": str(_METHOD),
    }


def manuals(root: str | Path) -> dict[str, str]:
    """{file name: text} for the manuals of THIS project. Raises FileNotFoundError
    when the method's templates are not beside the cockpit."""
    root = Path(root)
    values = _values(root)
    out = {}
    for name, template in _TEMPLATES.items():
        text = (_METHOD / template).read_text(encoding="utf-8")
        body = text[text.index("## This project"):]
        for key, value in values.items():
            body = body.replace("{{" + key + "}}", value)
        head = text[: text.index("## This project")].split("\n", 1)[0]
        out[name] = (f"{head}\n\n<!-- GENERATED for this project by cockpit/groundwork.py"
                     f"\n     from spec-growth-engine/{template} -- `cli.py manuals ROOT`"
                     f"\n     (or Refresh Manuals in the cockpit) renders it again. -->\n\n"
                     + body)
    return out


def endpoints() -> list[tuple[str, str]]:
    """(role, what it can do) per model-backed role -- what a run would find. A
    report, never a change: keys live in cockpit/.env and are H's business."""
    from agent import llm
    out = []
    for role in llm.ROLES:
        endpoint = llm.endpoint(role)
        ready = bool(endpoint["api_key"] and endpoint["model"])
        out.append((role, llm.describe(role) if ready else "no endpoint yet"))
    return out


_PROMPT = (
    "Word this as ONE invariant of a software project: a single sentence, present "
    "tense, stating what holds everywhere -- not advice, not a rationale, no "
    "hedging. It goes under '## Invariants (hold everywhere)' in ARCHITECTURE.md, "
    "where every node is measured against it, so say only what the answer says.\n\n"
    "QUESTION: {ask}\nANSWER: {answer}\n\nReturn the sentence and nothing else."
)


def propose(question: Question, answer: str, planner) -> str:
    """P words an answer as an invariant line. The person sees it and keeps,
    edits or drops it -- this proposes, it never decides. Returns the answer
    unchanged when P is unavailable, because a floor must be layable offline."""
    try:
        return planner.one_line(_PROMPT.format(ask=question.ask, answer=answer.strip()))
    except Exception:
        return answer.strip()
