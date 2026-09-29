"""The drift gate: compare the code evidence graph to the declared specs.

No silent drift: a cross-owner import that is NOT a declared dependency is a HARD
error and blocks the gate. The AI is expected to fix the spec (add the edge) or
the code (remove the import) in the same commit.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import evidence, graph, parser

# Build output / vendored trees: one definition, in evidence, next to the glob
# resolution it governs. Importing it here keeps the orphan scan and ownership
# resolution from disagreeing about what counts as a file.
_EXCLUDE = evidence.EXCLUDED_DIRS
# Files that are never "code"/orphans: engine meta files (SPEC.md, ARCHITECTURE.md)
# and the agent execution-accelerator memory (AGENT-NOTES.md).
#
# NOT called AGENTS.md: that name is the conventional place for INSTRUCTIONS TO
# agents, and the coder is told to append to this file. Using one name for both
# would have the coder overwrite its own briefing.
_IGNORE_FILES = {"SPEC.md", "ARCHITECTURE.md", "AGENT-NOTES.md"}
# the graph itself: claiming one of these as `code` is over-claiming, not a typo
_GRAPH_FILES = {"SPEC.md", "ARCHITECTURE.md"}
_ORPHAN_CAP = 20


def run(nodes: dict[str, dict], project_root: str) -> str:
    ev = evidence.build_evidence(nodes, project_root)
    owners = ev["owners"]
    declared = {nid: set(n.get("depends_on") or []) for nid, n in nodes.items()}
    errors: list[str] = []
    warnings: list[str] = []

    # SPEC.md files that don't parse (dropped by parser -> their code globs are
    # not applied, so their files would look like orphans). Surface the real cause.
    for rel, msg in parser.invalid_specs(project_root):
        errors.append(f"invalid YAML in {rel}: {msg}")
    errors += parser.unloaded_specs(project_root)       # no id, or a duplicate one

    # A `code` glob must never claim the GRAPH ITSELF as its realization. This is
    # what makes `code: ["**"]` detectable: a glob broad enough to swallow the
    # spec tree is not a declaration of ownership, it is a way to leave no file
    # unowned. Claiming AGENT-NOTES.md is merely wrong (it is the coder's scratch
    # memory, never a contract), so that one warns rather than blocks.
    for f, ns in sorted(owners.items()):
        name = Path(f).name
        if name in _GRAPH_FILES:
            errors.append(
                f"{sorted(ns)} claims the spec file {_rel(project_root, f)} as code; "
                "`code` globs name the files that REALIZE a node, not the graph itself")
        elif name in _IGNORE_FILES:
            warnings.append(
                f"{sorted(ns)} claims {_rel(project_root, f)} as code; it is agent "
                "scratch memory, not a source file")

    # ownership conflicts (a file owned by >1 node)
    for f, ns in owners.items():
        if len(ns) > 1:
            errors.append(f"ownership conflict: {_rel(project_root, f)} owned by {sorted(ns)}")

    # cross-owner code edges must be declared dependencies -- EXCEPT edges along the
    # ownership line (a parent realized by / using its descendant's contract). Those
    # are realization, not usage, and may not be declared (validate forbids it).
    used: dict[str, set[str]] = defaultdict(set)
    for a, b in ev["edges"]:
        oa, ob = _single(owners[a]), _single(owners[b])
        if oa and ob and oa != ob:
            if _ownership_line(nodes, oa, ob):
                continue  # ancestor<->descendant realization edge, allowed
            used[oa].add(ob)
            if ob not in declared.get(oa, set()):
                errors.append(
                    f"undeclared dependency: {oa} -> {ob} "
                    f"(code {_rel(project_root, a)} imports {_rel(project_root, b)})"
                )

    # declared dependencies with no code evidence (warning)
    # The same fact means two different things depending on how far the node is.
    # Spec-first work declares a dependency BEFORE the code exists, so at `specd`
    # the missing import is the expected state, not a discrepancy -- saying
    # "without code evidence" there reads as an error at the one moment the
    # method prescribes it. Once a node claims to be implemented, it is a
    # discrepancy again.
    _UNBUILT = ("specd", "in-slice")
    for nid, deps in declared.items():
        for d in deps:
            if d in used.get(nid, set()):
                continue
            if nodes.get(nid, {}).get("status") in _UNBUILT:
                warnings.append(
                    f"declared dependency not yet realized: {nid} -> {d} "
                    f"(node is still '{nodes[nid].get('status')}'; expected before the code exists)")
            else:
                warnings.append(f"declared dependency without code evidence: {nid} -> {d}")

    # orphan source files (in scope, no spec owner). "In scope" = file extensions
    # that some node actually declares via its code globs, so the check covers
    # exactly the languages this project uses (Python, TS, ... ) - no hardcoding.
    declared_exts = _declared_extensions(nodes)
    manifest_exts = _manifest_extensions(project_root)
    exts = declared_exts | manifest_exts

    # `excluded`: files deliberately outside the graph (generated sources, project
    # scripts, fixtures in the project's own language). Removed from the orphan
    # scan and nothing else -- exclusion never grants ownership.
    excluded = evidence.excluded_map(nodes, project_root)
    orphans = _orphans(project_root, owners, exts, set(excluded))

    # A file both owned and excluded is incoherent intent. Ownership wins (the
    # contract is unambiguous), so this is a stale line rather than a danger.
    for f in sorted(set(excluded) & set(owners)):
        warnings.append(
            f"{_rel(project_root, f)} is both owned by {sorted(owners[f])} and "
            f"excluded by {sorted(excluded[f])}; ownership wins, drop the exclusion")

    # An exclusion that matches nothing has quietly stopped meaning anything.
    for nid, pattern in evidence.stale_exclusions(nodes, project_root):
        warnings.append(f"excluded glob matches no file: {nid} -> {pattern!r}")

    # An exclusion must NAME what it excludes. A pattern of nothing but wildcards
    # excludes the whole project and silently disables the orphan check, which is
    # a HARD check -- one line would otherwise turn the gate off.
    for nid in sorted(nodes):
        for pattern in nodes[nid].get("excluded") or []:
            if isinstance(pattern, str) and not _names_something(pattern):
                errors.append(
                    f"excluded glob {pattern!r} on {nid} names nothing: an exclusion "
                    "must say WHICH files are outside the graph, not 'all of them'")

    # More excluded than specified is a shape worth seeing even when each single
    # glob looks reasonable.
    if len(excluded) > len(owners) and excluded:
        warnings.append(
            f"more files are excluded ({len(excluded)}) than owned ({len(owners)}); "
            "exclusions are meant to be the exception, not the rule")

    # An empty scan scope means the orphan check DID NOT RUN. Without this the
    # report is indistinguishable from a clean one: a project whose language the
    # engine does not recognise reports success. Quiet only for a graph that
    # claims no code at all (a freshly bootstrapped root).
    if not exts and _claims_code(nodes):
        warnings.append(
            "scan scope is EMPTY: no `code` glob names a file extension and no build "
            "manifest was recognised, so the orphan check did not run (nodes DO declare "
            "code). Name an extension in a glob, or add/recognise a build manifest.")

    hard = len(errors) + len(orphans)
    lines = [
        "# Code drift report (evidence graph vs declared specs)",
        f"project: {project_root}",
        f"owned source files: {len(owners)}   code edges: {len(ev['edges'])}",
        f"scan scope: {_scope_note(declared_exts, manifest_exts)}",
        f"excluded: {_excluded_note(nodes, excluded)}",
        "",
        f"HARD errors: {hard}",
    ]
    lines += [f"  [x] {e}" for e in errors]
    lines += [f"  [x] orphan code (no spec owner): {o}" for o in orphans[:_ORPHAN_CAP]]
    if len(orphans) > _ORPHAN_CAP:
        lines.append(f"      ... and {len(orphans) - _ORPHAN_CAP} more orphan(s)")
    if hard == 0:
        lines.append("  (none)")
    lines += ["", f"warnings: {len(warnings)}"]
    lines += [f"  [!] {w}" for w in warnings] or ["  (none)"]
    lines += ["", f"gate: {'BLOCK' if hard else 'pass'}"]
    return "\n".join(lines)


def _scope_note(declared: set[str], manifest: set[str]) -> str:
    """Human-readable scan scope, so an empty one is visible rather than implied."""
    if not declared and not manifest:
        return "EMPTY (orphan check did not run)"
    parts = []
    if declared:
        parts.append(f"{', '.join(sorted(declared))} (declared)")
    if manifest - declared:
        parts.append(f"{', '.join(sorted(manifest - declared))} (from build manifests)")
    return "   ".join(parts)


def _single(owner_set: set[str]) -> str | None:
    return next(iter(owner_set)) if len(owner_set) == 1 else None


def _ownership_line(nodes: dict[str, dict], a: str, b: str) -> bool:
    """True if a and b are on the same ownership line (one is the other's ancestor):
    a parent using its descendant's code is realization, not a dependency."""
    return b in graph.spine(nodes, a) or a in graph.spine(nodes, b)


def _rel(root: str, f: str) -> str:
    try:
        return str(Path(f).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return f


# A build manifest declares the project's language even when no `code` glob names
# a file extension (e.g. a node owns a package via `pkg/**`). Without this, a glob
# ending in `**` contributes no suffix and orphans of that language slip through.
_MANIFEST_EXTS = {
    "pom.xml": {".java"},
    "build.gradle": {".java", ".kt"},
    "build.gradle.kts": {".java", ".kt"},
    "settings.gradle": {".java", ".kt"},
    "settings.gradle.kts": {".java", ".kt"},
    "pyproject.toml": {".py"},
    "setup.py": {".py"},
    "Cargo.toml": {".rs"},
    "pubspec.yaml": {".dart"},
    "package.json": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"},
}


def _manifest_extensions(project_root: str) -> set[str]:
    """Source extensions implied by any build manifest in the tree (pom.xml ->
    .java, pyproject.toml -> .py, ...). This keeps the language in scope even when
    no node names that extension, so deleting/rewriting an owner cannot silently
    drop its code from the orphan scan."""
    exts: set[str] = set()
    root = Path(project_root)
    for p in root.rglob("*"):
        if p.name in _MANIFEST_EXTS and not evidence.is_excluded(p):
            exts |= _MANIFEST_EXTS[p.name]
    return exts


def _declared_extensions(nodes: dict[str, dict]) -> set[str]:
    """Extensions named by a `code` glob ('*.py' -> '.py'). A glob ending in `**`
    names none, which is why the manifests above matter."""
    exts: set[str] = set()
    for n in nodes.values():
        for glob in n.get("code") or []:
            if isinstance(glob, str) and Path(glob).suffix:
                exts.add(Path(glob).suffix)
    return exts


def _claims_code(nodes: dict[str, dict]) -> bool:
    """True if any node declares a non-empty `code` list -- i.e. the graph says
    this project HAS source files. Distinguishes a fresh, empty graph (nothing to
    scan, correctly quiet) from a real project the scanner cannot see."""
    return any(n.get("code") for n in nodes.values())


def _scanned_extensions(nodes: dict[str, dict], project_root: str) -> set[str]:
    """File extensions in scope for the orphan scan.

    Union of (a) extensions some node declares via its code globs ('*.py' ->
    '.py', 'src/**/*.tsx' -> '.tsx') and (b) extensions implied by the project's
    build manifests (pom.xml -> '.java'). (b) covers directory globs like
    'pkg/**' that name no extension. Only languages the project actually uses are
    scanned -- still no hardcoding of a universal extension list.
    """
    exts: set[str] = set()
    for n in nodes.values():
        for glob in n.get("code") or []:
            if isinstance(glob, str):
                suffix = Path(glob).suffix
                if suffix:
                    exts.add(suffix)
    return exts | _manifest_extensions(project_root)


def _names_something(pattern: str) -> bool:
    """True if a glob names at least one literal character -- a directory, a file
    or an extension. `**`, `*`, `**/*`, `*/**` name nothing."""
    return bool(pattern.replace("*", "").replace("/", "").replace("?", "").strip())


def _excluded_note(nodes: dict[str, dict], excluded: dict[str, set[str]]) -> str:
    """Exclusions are permanent by design, so they must stay VISIBLE -- otherwise
    `excluded` becomes the quiet way to make the gate stop complaining."""
    declarations = sum(len(n.get("excluded") or []) for n in nodes.values())
    if not declarations:
        return "none"
    return f"{len(excluded)} file(s) via {declarations} declaration(s)"


def _orphans(project_root: str, owners: dict[str, set[str]], exts: set[str],
             excluded: set[str] | None = None) -> list[str]:
    if not exts:  # no code declared anywhere -> nothing is "in scope"
        return []
    root = Path(project_root)
    out: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in exts:
            continue
        if p.name in _IGNORE_FILES:  # AGENT-NOTES.md = accelerator, never owned
            continue
        if evidence.is_excluded(p):
            continue
        resolved = str(p.resolve())
        if resolved in owners or resolved in (excluded or ()):
            continue
        out.append(_rel(project_root, p))
    return sorted(out)
