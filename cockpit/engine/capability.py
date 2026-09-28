"""Capability Registry & reuse (horizontal axis).

The Spine gives vertical context ("what must I conform to?"). The Registry gives
the orthogonal horizontal answer ("what already exists that I could reuse?") so
the same capability is not implemented twice in unrelated branches.

This module is deterministic and authors no intent. It is a *generated view* over
the specs' `provides` contracts plus the code evidence graph:

  build_registry(nodes)               -> list of capabilities (one per provider)
  find(registry, query, signature)    -> ranked matches (search-before-build)
  smells_like_capability(node)        -> (bool, reasons) AUTO-gate heuristic
  duplicates(nodes, project_root)     -> probable duplicate clusters (detector)
  add_claim / list_claims(root, ...)  -> intent-level claims + concurrency race

Similarity is lexical (token Jaccard) in this MVP -- enough to SURFACE probable
duplicates for human judgement and make reuse the path of least resistance.
Semantic/embedding similarity can be layered on later via the planner.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import evidence, graph

CLAIMS_FILE = "CAPABILITIES.claims.json"

# keywords that mark a clean external format/resource/protocol boundary -- the
# strongest "this is a reusable capability, not slice-private glue" signal.
_EXTERNAL_KEYWORDS = {
    "pdf", "csv", "tsv", "json", "yaml", "xml", "html", "markdown", "image",
    "png", "jpeg", "jpg", "svg", "excel", "xlsx", "zip", "tar", "gzip",
    "http", "https", "rest", "grpc", "graphql", "websocket", "tcp", "udp",
    "smtp", "email", "mail", "imap", "auth", "oauth", "jwt", "token", "ldap",
    "s3", "sql", "sqlite", "postgres", "mysql", "redis", "mongo", "kafka",
    "encrypt", "decrypt", "hash", "compress", "parse", "serialize", "render",
    "ocr", "embedding", "translate", "transcode", "thumbnail", "barcode", "qr",
}

_STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "and", "or", "from", "into", "with",
    "on", "in", "by", "as", "is", "be", "returns", "return", "given", "this",
    "that", "it", "its", "via", "using", "use", "uses", "get", "set",
}


# ---------------------------------------------------------------- tokenizing --
def _tokens(text: str) -> set[str]:
    raw = re.split(r"[^a-zA-Z0-9]+", (text or "").lower())
    out: set[str] = set()
    for t in raw:
        if len(t) < 2 or t in _STOPWORDS:
            continue
        out.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)  # crude singular
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _signature_tokens(provides: str) -> set[str]:
    """Tokens describing a provides signature's *shape* (args + return)."""
    if "->" in provides:
        left, _, right = provides.partition("->")
        return _tokens(left) | _tokens(right)
    m = re.search(r"\(([^)]*)\)\s*:?\s*(.*)$", provides)
    if m:
        return _tokens(m.group(1)) | _tokens(m.group(2))
    return _tokens(provides)


# ----------------------------------------------------------------- registry ---
def _contract(node: dict) -> dict:
    c = node.get("contract")
    return c if isinstance(c, dict) else {}


def _provides_list(node: dict) -> list[str]:
    p = _contract(node).get("provides")
    if isinstance(p, list):
        return [s for s in p if isinstance(s, str)]
    if isinstance(p, str):
        return [p]
    return []


def _cap_id(node: dict, nid: str) -> str:
    cap = node.get("capability")
    if isinstance(cap, dict) and isinstance(cap.get("id"), str):
        return cap["id"]
    return f"cap:{nid}"


def build_registry(nodes: dict[str, dict]) -> list[dict]:
    """A searchable view: every node with a `provides` contract is a capability.

    Returns one entry per providing node:
      {id, node, role, provides:[...], kind, status, shared}
    """
    out: list[dict] = []
    for nid, node in nodes.items():
        provides = _provides_list(node)
        if not provides:
            continue
        out.append({
            "id": _cap_id(node, nid),
            "node": nid,
            "role": _contract(node).get("purpose", "") or node.get("_body", "")[:160],
            "provides": provides,
            "kind": node.get("kind", ""),
            "status": node.get("status", ""),
            "shared": bool(node.get("shared")) or "shared" in nid.split("."),
        })
    return out


def _cap_text(cap: dict) -> str:
    return " ".join([cap["id"], cap.get("role", ""), *cap.get("provides", [])])


# ------------------------------------------------------------------- search ---
def find(
    registry: list[dict],
    query: str,
    signature: str | None = None,
    limit: int = 10,
    reranker=None,
    prefilter: int = 20,
) -> list[dict]:
    """Rank capabilities by similarity to `query` (and optional signature).

    Lexical (token Jaccard) by default. If `reranker` is given (an injected
    callable from agent.semantic, GLM-5.2), the top `prefilter` lexical
    candidates are re-scored semantically and the two scores are blended -- the
    engine stays deterministic; the AI is the injected dependency.
    `reranker(query, candidates) -> {node_id: score in [0,1]}`.
    Returns matches [{capability, score, lexical[, semantic]}] sorted desc."""
    q_tokens = _tokens(query)
    s_tokens = _signature_tokens(signature) if signature else set()
    scored: list[dict] = []
    for cap in registry:
        text_score = _jaccard(q_tokens, _tokens(_cap_text(cap)))
        if s_tokens:
            sig_score = max(
                (_jaccard(s_tokens, _signature_tokens(p)) for p in cap["provides"]),
                default=0.0,
            )
            score = 0.6 * text_score + 0.4 * sig_score
        else:
            score = text_score
        if score > 0:
            scored.append({"capability": cap, "score": round(score, 3), "lexical": round(score, 3)})
    scored.sort(key=lambda x: x["score"], reverse=True)

    if reranker is not None and scored:
        candidates = [s["capability"] for s in scored[:prefilter]]
        try:
            sem = reranker(query, candidates) or {}
        except Exception:
            sem = {}  # any AI failure -> fall back to lexical, never crash the gate
        for s in scored:
            node = s["capability"]["node"]
            if node in sem:
                s["semantic"] = round(float(sem[node]), 3)
                s["score"] = round(0.5 * s["lexical"] + 0.5 * s["semantic"], 3)
        scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


# ------------------------------------------------------- search-before-build --
def smells_like_capability(node: dict) -> tuple[bool, list[str]]:
    """AUTO-gate heuristic: does this node look like a reusable capability?

    Signals: a clean input->output provides surface that touches an external
    format/resource/protocol, with no obvious slice-specific domain coupling.
    Returns (smells, reasons)."""
    provides = _provides_list(node)
    if not provides:
        return False, []
    reasons: list[str] = []
    has_surface = any(("(" in p and ")" in p) or "->" in p for p in provides)
    if has_surface:
        reasons.append("clean input->output surface")
    text_tokens = _tokens(" ".join(provides) + " " + _contract(node).get("purpose", ""))
    hits = sorted(text_tokens & _EXTERNAL_KEYWORDS)
    if hits:
        reasons.append("touches external format/resource: " + ", ".join(hits))
    smells = has_surface and bool(hits)
    return smells, reasons


# -------------------------------------------------------- duplicate detector --
def duplicates(
    nodes: dict[str, dict],
    project_root: str | Path,
    high: float = 0.6,
    medium: float = 0.4,
    judge=None,
) -> list[dict]:
    """Surface probable duplicate capabilities across unrelated branches.

    Combines three lexical/structural signals into a confidence score:
      - contract similarity (token Jaccard over role + provides)
      - signature-shape similarity (args + return)
      - shared external dependency (both import the same third-party lib)

    Skips pairs on the same ownership line (realization, not duplication) and
    pairs already connected by depends_on (one already reuses the other).

    If `judge` is given (injected from agent.semantic, GLM-5.2), the surviving
    candidate pairs are confirmed semantically and the LLM verdict adjusts the
    confidence -- handling "similar but not the same" (e.g. OCR vs no-OCR).
    `judge(pairs) -> {(a,b): {same: bool, confidence: float, reason: str}}`.
    Returns [{a, b, score, confidence, reasons[, semantic]}] sorted by score."""
    registry = build_registry(nodes)
    ext = evidence.external_dependencies(nodes, project_root)
    dep = graph.dependency_dag(nodes)
    by_node = {c["node"]: c for c in registry}
    out: list[dict] = []
    for i in range(len(registry)):
        for j in range(i + 1, len(registry)):
            a, b = registry[i], registry[j]
            na, nb = a["node"], b["node"]
            # same ownership line -> realization, not duplication
            if na in graph.spine(nodes, nb) or nb in graph.spine(nodes, na):
                continue
            # already connected -> one reuses the other
            if dep.has_edge(na, nb) or dep.has_edge(nb, na):
                continue
            contract_sim = _jaccard(_tokens(_cap_text(a)), _tokens(_cap_text(b)))
            sig_sim = max(
                (_jaccard(_signature_tokens(pa), _signature_tokens(pb))
                 for pa in a["provides"] for pb in b["provides"]),
                default=0.0,
            )
            shared_libs = ext.get(na, set()) & ext.get(nb, set())
            shared = 1.0 if shared_libs else 0.0
            score = 0.55 * contract_sim + 0.25 * sig_sim + 0.20 * shared
            if score < medium:
                continue
            reasons = [f"contract similarity {contract_sim:.2f}"]
            if sig_sim:
                reasons.append(f"signature similarity {sig_sim:.2f}")
            if shared_libs:
                reasons.append("shared external dependency: " + ", ".join(sorted(shared_libs)))
            out.append({
                "a": na, "b": nb, "score": round(score, 3),
                "confidence": "high" if score >= high else "medium",
                "reasons": reasons,
            })

    if judge is not None and out:
        pairs = [(d["a"], d["b"], by_node[d["a"]], by_node[d["b"]]) for d in out]
        try:
            verdicts = judge(pairs) or {}
        except Exception:
            verdicts = {}  # AI failure -> keep the lexical verdict
        for d in out:
            v = verdicts.get((d["a"], d["b"])) or verdicts.get((d["b"], d["a"]))
            if not v:
                continue
            d["semantic"] = {"same": bool(v.get("same")), "confidence": v.get("confidence")}
            if v.get("reason"):
                d["reasons"].append("LLM: " + str(v["reason"]))
            if v.get("same") is False:
                d["confidence"] = "low"  # similar but not the same -> demote
            elif v.get("same") is True and isinstance(v.get("confidence"), (int, float)):
                d["confidence"] = "high" if v["confidence"] >= high else d["confidence"]

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# ------------------------------------------------------------------- claims ---
def _claims_path(root: str | Path) -> Path:
    return Path(root) / CLAIMS_FILE


def list_claims(root: str | Path) -> list[dict]:
    path = _claims_path(root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    claims = data.get("claims") if isinstance(data, dict) else None
    return claims if isinstance(claims, list) else []


def add_claim(
    root: str | Path,
    cap_id: str,
    contract_sketch: str,
    owner: str,
    nodes: dict[str, dict] | None = None,
    threshold: float = 0.5,
) -> tuple[dict, list[dict]]:
    """Register an intent-level capability claim and detect concurrency conflicts.

    A conflict is another open claim (or an existing built capability) whose
    contract is similar enough -> CONCURRENT-CAPABILITY-CREATION: the two should
    coordinate (one builds the shared node, the other depends on it).
    Returns (claim, conflicts)."""
    claim = {
        "id": cap_id,
        "contract_sketch": contract_sketch,
        "owner": owner,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    sketch_tokens = _tokens(cap_id + " " + contract_sketch)
    conflicts: list[dict] = []
    for other in list_claims(root):
        sim = _jaccard(sketch_tokens, _tokens(other["id"] + " " + other.get("contract_sketch", "")))
        if other["id"] == cap_id or sim >= threshold:
            conflicts.append({"kind": "claim", "with": other, "similarity": round(sim, 3)})
    if nodes is not None:
        for cap in build_registry(nodes):
            sim = _jaccard(sketch_tokens, _tokens(_cap_text(cap)))
            if sim >= threshold:
                conflicts.append({"kind": "built", "with": cap, "similarity": round(sim, 3)})

    existing = list_claims(root)
    existing.append(claim)
    _claims_path(root).write_text(
        json.dumps({"claims": existing}, indent=2), encoding="utf-8"
    )
    return claim, conflicts
