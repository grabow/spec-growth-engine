"""Coding agent (role C): implement a node within its context bundle.

This shells out to a coding-agent CLI (default: `codex exec`). Override with the
SGE_CODER_CMD environment variable, e.g. SGE_CODER_CMD="claude -p".
The caller streams stdout (see app.py) so the UI stays responsive.

Build-root detection (Model B): the agent runs in the nearest ancestor directory
that holds a build manifest (pom.xml / pyproject.toml / Cargo.toml / package.json
/ pubspec.yaml / Gradle), so `mvn` / `uv` / `cargo` / `npm` / `flutter` work even
when the target node is a sub-package. For loose scripts (no manifest) it runs in
the node's own directory.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

DEFAULT_CMD = os.environ.get("SGE_CODER_CMD", "codex exec")

# Build manifests that mark a project/build root, per ecosystem.
BUILD_MANIFESTS = {
    "pom.xml",                                                   # Maven (Java)
    "build.gradle", "build.gradle.kts",                         # Gradle (Java/Kotlin)
    "settings.gradle", "settings.gradle.kts",
    "pyproject.toml", "setup.py",                              # Python (uv/pip)
    "Cargo.toml",                                              # Rust
    "pubspec.yaml",                                            # Dart / Flutter
    "package.json",                                           # JS / Node / React
}

_TASK = (
    "\n\n# TASK\n"
    "Implement the target node ONLY within the context above (its `code` globs). "
    "Build the active path for real (no fakes on it). You are running in the build "
    "root, so use the project's tool (mvn / uv / cargo / gradle / npm / flutter) to "
    "build and test. Update the node's SPEC.md in the SAME commit (contract / "
    "depends_on). Do not touch files outside the target node's scope.\n"
    "MEMORY: if you discover durable operational knowledge while building or testing "
    "(tool paths, setup steps, error workarounds), append a brief note to `AGENT-NOTES.md` "
    "in the build root so future runs are faster. AGENT-NOTES.md is a SPEED-UP ONLY -- not "
    "a spec, not a contract; never put intent there. Durable toolchain decisions "
    "(language, build tool) belong in ARCHITECTURE.md instead."
)


def find_build_root(start_dir: str | Path, project_root: str | Path | None) -> Path:
    """Nearest ancestor of `start_dir` (up to and incl. `project_root`) that holds a
    build manifest. Falls back to `start_dir` itself if none is found (loose scripts).
    """
    start_dir = Path(start_dir).resolve()
    chain = [start_dir, *start_dir.parents]
    if project_root is not None:
        root = Path(project_root).resolve()
        bounded = chain[: chain.index(root) + 1] if root in chain else [start_dir]
    else:
        bounded = [start_dir]
    for d in bounded:  # closest to the start first
        if any((d / m).is_file() for m in BUILD_MANIFESTS):
            return d
    return start_dir


def build_root_for_node(node: dict, project_root: str) -> Path:
    """The build root for a node, derived from where its CODE lives (not its spec).

    Code globs are project-root-relative, so the spec can sit anywhere; we start the
    build-root search at the directory of the node's first owned file, falling back
    to the node's spec dir / project root when it owns no code yet.
    """
    from engine import evidence  # local import: agent -> engine (no cycle)

    files = evidence.resolve_node_files(node, project_root)
    start = Path(files[0]).parent if files else Path(node.get("_dir", project_root))
    return find_build_root(start, project_root)


_FOLLOWUP = (
    "\n\n# FOLLOW-UP\n"
    "Above is the original context, YOUR PREVIOUS OUTPUT, and a new message from the "
    "human. `codex exec` is single-shot, so this is a fresh run with the prior "
    "conversation replayed for context. Address the new message. Change code only if "
    "it requires it (same rules as the original task); if it is only a question, "
    "answer it and do NOT modify files."
)


def run_prompt(
    prompt: str, cwd: str | None = None, command: str | list[str] | None = None,
    env: dict | None = None,
) -> subprocess.Popen:
    """Low-level: launch the coding-agent CLI with `prompt` at `cwd`; streamable Popen.

    `command` is a string (split like a shell would) or an argv list; `env`
    replaces the environment (agent/codex_cli.py puts a role's key there, and
    only there). stdin is /dev/null: `codex exec` WAITS on an open stdin, and
    started from a pipe it hung until killed."""
    cmd = list(command) if isinstance(command, (list, tuple)) \
        else shlex.split(command or DEFAULT_CMD)
    return subprocess.Popen(
        cmd + [prompt],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def implement(
    bundle: str,
    node_id: str,
    node: dict | None = None,
    project_root: str | None = None,
    command: str | list[str] | None = None,
    env: dict | None = None,
) -> subprocess.Popen:
    """Launch the coding agent in the node's build root; returns a streamable Popen."""
    cwd = str(build_root_for_node(node, project_root)) if (node and project_root) else None
    prompt = f"{bundle}\n\n(Target node: {node_id}; working dir: {cwd}){_TASK}"
    return run_prompt(prompt, cwd, command, env)


def followup_prompt(bundle: str, node_id: str, prior_output: str, message: str) -> str:
    """Compose a continuation prompt: original context + prior output + new message.
    `codex exec` has no session, so the conversation is replayed as one prompt."""
    return (
        f"{bundle}\n\n(Target node: {node_id})\n\n"
        f"# YOUR PREVIOUS OUTPUT\n{prior_output or '(none yet)'}\n\n"
        f"# NEW MESSAGE FROM HUMAN\n{message}{_FOLLOWUP}"
    )
