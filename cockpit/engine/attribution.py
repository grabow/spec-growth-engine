"""Per-node test attribution: which tests exercise which node.

The lifecycle gate records evidence per BUILD ROOT: a test run marks every node
under that root as covered, so a node with no test of its own inherits a green
run from its neighbours. The recorded fact is "something under this build root
passed", not "this node is tested" (LIFECYCLE.md 5a).

This module narrows that. It attributes each test file to the nodes it actually
exercises, by two deterministic routes:

  OWNED    the test file falls under a node's own `code` globs (e.g. a Maven
           component owning `src/test/java/**/<name>/**`) -> that node.
  IMPORTS  the test file imports a file owned by a node -> that node. This
           reuses the evidence import graph, which keeps an edge whenever the
           TARGET is owned -- the importer need not be.

It is not a proof of coverage: attribution is static, so a test exercising code
only through reflection, a fixture, a subprocess or an unresolvable import is
invisible here. Hence the lifecycle check built on it WARNS; it does not block.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import evidence

# Directory segments and filename shapes that mark a test across the languages
# the evidence scanner understands. Conservative on purpose: a false "this is a
# test" would attribute evidence that does not exist.
_TEST_DIRS = {"test", "tests", "__tests__", "spec", "testing"}
# Deliberately CASE-SENSITIVE for the JVM suffixes: the convention there is
# PascalCase (FooTest.java), and an insensitive match turns "Attest.kt" into a
# test ("At" + "test"). The other shapes are delimited by `_` or `.`, so they
# cannot swallow a word the same way.
_TEST_NAME = re.compile(
    r"""^(?:
        [Tt]est_.+\.pyi?                        # test_foo.py
      | .+_test\.(?:py|dart|go)                 # foo_test.py / foo_test.dart
      | .+(?:Test|Tests|IT|ITCase)\.(?:java|kt|kts)   # FooTest.java, OrderIT.java
      | .+\.(?:test|spec)\.[jt]sx?              # foo.test.ts, foo.spec.tsx
    )$""",
    re.VERBOSE,
)
_SCANNABLE = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
              ".java", ".kt", ".kts", ".dart", ".py", ".pyi"}
# build output / vendored trees are never sources of evidence -- the same
# definition drift and ownership use (evidence.EXCLUDED_DIRS)


def is_test_file(path: str | Path) -> bool:
    """True for a path that looks like a test by directory or by filename."""
    p = Path(path)
    if p.suffix not in _SCANNABLE:
        return False
    if any(part.lower() in _TEST_DIRS for part in p.parts[:-1]):
        return True
    return bool(_TEST_NAME.match(p.name))


def find_test_files(project_root: str | Path) -> list[str]:
    """Every test-looking source file under the project root."""
    root = Path(project_root)
    found = []
    for p in root.rglob("*"):
        if not p.is_file() or evidence.is_excluded(p):
            continue
        if is_test_file(p):
            found.append(str(p))
    return sorted(found)


def attribute(nodes: dict[str, dict], project_root: str | Path) -> dict[str, set[str]]:
    """node id -> the test files that exercise it (may be empty for a node)."""
    root = Path(project_root)
    owners = evidence.ownership_map(nodes, project_root)
    tests = find_test_files(root)
    by_node: dict[str, set[str]] = {nid: set() for nid in nodes}

    # route 1: the test file is itself owned by a node
    for t in tests:
        for nid in owners.get(t, ()):  # ownership_map keys are owned files
            by_node.setdefault(nid, set()).add(t)

    # route 2: the test file imports a file some node owns. Feeding the test
    # files in as importers is enough -- the edge builders only require the
    # TARGET to be owned.
    files = sorted(set(owners) | set(tests))
    edges = (evidence._ts_edges(files, owners)
             + evidence._jvm_edges(files, owners)
             + evidence._dart_edges(files, owners, root)
             + evidence._py_edges(files, owners, root))
    test_set = set(tests)
    for importer, target in edges:
        if importer not in test_set:
            continue
        for nid in owners.get(target, ()):
            by_node.setdefault(nid, set()).add(importer)
    return by_node


def unattributed(nodes: dict[str, dict], project_root: str | Path,
                 statuses: tuple[str, ...] = ("verified",)) -> list[str]:
    """Nodes at one of `statuses` that no test file could be attributed to.

    Only meaningful when attribution works AT ALL in this project: if not a
    single node has an attributed test, the scanner is blind here (an unknown
    language, tests outside the tree, an unresolvable import style) and the
    answer is "unknown", not "nothing is tested". That case returns [].
    """
    by_node = attribute(nodes, project_root)
    if not any(by_node.values()):
        return []
    return sorted(nid for nid, node in nodes.items()
                  if node.get("status") in statuses and not by_node.get(nid))
