"""Headless Spec Growth Engine gate (CLI) + git pre-commit hook installer.

The cockpit GUI is for authoring; this CLI is the *blocking gate*: it runs the
deterministic engine checks (structure + code drift) and exits non-zero so a
git pre-commit hook can refuse a commit that drifts spec from code.

  uv run python cli.py validate [ROOT]      # spec-side structure (intent graph)
  uv run python cli.py drift    [ROOT]      # code drift (evidence vs depends_on)
  uv run python cli.py gate     [ROOT]      # validate + drift (the commit gate);
                                            # on PASS, E accepts changes <= SOFT
  uv run python cli.py pending  [ROOT]      # everything awaiting H: waivers, decisions,
                                            # HARD changes (impact + brief), delegated acceptances
  uv run python cli.py prepare  [ROOT]      # H' briefs each pending HARD change (API key)
  uv run python cli.py decide   [ROOT]      # delegation on: H' decides the HARD changes it may
  uv run python cli.py test     [ROOT]      # run the tests, record them as evidence
  uv run python cli.py delegate ROOT [on|off] [--by NAME]  # the delegation: who decides HARD
  uv run python cli.py draft    ROOT ID --parent P --kind K --intent TEXT  # P drafts a node
  uv run python cli.py revise   ROOT ID --change TEXT                      # P revises a spec
  uv run python cli.py code     ROOT ID [--instruction TEXT]               # C implements
  uv run python cli.py code     ROOT ID --affected   # ID and whoever uses it, in order,
                                            # then the tests and the gate
  uv run python cli.py intents  ROOT [ID]   # the growth record: every intent, in order
  uv run python cli.py accept   ROOT ID... | --all [--by NAME]           # H accepts
  uv run python cli.py reject   ROOT ID... --reason TEXT [--by NAME]    # H rejects
  uv run python cli.py duplicates [ROOT]    # capability duplicate scan (advisory)
  uv run python cli.py init     ROOT --id ID --container NAME [--archetype KEY]
                                            # lay a floor: root, container, manifest,
                                            # invariants, and record it as accepted
  uv run python cli.py init     ROOT --like OLD   # the same floor again, elsewhere
  uv run python cli.py manuals  ROOT        # re-render AGENTS.md / ORCHESTRATOR.md
  uv run python cli.py find     ROOT WORDS    # the words in TASK.md, ARCHITECTURE.md and
                                            # every SPEC.md: where:line: text
  uv run python cli.py compact  ROOT ID [--force]   # P: the same spec in fewer words;
                                            # refused if a provides name would go
  uv run python cli.py rename   ROOT ID NEW [--by NAME]   # rename a node and its subtree;
                                            # its code stays where it is
  uv run python cli.py check    ROOT [--task FILE]   # does it meet TASK.md? E measures,
                                            # H' checks the goal -- no agent, nothing changed
  uv run python cli.py run      ROOT [--unsupervised] [--max-rounds N] [--task FILE]
                                            # an agent grows the graph, in rounds;
                                            # the record lands in ROOT/.sge/runs/
  uv run python cli.py install-hook [ROOT] [--force]   # wire .git/hooks/pre-commit

ROOT defaults to the current directory. The gate is OFFLINE and deterministic
(no API key, no network) so it is fast and safe to run on every commit.

`gate` is the one checking command that WRITES: once a project tracks an accepted
state (.sge/accepted.json, engine/accepted.py), a passing gate records every
change at SOFT or below as accepted. A HARD change never blocks the gate -- it
stays pending, and keeps its nodes from `verified`, until `accept` records it.
`reject` turns it into a HARD error with H's reason -- the gate then blocks until
the node is restored or changed differently.

`prepare` and `decide` are the commands that need an API key -- never the gate.
`prepare` has H' write a brief for each pending HARD change: a recommendation,
nothing more. `decide` works only under the delegation (`delegate ROOT on`, H's
act): it collects
the pending changes H' may decide -- inside its scope, and migrated
(engine/migration.py) -- and lets H' accept them; the rest stays for H. Every
acceptance by H' can be confirmed (`accept`) or overruled (`reject`) by H.
`test` records evidence headless, which is what "migrated" is checked against.

`draft`, `revise` and `code` are how the INTENT AUTHOR (role I -- you in the
cockpit, an agent in an orchestrated run) reaches the planner P and the coder C
without writing a spec or a line of code itself. Each role has its own model
(agent/llm.py): P is SGE_PLANNER_*, C is a codex agent on SGE_CODER_*, H' is
SGE_REVIEWER_*. Every call is logged with the model that made it.
"""
from __future__ import annotations

import argparse
import getpass
import stat
import sys
from pathlib import Path

# Make `engine` importable no matter the caller's cwd (the git hook runs from the
# committing repo, not from this directory).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from engine import (  # noqa: E402
    accepted, assist, autonomy, capability, changeset, drift, index as index_mod,
    migration, parser, validate,
)

HOOK_MARKER = "# spec-growth-engine pre-commit gate"


def _blocked(report: str) -> bool:
    """A report blocks iff its trailing gate line is BLOCK (stable convention)."""
    return "gate: BLOCK" in report


def _load(root: str) -> dict:
    return parser.load_nodes(root)


def cmd_validate(root: str) -> int:
    report = validate.run(_load(root), root)
    print(report)
    return 1 if _blocked(report) else 0


def cmd_drift(root: str) -> int:
    report = drift.run(_load(root), root)
    print(report)
    return 1 if _blocked(report) else 0


def cmd_gate(root: str) -> int:
    """The commit gate: structure AND code drift must both pass; on a pass, E
    clears what it may (engine/gate.py -- the cockpit's Validate > Gate too)."""
    from engine import gate
    result = gate.run(_load(root), root)
    print(gate.text(result))
    return 1 if result["blocked"] else 0


def cmd_pending(root: str) -> int:
    """Everything awaiting H, as the cockpit's Requests window lists it: waivers
    requested, decisions requested, HARD change sets (with consumer impact and
    H's brief), and what H' accepted under the delegation. Headless, this used to show the HARD
    changes only -- a question the graph raised reached a person at a terminal
    just as a warning in `validate`, one screen further away than it should be.
    """
    from engine import decisions, inbox, waivers
    nodes = _load(root)
    for nid, exc in sorted(waivers.requested_waivers(nodes).items()):
        print(f"WAIVER requested on {nid}  ({exc.get('kind') or 'no kind'})")
        print(f"  reason: {str(exc.get('reason') or '').strip() or '(none given)'}")
        if exc.get("proposed_expiry"):
            print(f"  proposed expiry: {exc['proposed_expiry']}")
        print("  grant it in the cockpit (Requests), or write state/owner/expires "
              "into the spec yourself -- only H grants.")
        print()
    for nid in sorted(nodes):
        for req in decisions.requests_of(nodes[nid]):
            if not isinstance(req, dict) or not req.get("target"):
                continue
            print(f"DECISION requested by {nid}  ->  {req['target']}")
            print(f"  proposal: {str(req.get('proposal', '')).strip()}")
            print(f"  reason:   {str(req.get('reason', '')).strip()}")
            print("  yours to decide: change the target, then delete the request "
                  "(the cockpit does both in one click).")
            print()
    if not accepted.tracked(root):
        print("not tracked: no accepted state yet (`accept ROOT --all` starts one).")
        return 0
    waiting = accepted.pending(nodes, root)
    briefs = assist.load(root)
    delegation = autonomy.delegated(root)
    for c in waiting:
        print(changeset.report(c, changeset.impact(nodes, root, c)))
        rej = c["rejected"]
        if rej:
            print(f"REJECTED by {rej['by']} ({rej['at'][:10]}): {rej['reason']}")
            print("the accepted spec -- restore it, or change the node differently:")
            print("\n".join("  " + ln for ln in assist.sides(nodes, root, c)[0].splitlines()))
        else:
            in_scope, why = autonomy.delegable_scope(c)
            if in_scope:
                mig = migration.check(nodes, root, c)
                print("migrated: yes (every consumer tested after the change)" if mig["migrated"]
                      else "migrated: no -- " + "; ".join(mig["missing"]))
            print(f"delegable: {'yes' if in_scope else 'no'} ({why})")
            print(assist.format_brief(assist.brief_for(root, c, briefs),
                                      stale=assist.is_stale(root, c, briefs)))
        print()
    review = accepted.awaiting_review(root)
    if review:
        print("accepted by H' under the delegation, awaiting your review:")
        state = accepted.load(root) or {}
        for nid in review:
            rec = state["nodes"][nid]
            print(f"  {nid}  ({rec.get('at', '')[:16]}, {rec.get('by')})")
        print("  confirm: accept ROOT ID  |  overrule: reject ROOT ID --reason ...")
        print()
    open_ = [c["node"] for c in waiting if not c["rejected"]]
    if open_:
        print(f"{len(open_)} HARD change(s) await a decision: accept ROOT {' '.join(open_)}"
              "  |  reject ROOT ID --reason ..."
              + ("  |  delegated: decide ROOT" if delegation else ""))
    asked = [r for r in inbox.pending(nodes, root) if r["type"] in ("waiver", "decision")]
    if asked:
        print(f"{len(asked)} request(s) await you as well: "
              + ", ".join(f"{r['type']} on {r['node']}" for r in asked))
    elif not waiting and not review:
        print("nothing awaits your decision.")
    who = ("H' may accept HARD changes in its scope" if delegation
           else "pending HARD changes are H's")
    print(f"delegation: {'on' if delegation else 'off'} ({who})")
    return 0


def cmd_prepare(root: str) -> int:
    """H' briefs every pending HARD change that has no fresh brief. Needs the
    planner's API key (cockpit/.env); the gate itself never does."""
    nodes = _load(root)
    if not accepted.tracked(root):
        print("not tracked: nothing can be pending.")
        return 0
    reviewer = _h_prime()
    arch = parser.load_architecture(root)
    try:
        done = assist.prepare(nodes, root, lambda report, old, cur: reviewer.brief_hard_change(
            report, old, cur, architecture=arch))
    except RuntimeError as exc:
        print(f"H' unavailable: {exc}", file=sys.stderr)
        return 2
    if not done:
        print("nothing to prepare: " + ("every pending HARD change has a fresh brief."
                                        if accepted.pending(nodes, root)
                                        else "no HARD change is pending."))
        return 0
    failed = [nid for nid, brief in done if brief is None]
    for nid, brief in done:
        if brief:
            conf = brief["confidence"]
            print(f"prepared {nid}: H' recommends {brief['recommendation'].upper()}"
                  + (f" ({conf:.2f})" if conf is not None else ""))
    if failed:
        print(f"H' gave no usable brief for {', '.join(failed)}.", file=sys.stderr)
        return 2
    return 0


def cmd_accept(root: str, ids: list[str], all_: bool, by: str | None) -> int:
    """H accepts the current state of the named nodes (or of everything)."""
    nodes = _load(root)
    by = by or getpass.getuser()
    if all_:
        n = accepted.accept_all(nodes, root, by=by)
        print(f"accepted the whole graph ({n} nodes + ARCHITECTURE.md) as {by}.")
        return 0
    if not ids:
        print("name the nodes to accept (see `pending ROOT`), or --all.", file=sys.stderr)
        return 2
    return _decide(nodes, root, ids, "accept", by)


def cmd_reject(root: str, ids: list[str], reason: str, by: str | None) -> int:
    """H rejects pending HARD changes; the gate blocks on them until they are gone."""
    if not ids:
        print("name the nodes to reject (see `pending ROOT`).", file=sys.stderr)
        return 2
    return _decide(_load(root), root, ids, "reject", by or getpass.getuser(), reason)


def _decide(nodes: dict, root: str, ids: list[str], decision: str, by: str,
            reason: str = "") -> int:
    try:
        done = assist.decide(nodes, root, ids, decision=decision, by=by, reason=reason)
    except (ValueError, accepted.Unreadable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for d in done:
        brief = d["brief"]
        note = f" -- H' had recommended {brief['recommendation']}" if brief else ""
        print(f"{d['action']} {d['node']} as {by}{note}")
    return 0


def _targets(nodes: dict) -> set[str]:
    """What a decision request may point at: ARCHITECTURE.md or a node that
    exists. The planner drops anything else before it reaches the file, because
    only H (or H' in an unsupervised run) deletes a request, and a bad target is a
    HARD error (engine/decisions)."""
    from engine import decisions
    return set(nodes) | {decisions.ARCHITECTURE}


def _load_env() -> None:
    """cockpit/.env: the API key, and role models not already set in the
    environment (a value set by the caller -- a run's command line -- wins)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_HERE / ".env")
    except ImportError:  # pragma: no cover
        pass


def _h_prime():
    """The reviewer (H'), with the key from cockpit/.env -- prepare and decide only."""
    _load_env()
    from agent import reviewer
    return reviewer


def _write_spec(root: str, nodes: dict, nid: str, text: str, path: Path, *,
                actor: str, by: str, action: str, intent: str, note: str = "") -> int:
    """Write what P produced, the way the cockpit's Save does: repair the YAML,
    show the change set against the accepted state, log who wrote it -- and
    record the intent it was grown from (engine/intents.py)."""
    import specfix
    from engine import intents, lifecycle
    text, _fixes = specfix.repair_frontmatter(text)
    try:
        before = accepted.before(root)
    except accepted.Unreadable:
        before = None
    assessed = changeset.assess(nodes, root, nid, text, before=before)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")
    gate = assessed[0]["gate"] if assessed else None
    lifecycle.log_autonomy(root, {"actor": actor, "by": by, "action": action, "node": nid,
                                  "gate": gate})
    intents.record(root, nid, action, intent, by=by, gate=gate, note=note)
    print(f"{action} {nid} -> {path}  (by {actor}: {by})")
    if note:
        print(f"P's note: {note}")
    print(changeset.report(*assessed) if assessed
          else "the result does not parse as a SPEC.md -- validate will say why")
    return 0


def cmd_draft(root: str, nid: str, parent: str, kind: str, intent: str) -> int:
    """P turns an intent into the SPEC.md of a NEW node. The node's place follows
    the layout rule (engine/nodes.py): its folder is the parent's folder plus the
    last segment of its id. The parent's SPEC.md is not touched."""
    from engine import nodes as nodeops
    nodes = _load(root)
    if nid in nodes:
        print(f"error: {nid} exists -- change its spec with `revise`", file=sys.stderr)
        return 2
    if parent not in nodes:
        print(f"error: no parent node {parent!r}", file=sys.stderr)
        return 2
    segment = nid.rsplit(".", 1)[-1]
    expected = nodeops.compute_id(nodes[parent], segment)
    if expected != nid:
        print(f"error: a child {segment!r} of {parent} has the id {expected!r}", file=sys.stderr)
        return 2
    _load_env()
    from agent import llm, planner
    # the Spine: every ancestor's contract. The planner's prompt derives the
    # node's code globs from the container's layout invariants "shown in the
    # ancestor contracts" -- given nothing, it guessed them (and C had to
    # correct svc/src/stats/** to svc/src/svc/stats/**).
    from engine import graph
    spine = {a: nodes[a].get("contract") for a in graph.spine(nodes, parent)}
    try:
        text = planner.draft_spec(intent, nid, parent, kind, spine,
                                  architecture=parser.load_architecture(root),
                                  capabilities=capability.build_registry(nodes),
                                  targets=_targets(nodes))
    except RuntimeError as exc:
        print(f"P unavailable: {exc}", file=sys.stderr)
        return 2
    path = Path(nodes[parent]["_dir"]) / segment / parser.SPEC_NAME
    return _write_spec(root, nodes, nid, text, path, actor="P", by=llm.planner_model(),
                       action="drafted", intent=intent)


def cmd_revise(root: str, nid: str, change: str) -> int:
    """P changes an existing SPEC.md per a change request, keeping what the
    request does not touch (status, code globs, waivers, requests)."""
    nodes = _load(root)
    if nid not in nodes:
        print(f"error: no node {nid!r} -- create it with `draft`", file=sys.stderr)
        return 2
    _load_env()
    from agent import llm, planner
    from engine import graph, nodes as nodeops
    path = Path(nodes[nid]["_path"])
    # the same view the draft had, plus who relies on this node: growing an
    # existing node is where additive-or-breaking is decided
    spine = {a: nodes[a].get("contract") for a in graph.spine(nodes, nid)[:-1]}
    try:
        text, note = planner.revise_spec(path.read_text(encoding="utf-8"), change,
                                         architecture=parser.load_architecture(root),
                                         spine=spine,
                                         consumers=nodeops.dependents_of(nodes, nid),
                                         targets=_targets(nodes), with_note=True)
    except RuntimeError as exc:
        print(f"P unavailable: {exc}", file=sys.stderr)
        return 2
    return _write_spec(root, nodes, nid, text, path, actor="P", by=llm.planner_model(),
                       action="revised", intent=change, note=note)


def cmd_compact(root: str, nid: str, force: bool = False) -> int:
    """P says the same spec in fewer words (planner.compact_spec) and it is written
    like a revise -- unless a `provides` name went missing on the way: then nothing
    is written and the lost names are said (--force writes all the same)."""
    nodes = _load(root)
    if nid not in nodes:
        print(f"error: no node {nid!r}", file=sys.stderr)
        return 2
    _load_env()
    from agent import llm, planner
    from engine import graph
    path = Path(nodes[nid]["_path"])
    current = path.read_text(encoding="utf-8")
    spine = {a: nodes[a].get("contract") for a in graph.spine(nodes, nid)[:-1]}
    try:
        text, note = planner.compact_spec(current, parser.load_architecture(root),
                                          spine=spine)
    except RuntimeError as exc:
        print(f"P unavailable: {exc}", file=sys.stderr)
        return 2
    lost = planner.lost_promises(current, text)
    if lost and not force:
        print(f"not written: compacting dropped {', '.join(lost)} from provides -- every "
              "promise must survive (--force writes it all the same)", file=sys.stderr)
        return 2
    print(f"{len(current.splitlines())} -> {len(text.splitlines())} lines")
    return _write_spec(root, nodes, nid, text, path, actor="P", by=llm.planner_model(),
                       action="compacted", intent="the same spec in fewer words", note=note)


def cmd_intents(root: str, nid: str | None) -> int:
    """The growth record: every intent a node (or the graph) was grown from."""
    from engine import intents
    entries = intents.history(root, nid)
    if nid is None:
        for node in sorted({e["node"] for e in entries}):
            print(f"{node}:")
            print("\n".join("  " + ln for ln in intents.format_history(
                [e for e in entries if e["node"] == node]).splitlines()))
        if not entries:
            print("(no recorded intent)")
    else:
        print(intents.format_history(entries))
    return 0


def cmd_code(root: str, nid: str, instruction: str | None) -> int:
    """C implements one node from its context bundle (engine/context.py), in the
    node's build root, as a codex agent on the coder's own endpoint
    (SGE_CODER_BASE_URL / _API_KEY / _MODEL). Streams C's output and keeps it in
    <root>/.sge/code/. C may take minutes."""
    import time
    from agent import coder
    from engine import context, lifecycle
    nodes = _load(root)
    if nid not in nodes:
        print(f"error: no node {nid!r}", file=sys.stderr)
        return 2
    _load_env()
    from agent import codex_cli
    try:
        command, env = codex_cli.command("coder")
    except RuntimeError as exc:
        print(f"C unavailable: {exc}", file=sys.stderr)
        return 2
    by = codex_cli.describe("coder")
    bundle = context.assemble(nodes, parser.load_architecture(root), nid, root)
    if instruction:
        bundle += f"\n\n# INSTRUCTION FROM THE INTENT AUTHOR\n{instruction}"
    log = Path(root) / ".sge" / "code" / f"{nid}-{time.strftime('%Y%m%dT%H%M%S')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = coder.implement(bundle, nid, nodes[nid], root, command=command, env=env)
    except OSError as exc:
        print(f"C could not start ({by}): {exc}", file=sys.stderr)
        return 2
    with log.open("w", encoding="utf-8") as out:
        for line in proc.stdout:  # type: ignore[union-attr]
            out.write(line)
            print(line, end="")
    code = proc.wait()
    lifecycle.log_autonomy(root, {"actor": "C", "by": by, "action": "coded",
                                  "node": nid, "exit": code})
    print(f"\nC finished (exit {code}); its output is in {log}")
    return code


def cmd_code_affected(root: str, nid: str) -> int:
    """C implements the node and whoever uses it -- its consumers by depends_on and
    the ancestors whose code imports it -- one after the other, what a node uses
    first (changeset.affected); then the tests, the whole build, and the gate.
    It stops at the first node C fails on. The same as Codex on each of them in
    turn, and Run Tests after: this is the order, done for you."""
    from engine import changeset
    nodes = _load(root)
    if nid not in nodes:
        print(f"error: no node {nid!r}", file=sys.stderr)
        return 2
    order = changeset.affected(nodes, root, nid)
    print("affected, in order: " + ", ".join(order))
    for i, node in enumerate(order, 1):
        print(f"\n===== {i}/{len(order)}  C implements {node} =====", flush=True)
        code = cmd_code(root, node, None)
        if code != 0:
            print(f"\nAFFECTED STOPPED at {node}: C ended with exit {code} -- "
                  f"{', '.join(order[i:]) or 'nothing'} not coded")
            return code
    print("\n===== the tests: the whole build =====", flush=True)
    tests = cmd_test(root)
    print("\n===== the gate =====", flush=True)
    gate = cmd_gate(root)
    green = tests == 0 and gate == 0
    print(f"\nAFFECTED {'DONE' if green else 'RED'}: {len(order)} node(s) coded; "
          f"tests {'pass' if tests == 0 else 'FAIL'}, gate {'pass' if gate == 0 else 'BLOCKS'}")
    return 0 if green else 1


def cmd_decide(root: str) -> int:
    """Under the delegation: H' decides every pending HARD change in its scope that E found
    migrated. The gate never does this; it stays offline."""
    nodes = _load(root)
    if not accepted.tracked(root):
        print("not tracked: nothing can be pending.")
        return 0
    reviewer = _h_prime()
    arch = parser.load_architecture(root)
    try:
        done = assist.delegated(nodes, root, lambda report, old, cur: reviewer.brief_hard_change(
            report, old, cur, architecture=arch))
    except ValueError as exc:
        print(str(exc))
        return 0
    except RuntimeError as exc:
        print(f"H' unavailable: {exc}", file=sys.stderr)
        return 2
    if not done:
        print("nothing to decide: no HARD change is pending.")
    for d in done:
        print(f"{d['action']:10} {d['node']}: {d['reason']}")
    return 0


def cmd_test(root: str) -> int:
    """Run the project's tests at every build root and record them as evidence
    (what the cockpit's Run Tests does). This is what `migrated` is checked
    against, and what `verified` needs -- headless, nothing else records it."""
    import subprocess
    import testrun
    nodes = _load(root)
    roots = testrun.build_roots(nodes, root)
    if not roots:
        print("no build root with a recognised test command.")
        return 0
    failed = False
    for build_root in roots:
        cmd = testrun.test_command(build_root)
        started = testrun.now()
        run = subprocess.run(cmd, cwd=str(build_root), capture_output=True, text=True)
        passed = run.returncode == 0
        failed |= not passed
        covered = testrun.record(nodes, root, build_root, passed, " ".join(cmd), started)
        # the runner's summary is the last line of STDOUT; stderr carries the
        # build tool's chatter ("Installed 6 packages")
        tail = (run.stdout.strip().splitlines() or run.stderr.strip().splitlines() or [""])[-1]
        print(f"{'PASS' if passed else 'FAIL'}  {build_root}  ({' '.join(cmd)}): {tail}")
        print(f"      evidence recorded for: {', '.join(covered) or '(no node)'}")
    return 1 if failed else 0


def cmd_manuals(root: str) -> int:
    """Re-render AGENTS.md and ORCHESTRATOR.md for this project from the method's
    templates -- after the templates changed, or the container did. The manuals
    are generated: an edit to them is lost here, which is why it belongs in the
    template."""
    import groundwork
    try:
        texts = groundwork.manuals(root)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, text in texts.items():
        path = Path(root) / name
        before = path.read_text(encoding="utf-8") if path.is_file() else None
        path.write_text(text, encoding="utf-8")
        print(f"{name}: " + ("unchanged" if before == text else
                             "written" if before is None else "refreshed"))
    return 0


def cmd_run(root: str, task: str | None, max_rounds: int, unsupervised: bool) -> int:
    """An agent grows the graph, in rounds (orchestrate.py) -- the cockpit's Start a
    run, without the window. It prints one readable line per event; the whole
    record lands in ROOT/.sge/runs/."""
    import orchestrate
    _load_env()     # the endpoints live in cockpit/.env; blockers() must see them
    missing = orchestrate.blockers(root, task, unsupervised=unsupervised)
    if missing:
        print("not ready for a run:\n" + "\n".join(f"  {m}" for m in missing),
              file=sys.stderr)
        return 2
    return orchestrate.main([root, orchestrate.first_prompt(unsupervised),
                             "--task", task or str(Path(root) / "TASK.md"),
                             "--max-rounds", str(max_rounds), "--readable",
                             *(["--unsupervised"] if unsupervised else [])])


def cmd_rename(root: str, node_id: str, new: str, by: str | None) -> int:
    """Rename a node and its subtree (engine/nodes.rename_node): every field that
    names it follows, its SPEC.md files move, its code stays where it is."""
    import getpass
    from engine import nodes as nodeops
    try:
        result = nodeops.rename_node(root, node_id, new, _load(root),
                                     by=by or getpass.getuser())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(nodeops.rename_text(result))
    return 0


def cmd_find(root: str, query: str) -> int:
    """Words in TASK.md, ARCHITECTURE.md and every SPEC.md -- the cockpit's Find in
    Specs: one `where:line: text` per hit. 0 when found, 1 when not."""
    from engine import search
    hits = search.find(root, _load(root), query)
    for hit in hits:
        print(f"{hit['where']}:{hit['line']}: {hit['text']}")
    return 0 if hits else 1


def cmd_check(root: str, task: str | None) -> int:
    """Does the project meet its goal, as it stands? E runs the tests and the gate,
    and on a green floor H' checks the result against TASK.md -- no agent, no
    session, no file changed (orchestrate.check). 0 only for `done`."""
    import orchestrate
    path = Path(task) if task else Path(root) / "TASK.md"
    if not path.is_file():
        print(f"no goal to check against: {path} does not exist", file=sys.stderr)
        return 2
    _load_env()     # H' is configured in cockpit/.env
    import time
    start = time.monotonic()

    def progress(step: str) -> None:            # it takes a while; say what it is doing
        n = orchestrate.CHECK_STEPS.index(step) + 1
        print(f"[{n}/{len(orchestrate.CHECK_STEPS)}] {step} ...  "
              f"({time.monotonic() - start:.0f}s)", file=sys.stderr, flush=True)
    result = orchestrate.check(str(Path(root).resolve()), path.read_text(encoding="utf-8"),
                               progress=progress)
    print(orchestrate.check_text(result))
    return 0 if result["verdict"] == "done" else 1


def cmd_delegate(root: str, state: str | None, by: str | None) -> int:
    """Show the delegation, or -- H's act -- turn it on or off."""
    if state is None:
        on = autonomy.delegated(root)
        print(f"delegation {'on' if on else 'off'}: "
              + ("H' may accept pending HARD changes in its scope (decide)"
                 if on else "pending HARD changes are H's"))
        return 0
    on = state == "on"
    autonomy.set_delegation(root, on, by=by or getpass.getuser())
    print(f"delegation turned {state} by {by or getpass.getuser()}.")
    return 0


def cmd_init(root: str, system_id: str, container: str, archetype: str, purpose: str,
             invariants: list[str], by: str | None, behaviours: list[str],
             always: list[str], out_of_scope: list[str], like: str | None = None) -> int:
    """Lay the floor of a NEW project (groundwork.py): the root, one container
    with its layout and build manifest, the invariants, and the accepted state.
    The guided version is the cockpit's; this one takes the answers as flags, so
    it scripts and so the steps have a door that needs no window. With `like`, the
    answers are those recorded when OLD's floor was laid, and TASK.md is OLD's."""
    import groundwork
    if like:
        try:
            actions = groundwork.like(like, by=by)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    elif not (system_id and container):
        print("error: --id and --container are needed (or --like OLD)", file=sys.stderr)
        return 2
    else:
        lines = list(groundwork.DEFAULT_INVARIANTS) + list(invariants or [])
        actions = groundwork.plan({"system_id": system_id, "purpose": purpose,
                                   "container": container, "archetype": archetype,
                                   "invariants": lines, "by": by or getpass.getuser(),
                                   "behaviours": "\n".join(behaviours),
                                   "always": "\n".join(always),
                                   "out_of_scope": "\n".join(out_of_scope)})
    try:
        for said in groundwork.apply(root, actions):
            print(said)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _load_env()
    print("\nroles, as a run would find them:")
    for role, where in groundwork.endpoints():
        print(f"  {role:9} {where}")
    goal = (Path(root) / "TASK.md").is_file()
    print("\nThe floor is laid, and the manuals name this project. What grows on it "
          "is not this command's business:\n"
          "  a person   -> open the cockpit on this root and draft the first component\n"
          + ("  a run      -> read TASK.md once more, then `cli.py run ROOT`" if goal else
             "  a run      -> write TASK.md next to the root, then `cli.py run ROOT`"))
    return 0


def cmd_duplicates(root: str) -> int:
    """Advisory: surface probable duplicate capabilities (lexical, never blocks)."""
    dups = capability.duplicates(_load(root), root)
    if not dups:
        print("no probable duplicate capabilities found.")
        return 0
    print(f"probable duplicate capabilities: {len(dups)}")
    for d in dups:
        print(f"  [{d['confidence'].upper()} {d['score']:.2f}] {d['a']} ~ {d['b']}")
        for r in d["reasons"]:
            print(f"      - {r}")
    return 0


def cmd_index(root: str) -> int:
    """Generate project.index.json (spec graph + capabilities + edges + evidence)."""
    path = index_mod.write_index(root)
    print(f"wrote {path}")
    return 0


def _find_git_dir(root: Path) -> Path | None:
    """Nearest ancestor containing a `.git` directory (a normal, non-worktree repo)."""
    for base in [root, *root.parents]:
        git = base / ".git"
        if git.is_dir():
            return git
    return None


def cmd_install_hook(root: str, force: bool = False) -> int:
    root_abs = Path(root).resolve()
    git_dir = _find_git_dir(root_abs)
    if git_dir is None:
        print(f"error: no git repository found at or above {root_abs}", file=sys.stderr)
        print("       run 'git init' there first.", file=sys.stderr)
        return 2
    hooks = git_dir / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    if hook.exists() and HOOK_MARKER not in hook.read_text(encoding="utf-8", errors="ignore") \
            and not force:
        print(f"error: {hook} exists and is not ours. Re-run with --force to overwrite.",
              file=sys.stderr)
        return 2
    script = (
        "#!/bin/sh\n"
        f"{HOOK_MARKER}\n"
        "# Auto-generated. Refuses a commit when spec and code have drifted.\n"
        f'exec uv run --project "{_HERE}" python "{_HERE / "cli.py"}" gate "{root_abs}"\n'
    )
    hook.write_text(script, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed pre-commit gate: {hook}")
    print(f"  -> runs: cli.py gate {root_abs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="spec", description="Spec Growth Engine gate")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "drift", "gate", "duplicates", "index"):
        sp = sub.add_parser(name)
        sp.add_argument("root", nargs="?", default=".")
    sp = sub.add_parser("init")
    sp.add_argument("root")
    sp.add_argument("--id", dest="system_id", help="the root node's id")
    sp.add_argument("--container", help="the first container's name")
    sp.add_argument("--like", metavar="OLD",
                    help="lay the floor OLD was laid with: its recorded answers, and "
                         "its TASK.md as it reads now")
    sp.add_argument("--archetype", default="python-uv-src",
                    help="code layout + build manifest (cockpit/layouts.py)")
    sp.add_argument("--purpose", default="", help="one or two sentences: what this is")
    sp.add_argument("--invariant", dest="invariants", action="append", default=[],
                    help="one line that holds everywhere; repeatable (the four "
                         "defaults are always written)")
    sp.add_argument("--by", help="who laid it (default: the login name)")
    sp.add_argument("--does", dest="behaviours", action="append", default=[],
                    help="a behaviour the system must have; repeatable. Giving any "
                         "of these (or --always) also writes TASK.md, the goal a run "
                         "is measured against")
    sp.add_argument("--always", action="append", default=[],
                    help="something that must hold across all behaviours; repeatable")
    sp.add_argument("--not-this", dest="out_of_scope", action="append", default=[],
                    help="out of scope: what nobody should grow; repeatable")
    sp = sub.add_parser("manuals")
    sp.add_argument("root")
    sp = sub.add_parser("find")
    sp.add_argument("root")
    sp.add_argument("query", help="words to find, case ignored")
    sp = sub.add_parser("compact")
    sp.add_argument("root")
    sp.add_argument("id")
    sp.add_argument("--force", action="store_true",
                    help="write even if a provides name went missing")
    sp = sub.add_parser("rename")
    sp.add_argument("root")
    sp.add_argument("id", help="the node to rename")
    sp.add_argument("new", help="its new LAST id part (or the whole new id)")
    sp.add_argument("--by", help="who renames it (default: the OS user)")
    sp = sub.add_parser("check")
    sp.add_argument("root")
    sp.add_argument("--task", help="the goal (default: ROOT/TASK.md)")
    sp = sub.add_parser("run")
    sp.add_argument("root")
    sp.add_argument("--task", help="the goal (default: ROOT/TASK.md)")
    sp.add_argument("--max-rounds", type=int, default=5)
    sp.add_argument("--unsupervised", action="store_true",
                    help="H' answers decision requests between rounds, in H's place "
                         "(needs the delegation on)")
    sp = sub.add_parser("install-hook")
    sp.add_argument("root", nargs="?", default=".")
    sp.add_argument("--force", action="store_true")
    sp = sub.add_parser("pending")
    sp.add_argument("root", nargs="?", default=".")
    sp = sub.add_parser("accept")
    sp.add_argument("root")
    sp.add_argument("ids", nargs="*", help="node ids, or ARCHITECTURE.md")
    sp.add_argument("--all", dest="all_", action="store_true",
                    help="accept the whole current graph (how a project starts tracking)")
    sp.add_argument("--by", help="who accepts (default: the login name)")
    sp = sub.add_parser("reject")
    sp.add_argument("root")
    sp.add_argument("ids", nargs="*", help="node ids, or ARCHITECTURE.md")
    sp.add_argument("--reason", required=True,
                    help="why -- the agent reads it in the gate's HARD error")
    sp.add_argument("--by", help="who rejects (default: the login name)")
    sp = sub.add_parser("prepare")
    sp.add_argument("root", nargs="?", default=".")
    for name in ("decide", "test"):
        sp = sub.add_parser(name)
        sp.add_argument("root", nargs="?", default=".")
    sp = sub.add_parser("draft")
    sp.add_argument("root")
    sp.add_argument("id")
    sp.add_argument("--parent", required=True)
    sp.add_argument("--kind", default="component", choices=("component", "container"))
    sp.add_argument("--intent", required=True, help="what the node is for, with examples")
    sp = sub.add_parser("revise")
    sp.add_argument("root")
    sp.add_argument("id")
    sp.add_argument("--change", required=True, help="what to change in the spec, and why")
    sp = sub.add_parser("intents")
    sp.add_argument("root")
    sp.add_argument("id", nargs="?")
    sp = sub.add_parser("code")
    sp.add_argument("root")
    sp.add_argument("id")
    sp.add_argument("--instruction", help="a note for C beyond the spec")
    sp.add_argument("--affected", action="store_true",
                    help="the node AND whoever uses it, in order, then the tests and "
                         "the gate (changeset.affected)")
    sp = sub.add_parser("delegate")
    sp.add_argument("root")
    sp.add_argument("state", nargs="?", choices=("on", "off"))
    sp.add_argument("--by", help="who sets it (default: the login name)")

    args = p.parse_args(argv)
    if args.cmd == "validate":
        return cmd_validate(args.root)
    if args.cmd == "drift":
        return cmd_drift(args.root)
    if args.cmd == "gate":
        return cmd_gate(args.root)
    if args.cmd == "duplicates":
        return cmd_duplicates(args.root)
    if args.cmd == "index":
        return cmd_index(args.root)
    if args.cmd == "init":
        return cmd_init(args.root, args.system_id, args.container, args.archetype,
                        args.purpose, args.invariants, args.by, args.behaviours,
                        args.always, args.out_of_scope, like=args.like)
    if args.cmd == "manuals":
        return cmd_manuals(args.root)
    if args.cmd == "find":
        return cmd_find(args.root, args.query)
    if args.cmd == "compact":
        return cmd_compact(args.root, args.id, args.force)
    if args.cmd == "rename":
        return cmd_rename(args.root, args.id, args.new, args.by)
    if args.cmd == "check":
        return cmd_check(args.root, args.task)
    if args.cmd == "run":
        if args.max_rounds < 1:
            print("error: --max-rounds must be at least 1", file=sys.stderr)
            return 2
        return cmd_run(args.root, args.task, args.max_rounds, args.unsupervised)
    if args.cmd == "install-hook":
        return cmd_install_hook(args.root, args.force)
    if args.cmd == "pending":
        return cmd_pending(args.root)
    if args.cmd == "accept":
        return cmd_accept(args.root, args.ids, args.all_, args.by)
    if args.cmd == "reject":
        return cmd_reject(args.root, args.ids, args.reason, args.by)
    if args.cmd == "prepare":
        return cmd_prepare(args.root)
    if args.cmd == "decide":
        return cmd_decide(args.root)
    if args.cmd == "test":
        return cmd_test(args.root)
    if args.cmd == "delegate":
        return cmd_delegate(args.root, args.state, args.by)
    if args.cmd == "draft":
        return cmd_draft(args.root, args.id, args.parent, args.kind, args.intent)
    if args.cmd == "revise":
        return cmd_revise(args.root, args.id, args.change)
    if args.cmd == "code":
        if args.affected:
            return cmd_code_affected(args.root, args.id)
        return cmd_code(args.root, args.id, args.instruction)
    if args.cmd == "intents":
        return cmd_intents(args.root, args.id)
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
