"""Semantic capability matching (role: AI judge) over GLM-5.2.

The engine's capability registry is deterministic and lexical (token Jaccard).
This module provides the OPTIONAL semantic layer as *injected* callables:

  make_reranker(model)  -> reranker(query, candidates) -> {node_id: score}
  make_judge(model)     -> judge(pairs) -> {(a, b): {same, confidence, reason}}

Both are passed into engine.capability.find / .duplicates. Keeping the AI here
(not in the engine) preserves the boundary "engine authors/asks nothing". If no
API key is configured, the factories return None and the engine falls back to
pure lexical matching -- the feature degrades, it never breaks the gate.

Design: retrieve-then-rerank. The engine does the cheap lexical prefilter; only
the top candidates are sent to the LLM, so token cost stays bounded.
"""
from __future__ import annotations

from .llm import _call_tool, _client

_RANK_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_scores",
        "description": "Score how well each capability satisfies the query.",
        "parameters": {
            "type": "object",
            "required": ["scores"],
            "properties": {
                "scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["node", "score"],
                        "properties": {
                            "node": {"type": "string"},
                            "score": {
                                "type": "number",
                                "description": "Semantic match 0.0 (unrelated) .. 1.0 (exact same capability).",
                            },
                        },
                    },
                }
            },
        },
    },
}

_JUDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_verdicts",
        "description": "Judge whether each pair of capabilities is the SAME reusable capability.",
        "parameters": {
            "type": "object",
            "required": ["verdicts"],
            "properties": {
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["a", "b", "same", "confidence"],
                        "properties": {
                            "a": {"type": "string"},
                            "b": {"type": "string"},
                            "same": {
                                "type": "boolean",
                                "description": "True only if one shared node could replace both.",
                            },
                            "confidence": {"type": "number", "description": "0.0 .. 1.0"},
                            "reason": {"type": "string", "description": "One short sentence."},
                        },
                    },
                }
            },
        },
    },
}


def _cap_line(cap: dict) -> str:
    return f"{cap['node']}: role={cap.get('role', '')!r} provides={cap.get('provides', [])}"


def make_reranker(model: str | None = None):
    """Return reranker(query, candidates)->{node: score}, or None if no LLM."""
    try:
        client = _client()
    except RuntimeError:
        return None

    def reranker(query: str, candidates: list[dict]) -> dict[str, float]:
        listing = "\n".join(f"- {_cap_line(c)}" for c in candidates)
        prompt = (
            "You match a needed capability against existing ones for REUSE. "
            "Score each by how well it already provides what the query needs "
            "(1.0 = same capability, reuse it; 0.0 = unrelated). Judge meaning, "
            "not wording (e.g. 'read PDF' == 'extract text from PDF file').\n\n"
            f"QUERY: {query}\n\nCAPABILITIES:\n{listing}\n\nCall emit_scores."
        )
        data, _ = _call_tool(client, _RANK_TOOL, prompt, model=model)
        out: dict[str, float] = {}
        for row in data.get("scores", []):
            node = row.get("node")
            if isinstance(node, str):
                try:
                    out[node] = max(0.0, min(1.0, float(row.get("score", 0))))
                except (TypeError, ValueError):
                    pass
        return out

    return reranker


def make_judge(model: str | None = None):
    """Return judge(pairs)->{(a,b): verdict}, or None if no LLM.

    `pairs` is a list of (a_id, b_id, a_cap, b_cap)."""
    try:
        client = _client()
    except RuntimeError:
        return None

    def judge(pairs: list[tuple]) -> dict[tuple[str, str], dict]:
        listing = "\n".join(
            f"- pair ({a},{b}):\n    {a} -> {_cap_line(ca)}\n    {b} -> {_cap_line(cb)}"
            for a, b, ca, cb in pairs
        )
        prompt = (
            "For each pair, decide if they are the SAME reusable capability -- i.e. "
            "one shared node could replace both. Be strict about 'similar but not "
            "the same' (e.g. PDF-with-OCR vs PDF-without-OCR are NOT the same; a "
            "common core may exist but the surfaces differ). Give a short reason.\n\n"
            f"PAIRS:\n{listing}\n\nCall emit_verdicts."
        )
        data, _ = _call_tool(client, _JUDGE_TOOL, prompt, model=model)
        out: dict[tuple[str, str], dict] = {}
        for v in data.get("verdicts", []):
            a, b = v.get("a"), v.get("b")
            if isinstance(a, str) and isinstance(b, str):
                out[(a, b)] = {
                    "same": bool(v.get("same")),
                    "confidence": v.get("confidence"),
                    "reason": v.get("reason", ""),
                }
        return out

    return judge
