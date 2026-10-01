"""Code evidence graph (multi-language).

Builds, from the actual source files, what the code *really* does:
  - which spec node owns each source file (via each node's `code` globs)
  - which files import which (regex/heuristic based, no language toolchain)

This is the "Evidence" side; `drift.py` compares it to the "Intent" side
(the declared `depends_on` in the specs).

Import-edge detection is per-language and resolves only to files that are
themselves owned by some node (edges to external/library code are ignored):
  - TS/JS  : relative specifiers (./x, ../y) + require()/dynamic import()
  - Java   : fully-qualified `import a.b.C;` + wildcard `import a.b.*;`
  - Kotlin : `import a.b.C` / `import a.b.foo` (+ `as alias`) + wildcard
  - Dart   : relative + `part` imports, and `package:<name>/...` -> lib/...
  - Python : `import a.b`, `from a.b import c`, and relative `from .m import x`
"""
from __future__ import annotations

import glob as _glob
import re
from collections import defaultdict
from pathlib import Path

from . import graph

# ---------------------------------------------------------------- TS / JS ----
# import x from '...' / export ... from '...'
_FROM = re.compile(r"""\bfrom\s*['"]([^'"]+)['"]""")
# side-effect import '...'
_SIDE = re.compile(r"""\bimport\s*['"]([^'"]+)['"]""")
# require('...')
_REQ = re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)""")
# dynamic import('...')
_DYN = re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""")

_TS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".cts", ".mts"}
_CAND_SUFFIX = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cts", ".mts"]
_CAND_INDEX = ["index.ts", "index.tsx", "index.js"]

# ------------------------------------------------------------------- JVM -----
_JVM_EXT = {".java", ".kt", ".kts"}
# `import a.b.C;` (java) / `import a.b.C` / `import a.b.C as D` (kotlin)
_JVM_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)(?:\.\*)?\s*(?:as\s+\w+)?;?\s*$", re.M)
_JVM_WILDCARD = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\.\*\s*;?\s*$", re.M)
_JVM_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;?\s*$", re.M)
# top-level Kotlin declarations whose name an importer may reference
_KT_DECL = re.compile(
    r"^\s*(?:public\s+|internal\s+|open\s+|abstract\s+|sealed\s+|data\s+|"
    r"final\s+|enum\s+|annotation\s+)*"
    r"(?:class|interface|object|fun|val|var|typealias)\s+([A-Za-z_]\w*)",
    re.M,
)

# ------------------------------------------------------------------ Dart -----
_DART_EXT = {".dart"}
# import/export/part with a quoted target
_DART_DIRECTIVE = re.compile(
    r"""\b(?:import|export|part)\s+['"]([^'"]+)['"]"""
)

# ---------------------------------------------------------------- Python -----
_PY_EXT = {".py", ".pyi"}
_PY_IMPORT = re.compile(r"^\s*import\s+([\w.]+)(?:\s+as\s+\w+)?", re.M)
# from a.b.c import x  /  from . import x  /  from ..pkg import y
_PY_FROM = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+(.+)$", re.M)


# --------------------------------------------------------------- ownership ---
# Directories that hold BUILD OUTPUT or vendored code: never authored, so never
# owned. Defined once, here, because ownership is resolved here -- drift and
# attribution import it rather than keeping their own copies, which had already
# drifted apart (one knew `.sge` and `venv`, the other did not).
#
# Note what is NOT in this list: SPEC.md and ARCHITECTURE.md. A glob matching a
# generated .pyc is an accident of when the tests last ran -- making it an error
# would let the gate's result depend on that. A glob matching a spec file is an
# authoring mistake, so it stays visible and drift reports it (glossary 3.2c).
EXCLUDED_DIRS = {
    "node_modules", "dist", "build", "out", "bin", "target",      # build output
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",      # tooling
    ".idea", ".gradle", ".dart_tool", ".sge",
}


def is_excluded(path: str | Path) -> bool:
    """True for a path inside a build-output or vendored directory."""
    return any(part in EXCLUDED_DIRS for part in Path(path).parts)


def resolve_globs(globs, project_root: str | Path) -> list[str]:
    """Resolved absolute paths for PROJECT-ROOT-relative globs (spec location is
    independent of code location). Shared by `code` and `excluded`.

    Build output is filtered out: `src/foo/**` written by a human legitimately
    starts matching `src/foo/__pycache__/*.pyc` after the first test run, and a
    node's ownership must not change because its tests were executed."""
    base = Path(project_root)
    out: list[str] = []
    for pattern in globs or []:
        if not isinstance(pattern, str):
            continue
        for found in _glob.glob(str(base / pattern), recursive=True):
            p = Path(found)
            if p.is_file() and not is_excluded(p):
                out.append(str(p.resolve()))
    return out


def resolve_node_files(node: dict, project_root: str | Path) -> list[str]:
    """Resolved absolute paths owned by `node` via its `code` globs."""
    return resolve_globs(node.get("code"), project_root)


def excluded_map(nodes: dict[str, dict],
                 project_root: str | Path) -> dict[str, set[str]]:
    """Map each DECLARED-EXCLUDED file -> the node ids that excluded it.

    `excluded` says a file is deliberately outside the graph: generated sources,
    project scripts, fixtures in the project's own language. It removes the file
    from the orphan scan and nothing else -- it never grants ownership, so an
    excluded file has no contract and takes part in no import edge.
    """
    out: dict[str, set[str]] = defaultdict(set)
    for nid, node in nodes.items():
        for f in resolve_globs(node.get("excluded"), project_root):
            out[f].add(nid)
    return out


def stale_exclusions(nodes: dict[str, dict],
                     project_root: str | Path) -> list[tuple[str, str]]:
    """(node id, glob) for `excluded` globs that match no file -- a typo or a
    leftover. Without this, an exclusion list silently stops meaning anything."""
    base = Path(project_root)
    out: list[tuple[str, str]] = []
    for nid in sorted(nodes):
        for pattern in nodes[nid].get("excluded") or []:
            if not isinstance(pattern, str):
                continue
            if not any(Path(f).is_file()
                       for f in _glob.glob(str(base / pattern), recursive=True)):
                out.append((nid, pattern))
    return out


def ownership_map(nodes: dict[str, dict], project_root: str | Path) -> dict[str, set[str]]:
    """Map each owned source file (resolved abs path) -> set of owning node ids.
    Code globs are resolved relative to the PROJECT ROOT, not the node's folder.

    On ONE ownership line the most specific owner wins: a component whose glob
    covers a file of its sub-component gives that file up -- the sub-component
    carves it out, and nobody has to narrow the parent's glob by hand. Owners
    that are NOT on one line keep the file together: that is the ownership
    conflict drift reports."""
    owners: dict[str, set[str]] = defaultdict(set)
    for nid, node in nodes.items():
        for f in resolve_node_files(node, project_root):
            owners[f].add(nid)
    for f, who in owners.items():
        if len(who) > 1:
            deepest = most_specific(nodes, who)
            if deepest:
                owners[f] = {deepest}
    return owners


def most_specific(nodes: dict[str, dict], who: set[str]) -> str | None:
    """The one of `who` all the others are ancestors of -- None when they do not
    lie on one ownership line."""
    for nid in who:
        if who <= set(graph.spine(nodes, nid)):
            return nid
    return None


# ----------------------------------------------------------------- TS / JS ---
def scan_imports(path: Path) -> list[str]:
    """Return the raw TS/JS import specifiers found in a source file."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    specs: list[str] = []
    for rx in (_FROM, _SIDE, _REQ, _DYN):
        specs += rx.findall(text)
    return specs


def resolve(importer: Path, spec: str) -> Path | None:
    """Resolve a relative TS/JS import specifier to a real file (or None)."""
    if not spec.startswith("."):
        return None  # bare/external (node_modules / workspace alias) - ignored in MVP
    base = importer.parent / spec
    for suffix in _CAND_SUFFIX:
        cand = base.with_name(base.name + suffix) if suffix else base
        if cand.is_file():
            return cand.resolve()
    for index in _CAND_INDEX:
        cand = base / index
        if cand.is_file():
            return cand.resolve()
    return None


def _ts_edges(files: list[str], owners: dict[str, set[str]]) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for f in files:
        fp = Path(f)
        if fp.suffix not in _TS_EXT:
            continue
        for spec in scan_imports(fp):
            target = resolve(fp, spec)
            if target and str(target) in owners:
                edges.append((f, str(target)))
    return edges


# --------------------------------------------------------------------- JVM ---
def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _jvm_index(files: list[str]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Build (fqn -> file, package -> {files}) for owned JVM files.

    Java: fqn = package + filename stem. Kotlin: package + each top-level decl
    name (filename stem too, as a fallback)."""
    by_fqn: dict[str, str] = {}
    by_pkg: dict[str, set[str]] = defaultdict(set)
    for f in files:
        fp = Path(f)
        if fp.suffix not in _JVM_EXT:
            continue
        text = _read(f)
        m = _JVM_PACKAGE.search(text)
        pkg = m.group(1) if m else ""
        by_pkg[pkg].add(f)
        stem = fp.stem
        names = {stem}
        if fp.suffix in (".kt", ".kts"):
            names |= set(_KT_DECL.findall(text))
        for name in names:
            fqn = f"{pkg}.{name}" if pkg else name
            by_fqn.setdefault(fqn, f)
    return by_fqn, by_pkg


def _jvm_edges(files: list[str], owners: dict[str, set[str]]) -> list[tuple[str, str]]:
    by_fqn, by_pkg = _jvm_index(files)
    if not by_fqn and not by_pkg:
        return []
    edges: list[tuple[str, str]] = []
    for f in files:
        fp = Path(f)
        if fp.suffix not in _JVM_EXT:
            continue
        text = _read(f)
        wildcards = set(_JVM_WILDCARD.findall(text))
        for fqn in _JVM_IMPORT.findall(text):
            target = by_fqn.get(fqn)
            if target and target != f and target in owners:
                edges.append((f, target))
        for pkg in wildcards:
            for target in by_pkg.get(pkg, ()):  # import a.b.* -> all owned files in a.b
                if target != f and target in owners:
                    edges.append((f, target))
    return edges


# -------------------------------------------------------------------- Dart ---
def _dart_resolve(importer: Path, spec: str, project_root: Path) -> Path | None:
    if spec.startswith("dart:"):
        return None  # SDK
    if spec.startswith("package:"):
        # package:<name>/<rest>  ->  <pkg-root>/lib/<rest>
        rest = spec.split("/", 1)
        if len(rest) != 2:
            return None
        sub = rest[1]
        for base in [importer.parent, *importer.parents]:
            if (base / "pubspec.yaml").is_file():
                cand = base / "lib" / sub
                return cand.resolve() if cand.is_file() else None
            if base == project_root:
                break
        return None
    if ":" in spec:
        return None  # other schemes
    cand = (importer.parent / spec)
    return cand.resolve() if cand.is_file() else None


def _dart_edges(
    files: list[str], owners: dict[str, set[str]], project_root: Path
) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for f in files:
        fp = Path(f)
        if fp.suffix not in _DART_EXT:
            continue
        for spec in _DART_DIRECTIVE.findall(_read(f)):
            target = _dart_resolve(fp, spec, project_root)
            if target and str(target) in owners:
                edges.append((f, str(target)))
    return edges


# ------------------------------------------------------------------ Python ---
def _py_module_file(parts: list[str], roots: list[Path]) -> Path | None:
    """Resolve a dotted module ['a','b','c'] to a .py / package file under any root."""
    for root in roots:
        base = root.joinpath(*parts)
        for cand in (base.with_suffix(".py"), base / "__init__.py", base.with_suffix(".pyi")):
            if cand.is_file():
                return cand.resolve()
    return None


def _py_edges(
    files: list[str], owners: dict[str, set[str]], project_root: Path
) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    py_files = [f for f in files if Path(f).suffix in _PY_EXT]
    if not py_files:
        return []
    # Absolute imports may be rooted at project_root or any owned-file ancestor.
    abs_roots = {project_root}
    for f in py_files:
        abs_roots.update(Path(f).parents)
    abs_roots = list(abs_roots)

    def _emit(importer: str, target: Path | None) -> None:
        if target and str(target) in owners and str(target) != importer:
            edges.append((importer, str(target)))

    for f in py_files:
        fp = Path(f)
        text = _read(f)
        # plain `import a.b.c`
        for mod in _PY_IMPORT.findall(text):
            _emit(f, _py_module_file(mod.split("."), abs_roots))
        # `from <dots><module> import names`
        for dots, module, names in _PY_FROM.findall(text):
            if dots:  # relative import
                base = fp.parent
                for _ in range(len(dots) - 1):
                    base = base.parent
                mod_parts = module.split(".") if module else []
                roots = [base]
            else:  # absolute
                mod_parts = module.split(".")
                roots = abs_roots
            # the module itself (e.g. `from a.b import c` -> a/b.py providing c)
            if mod_parts:
                _emit(f, _py_module_file(mod_parts, roots))
            # each imported name may itself be a submodule (a/b/c.py)
            for raw in names.split(","):
                name = raw.split(" as ")[0].strip().strip("()").strip()
                if not name or name == "*":
                    continue
                _emit(f, _py_module_file([*mod_parts, name], roots))
    return edges


# -------------------------------------------------- external dependencies ----
# Used by the duplicate detector (capability.py): "two nodes that both import a
# PDF library, with similar surfaces, probably duplicate the same capability".
_JVM_STDLIB = ("java.", "javax.", "jakarta.", "kotlin.", "kotlinx.", "scala.", "android.")
_PY_STDLIB = {
    "os", "sys", "re", "io", "json", "math", "time", "datetime", "pathlib",
    "typing", "collections", "itertools", "functools", "dataclasses", "abc",
    "enum", "logging", "subprocess", "threading", "asyncio", "unittest",
    "argparse", "glob", "shutil", "tempfile", "random", "string", "hashlib",
    "base64", "uuid", "copy", "contextlib", "warnings", "traceback", "csv",
    "sqlite3", "socket", "struct", "pickle", "configparser", "decimal",
    "__future__", "operator", "inspect", "types", "weakref",
}


def _ts_lib(spec: str) -> str | None:
    if spec.startswith(".") or ":" in spec:
        return None
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def _file_external_libs(
    f: str,
    by_fqn: dict[str, str],
    by_pkg: dict[str, set[str]],
    abs_roots: list[Path],
    owners: dict[str, set[str]],
) -> set[str]:
    fp = Path(f)
    text = _read(f)
    libs: set[str] = set()
    if fp.suffix in _TS_EXT:
        for spec in scan_imports(fp):
            lib = _ts_lib(spec)
            if lib:
                libs.add(lib)
    elif fp.suffix in _JVM_EXT:
        for fqn in _JVM_IMPORT.findall(text):
            if fqn in by_fqn:  # owned -> internal
                continue
            if fqn.startswith(_JVM_STDLIB):
                continue
            libs.add(".".join(fqn.split(".")[:3]))
    elif fp.suffix in _DART_EXT:
        for spec in _DART_DIRECTIVE.findall(text):
            if spec.startswith("package:"):
                libs.add("package:" + spec[len("package:"):].split("/")[0])
    elif fp.suffix in _PY_EXT:
        mods: set[str] = set()
        mods.update(_PY_IMPORT.findall(text))
        for dots, module, _names in _PY_FROM.findall(text):
            if not dots and module:
                mods.add(module)
        for mod in mods:
            top = mod.split(".")[0]
            if top in _PY_STDLIB:
                continue
            if _py_module_file(mod.split("."), abs_roots):  # owned -> internal
                continue
            libs.add(top)
    return libs


def external_dependencies(
    nodes: dict[str, dict], project_root: str | Path
) -> dict[str, set[str]]:
    """Map node id -> set of external library identifiers its owned files import.

    Intra-project (owned) and standard-library imports are excluded; what remains
    is the third-party surface that signals a possible shared capability."""
    root = Path(project_root)
    owners = ownership_map(nodes, project_root)
    files = list(owners)
    by_fqn, by_pkg = _jvm_index(files)
    abs_roots = {root}
    for f in files:
        if Path(f).suffix in _PY_EXT:
            abs_roots.update(Path(f).parents)
    abs_roots_list = list(abs_roots)
    out: dict[str, set[str]] = defaultdict(set)
    for f, nids in owners.items():
        libs = _file_external_libs(f, by_fqn, by_pkg, abs_roots_list, owners)
        for nid in nids:
            out[nid] |= libs
    return out


# --------------------------------------------------------------- evidence ----
def build_evidence(nodes: dict[str, dict], project_root: str | Path) -> dict:
    """Return {'owners': {file: {nid}}, 'edges': [(importer, imported)]}.

    Import edges are detected per language (TS/JS, Java, Kotlin, Dart, Python)
    and kept only when both endpoints are owned source files."""
    root = Path(project_root)
    owners = ownership_map(nodes, project_root)
    files = list(owners)
    edges: list[tuple[str, str]] = []
    edges += _ts_edges(files, owners)
    edges += _jvm_edges(files, owners)
    edges += _dart_edges(files, owners, root)
    edges += _py_edges(files, owners, root)
    # de-duplicate while preserving order
    seen: set[tuple[str, str]] = set()
    uniq: list[tuple[str, str]] = []
    for e in edges:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return {"owners": owners, "edges": uniq}
