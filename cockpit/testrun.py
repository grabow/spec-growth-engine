"""Test runner: execute a node's project tests to produce the evidence that
acceptance criteria need (the `implemented -> verified` gate).

Picks the test command from the build manifest at the node's build root (reusing
the same build-root detection as the coder), runs it there, and streams output.
This is deterministic (no AI): it only selects and launches the project's own
test command.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from agent.coder import build_root_for_node
from engine import attribution, lifecycle


def test_command(build_root: str | Path) -> list[str] | None:
    """The project's test command for the manifest present in `build_root`."""
    p = Path(build_root)
    if (p / "pom.xml").is_file():
        return ["mvn", "-q", "test"]
    if any((p / m).is_file() for m in
           ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")):
        gradlew = p / "gradlew"
        return [str(gradlew) if gradlew.is_file() else "gradle", "test"]
    if (p / "pyproject.toml").is_file() or (p / "setup.py").is_file():
        return ["uv", "run", "pytest"]
    if (p / "Cargo.toml").is_file():
        return ["cargo", "test"]
    if (p / "pubspec.yaml").is_file():
        text = (p / "pubspec.yaml").read_text(encoding="utf-8", errors="ignore")
        return ["flutter", "test"] if "flutter" in text else ["dart", "test"]
    if (p / "package.json").is_file():
        return ["npm", "test"]
    return None


def covered(nodes: dict[str, dict], project_root: str, build_root: str | Path) -> list[str]:
    """The nodes a run at `build_root` covers: every node whose build root it is."""
    return sorted(k for k, nd in nodes.items()
                  if str(build_root_for_node(nd, project_root)) == str(build_root))


def record(nodes: dict[str, dict], project_root: str, build_root: str | Path,
           passed: bool, command: str, started: str) -> list[str]:
    """Record a finished run as test evidence for every node it covers, with the
    test files attributed to each (engine.attribution). Shared by the cockpit's
    Run Tests and `cli.py test`. Returns the covered node ids."""
    ids = covered(nodes, project_root, build_root)
    if ids:
        try:
            tests_by_node = attribution.attribute(nodes, project_root)
        except Exception:  # attribution is a refinement, never a blocker
            tests_by_node = None
        lifecycle.record_evidence(project_root, ids, "pass" if passed else "fail", command,
                                  str(build_root), tests_by_node=tests_by_node, at=started)
    return ids


def now() -> str:
    """The evidence timestamp format (local time, seconds)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def build_roots(nodes: dict[str, dict], project_root: str) -> list[Path]:
    """Every distinct build root with a test command -- what `cli.py test` runs."""
    roots = {build_root_for_node(nd, project_root) for nd in nodes.values()}
    return sorted(r for r in roots if test_command(r) is not None)


def run_tests(node: dict, project_root: str) -> tuple[subprocess.Popen, Path, list[str]]:
    """Run the project's tests at the node's build root.

    Returns (streamable Popen, build_root, command). Raises ValueError if no
    recognized build manifest is found.
    """
    root = build_root_for_node(node, project_root)
    cmd = test_command(root)
    if cmd is None:
        raise ValueError(f"no recognized build manifest in {root}; cannot run tests")
    proc = subprocess.Popen(
        cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return proc, root, cmd
