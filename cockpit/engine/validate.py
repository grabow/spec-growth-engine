"""Structural validation of the spec graph.

NOTE: this is the spec-side validator only (intent graph consistency). The
code-side evidence graph + spec<->code drift comparison is Phase 4 and is
language-specific; it is not implemented yet.
"""
from __future__ import annotations

from . import accepted, decisions, waivers, graph, lifecycle, parser


def run(nodes: dict[str, dict], root: str | None = None) -> str:
    errors: list[str] = []
    warnings: list[str] = []
    ids = set(nodes)

    # SPEC.md files with invalid YAML (dropped by the parser) -> HARD errors
    if root is not None:
        for rel, msg in parser.invalid_specs(root):
            errors.append(f"invalid YAML in {rel}: {msg}")

    for nid, n in nodes.items():
        parent = n.get("parent")
        if parent and parent not in ids:
            errors.append(f"orphan: {nid} -> unknown parent '{parent}'")

        for dep in n.get("depends_on") or []:
            if dep not in ids:
                errors.append(f"undeclared dependency: {nid} -> '{dep}' (no such node)")
            elif dep in graph.spine(nodes, nid) or nid in graph.spine(nodes, dep):
                # dep is self, an ancestor, or a descendant -> ownership, not usage
                errors.append(
                    f"dependency within ownership line (ancestor/descendant/self): {nid} -> {dep}"
                )
            elif not nodes[dep].get("contract"):
                errors.append(f"dependency without contract: {nid} -> {dep}")

        if n.get("kind") != "system" and not n.get("contract"):
            warnings.append(f"node without contract: {nid}")

    for cycle in graph.dependency_cycles(nodes):
        errors.append("dependency cycle: " + " -> ".join(cycle + [cycle[0]]))

    # waivers: typed / owned / time-boxed, and never masquerading as done.
    # Runs WITHOUT a root: it is a property of the spec text alone.
    for severity, msg in waivers.issues(nodes):
        (errors if severity == "HARD" else warnings).append(msg)

    # decision requests: questions above the asker's authority, pending until H
    # changes the target and deletes the request
    for severity, msg in decisions.issues(nodes):
        (errors if severity == "HARD" else warnings).append(msg)

    # status lifecycle: `verified` must be backed by test evidence (no fake completion)
    if root is not None:
        for severity, msg in lifecycle.status_issues(nodes, root):
            (errors if severity == "HARD" else warnings).append(msg)

    # HARD changes against the accepted state: pending, not blocking -- but never
    # `verified` until H accepts them (engine/accepted.py). Untracked -> nothing.
    if root is not None:
        for severity, msg in accepted.issues(nodes, root):
            (errors if severity == "HARD" else warnings).append(msg)

    lines = ["# Drift / structure report", f"nodes: {len(nodes)}",
             f"waivers: {waivers.summary(nodes)}",
             f"decisions: {decisions.summary(nodes)}"]
    if root is not None:
        lines.append(f"accepted: {accepted.summary(nodes, root)}")
    lines.append("")
    lines.append(f"HARD errors: {len(errors)}")
    lines += [f"  [x] {e}" for e in errors] or ["  (none)"]
    lines += ["", f"warnings: {len(warnings)}"]
    lines += [f"  [!] {w}" for w in warnings] or ["  (none)"]
    lines += ["", f"gate: {'BLOCK' if errors else 'pass'}"]
    return "\n".join(lines)
