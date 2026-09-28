"""The context assembler: Context(N), the scoped bundle for the coding agent.

Context(N) = ARCHITECTURE.md
           + SpineContracts(root -> N)
           + N.fullSpec
           + Contracts(deps(N))      (one hop, contract only)
           + OwnCode(N)

Output is plain ASCII text (no markdown rendering needed).
"""
from __future__ import annotations

import glob
from pathlib import Path

import yaml

from . import graph
from .evidence import EXCLUDED_DIRS

_MAX_CODE_FILES = 20


def _yaml(obj) -> str:
    # allow_unicode=False keeps the bundle strictly ASCII.
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=False).rstrip()


# Keys kept in an ancestor's short-form contract (a descendant only needs to know
# what the ancestor promises and which invariants it must preserve).
_SHORT_KEYS = ["purpose", "provides", "invariants"]


def _short_contract(contract):
    if not isinstance(contract, dict):
        return contract
    short = {k: contract[k] for k in _SHORT_KEYS if k in contract}
    return short or {"note": "no provides/invariants declared"}


def assemble(nodes: dict[str, dict], arch_md: str, target: str, project_root: str) -> str:
    if target not in nodes:
        return f"# ERROR\nUnknown node: {target}"
    n = nodes[target]
    out: list[str] = []

    # 1. ARCHITECTURE.md - global invariants (apply to every node)
    out.append("# ARCHITECTURE.md (global invariants, apply to every node)")
    out.append(arch_md.strip() or "(none)")

    # 2. Ancestor contracts - SHORT form (Spine, root -> ... -> parent)
    ancestors = graph.spine(nodes, target)[:-1]  # exclude the target itself
    out.append("\n# Ancestor contracts (Spine, short form)")
    if ancestors:
        for nid in ancestors:
            kind = nodes[nid].get("kind", "?")
            out.append(f"## {nid}  [{kind}]")
            out.append(_yaml({"contract": _short_contract(nodes[nid].get("contract", {}))}))
    else:
        out.append("(target is the root)")

    # 3. Target SPEC - FULL
    out.append(f"\n# Target node: {target} (full spec)")
    out.append(_yaml({k: v for k, v in n.items() if not k.startswith("_")}))
    if n.get("_body"):
        out.append(n["_body"].strip())

    # 4. Own code
    files = _own_code(n, project_root)
    out.append("\n# Own code")
    if files:
        for f in files[:_MAX_CODE_FILES]:
            out.append(f"--- {f} ---")
            try:
                # errors="replace": C reads this bundle, not a parser. A byte
                # that is not UTF-8 is a strange character in one line, never a
                # crash -- run 07 died here on a .pyc a code glob had caught.
                out.append(Path(f).read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                out.append(f"(could not read: {exc})")
    else:
        out.append("(none yet)")

    # 5. Dependency contracts - one hop, contract only
    deps = [d for d in (n.get("depends_on") or []) if isinstance(d, str)]
    out.append("\n# Dependency contracts (one hop, contract only)")
    if deps:
        for dep in deps:
            target_node = nodes.get(dep) or {}
            contract = target_node.get("contract", "(missing contract)")
            out.append(f"## {dep}")
            out.append(_yaml({"contract": contract}))
    else:
        out.append("(none)")

    return "\n".join(out)


def _own_code(node: dict, project_root: str) -> list[str]:
    """The node's own source files. A recursive glob (`src/svc/textfile/**`)
    also catches what the build leaves behind -- `__pycache__/*.pyc` in run 07 --
    so the build-output directories the evidence scanner skips are skipped here
    too: a bundle of bytecode teaches C nothing and costs it its context."""
    base = Path(project_root)  # code globs are project-root-relative
    found: list[str] = []
    for pattern in node.get("code") or []:
        if isinstance(pattern, str):
            found += glob.glob(str(base / pattern), recursive=True)
    return sorted(f for f in found if Path(f).is_file()
                  and not EXCLUDED_DIRS & set(Path(f).relative_to(base).parts))
