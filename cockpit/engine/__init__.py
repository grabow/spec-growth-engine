"""Spec Growth Engine - deterministic core.

This package authors NO intent. It only parses SPEC.md files, builds the
ownership tree + dependency DAG, assembles scoped context bundles, and validates
structure. Drafting (intent -> spec) lives in the `agent` package; coding lives
in the coding agent. Keep this boundary strict (engine = role E in the paper).
"""

__all__ = [
    "parser", "graph", "context", "validate", "evidence", "drift", "nodes",
    "capability", "lifecycle", "index",
]
