# Capability Registry & Reuse

> Part of the **Spec Growth Engine** method. This document adds the **horizontal**
> context axis that vertical slices alone lack: a way to discover and reuse
> existing capabilities across unrelated branches of the tree, instead of
> duplicating them.

## 0. Why this exists

The Spine gives **vertical** context — ancestors, neighbors, direct dependencies.
It answers *"what must I conform to?"*. It is narrow by design and therefore
**blind to siblings in other branches**.

But duplication is a **horizontal** question — *"what already exists that I could
reuse?"* — and it crosses the tree to branches the Spine never shows.

```text
Real failure it must prevent:
  Slice A needs to read PDFs -> writes a PDF reader inside its own branch.
  Slice B (unrelated) needs to read PDFs -> writes its own PDF reader.
  Neither Spine shows the other. The duplication is found only by accident.
```

Answering a horizontal question (reuse) with a vertical mechanism (Spine) is the
mistake. The fix is a second, orthogonal axis — not abandoning slices.

## 1. Principle: two orthogonal context axes

```text
VERTICAL   (Spine + neighbors)      -> "What must I conform to?"  -> Conformance
HORIZONTAL (Capability Registry)    -> "What already exists?"     -> Reuse
```

Both are required; neither replaces the other. The Registry does **not** violate
"don't read everything": it is a **query** (ask "is there a PDF->Text
capability?", get back one contract), not a bulk load. Agents use it as a
**tool**, not as default context.

## 2. What a capability is

> Canonical: [SPEC-GROWTH-ENGINE.md §3.6](SPEC-GROWTH-ENGINE.md).

A capability is a node's `provides` contract viewed as a **reusable unit**, with
a stable identity:

```yaml
capability:
  id: cap:pdf-to-text          # stable, searchable
  role: "Extract plain text from a PDF file."
  provides: "readPdf(path): Text"
  provided_by: shared.pdf-reader   # exactly ONE node should provide it
```

Rule of identity:

```text
A capability should have exactly ONE providing node.
Two nodes providing the same capability = a duplicate (see §6).
```

## 3. The Capability Registry

The Registry is a **generated, searchable view** over all `provides` contracts in
`project.index.json` — not a hand-maintained list.

```text
Query by:
  - name / id            ("pdf")
  - signature shape      (file -> text)
  - role semantics       (embedding similarity over the role text)

Returns: matching capabilities + their contract + provided_by node.
```

Engine command:

```text
spec capability find "pdf to text"
spec capability find --signature "path -> Text"
```

## 4. Capabilities belong in Shared, not in a slice

> Node classes (owned/shared/excluded): [SPEC-GROWTH-ENGINE.md §3.2](SPEC-GROWTH-ENGINE.md).

```text
Vertical slices OWN features.
The horizontal shared/platform layer OWNS capabilities.
```

A PDF reader is **not** part of a feature slice — it is a platform capability.
Promotion rule:

```text
A capability used (or needed) by more than one slice MUST be a `shared` node,
never slice-local.
```

This connects to the `owner()/shared/excluded` classifier: a `shared` node has
its own contract and is depended on like any other node. Slice-local helpers that
are genuinely private (one feature, no external format/protocol, no reuse
potential) stay inside their component as `design` — they are not capabilities.

## 5. Search-before-build gate

> Gate levels: [SPEC-GROWTH-ENGINE.md §3.9](SPEC-GROWTH-ENGINE.md).

Before a slice creates anything that **smells like a capability**, it must query
the Registry first.

```text
Heuristic "smells like a capability":
  - clean input -> output contract
  - touches an external format/resource/protocol (PDF, CSV, image, HTTP, auth, ...)
  - no slice-specific domain coupling

Gate:
  match found     -> declare depends_on <capability>   (REUSE)
  no match        -> create it as a SHARED node         (so the next slice finds it)
  truly private   -> keep as slice-local design         (must justify "no reuse potential")
```

Gate level (GOVERNANCE.md §3): **AUTO** — the engine refuses to register a new
capability-shaped node without an attached query result ("no match found"
evidence or a reuse decision). Promotion to `shared` is **SOFT** (human confirms
it is genuinely shared).

## 6. Duplicate detector (drift-validator extension)

The evidence graph already knows imports, exports, symbols. The detector finds
**mechanically** what teams otherwise find by accident.

```text
Signals (combined into a confidence score):
  - same external dependency (both import a pdf lib)
    + structurally similar exported surface (file -> text)
  - code-clone detection (AST/token similarity: type-1 exact, type-2 renamed,
    type-3 near-miss)
  - contract similarity (embedding cosine over role/provides text)

Output:
  high confidence   -> HARD warning + consolidation task (§8)
  medium confidence -> suggestion ("A.pdf-reader ~ B.pdf-reader; same capability?")
```

Engine command:

```text
spec capability duplicates        # lists probable duplicate clusters
```

## 7. Capability claim (the concurrency race)

The PDF failure was a **race**: both slices built the reader before either
committed. Detection-on-commit catches it too late; a **claim** catches it early.

```text
When a slice's plan declares a NEEDED capability that is not yet in the Registry,
it registers a CLAIM:

  claim:
    id: cap:pdf-to-text
    contract_sketch: "path -> Text"
    owner: <slice/agent>

If a second slice registers a claim matching an existing claim (by contract
similarity), the engine raises CONCURRENT-CAPABILITY-CREATION:
  -> the two coordinate: one builds the shared node, the other depends on it.
```

Claims are visible in the Registry alongside built capabilities, so a search
finds both "exists" and "being built".

```text
spec capability claim cap:pdf-to-text --contract "path -> Text"
```

## 8. Consolidation protocol (Rule of Three / extract-on-second-use)

Do **not** speculatively pre-build a utility library (anti-agile). Build local
first; consolidate on the **second** occurrence.

```text
1st occurrence -> build local (you don't yet know it will be shared)
2nd occurrence -> detector fires -> consolidate:

  a. Human/Planner confirms A and B are the SAME capability.
     (Handle "similar but not same": e.g. one needs OCR, one does not.
      If intents differ -> mark as distinct/related; optionally factor a
      common core capability that both depend on.)
  b. Create/choose a shared node S with the union contract.
  c. Migrate A's and B's consumers to depend_on S.
  d. Remove the duplicate implementations.

Steps b–c are a contract introduction + consumer migration ->
follow GOVERNANCE.md §7 (change-set or deprecate-then-migrate) and the §3/§5 gates.
```

You need no perfect up-front foresight — only **detection + consolidation on the
second occurrence**. This is fully compatible with agile slice growth.

## 9. Honest limits

```text
- Perfect dedup is impossible: "similar but not the same" intents are real
  (OCR vs no-OCR). Semantic similarity is fuzzy.
- Realistic goal: SURFACE probable duplicates for judgment, and make REUSE the
  path of least resistance (existing capabilities easy to find + easy to
  depend_on). Reduce duplication drastically; do not eliminate it by decree.
```

## 10. Engine support (what to implement)

```text
1. Registry view        searchable index over all `provides` (generated)
2. Claim registry       intent-level capability claims + concurrency conflicts
3. Search-before-build   AUTO gate on capability-shaped node creation
4. Duplicate detector    clone + dependency + contract-similarity signals
5. Consolidation task    auto-opened on high-confidence duplicates
```

### Implementation status (cockpit/engine/capability.py)

```text
[done] Registry view        build_registry(nodes) -> one capability per provider
[done] Search               find(registry, query, signature) -> ranked matches
[done] Search-before-build   smells_like_capability(node) heuristic; the cockpit
                             Draft step auto-warns on resembling capabilities and
                             the Registry > Find Capability command queries first
[done] Duplicate detector    duplicates(nodes, root): contract-text + signature-
                             shape + shared-external-dependency signals; skips
                             ownership-line (realization) and already-depends_on
                             pairs; high/medium confidence clusters
[done] Claim registry        add_claim/list_claims (CAPABILITIES.claims.json):
                             concurrent-capability-creation conflict on similar
                             open claims or already-built capabilities
[done] Similarity            lexical (token Jaccard) by default; optional
                             SEMANTIC layer via the planner's model (agent/semantic.py),
                             dependency-injected into find()/duplicates(). The
                             engine stays deterministic; lexical is the cheap
                             prefilter, the LLM re-ranks search hits (blended)
                             and confirms duplicate pairs ("same capability?",
                             demoting similar-but-not-same). Any AI failure or
                             missing key falls back to lexical -- never breaks
                             the gate. Toggle: cockpit.json semantic_match.
[todo] Consolidation task    auto-open a tracked task on high-confidence dupes
                             (today: reported for human judgement, not tracked)
[todo] AST/token clone       type-1/2/3 code-clone signal (today: import-surface
                             + contract similarity only)
```

## 11. Relationship to the rest of the engine

```text
- Orthogonal to the Spine: Spine = conformance (vertical), Registry = reuse
  (horizontal). Adding the Registry does not widen the Spine.
- owner()/shared classifier: capabilities are `shared` nodes with contracts.
- GOVERNANCE.md: search-before-build = AUTO gate; promotion to shared = SOFT;
  consolidation = §7 contract-change protocol; gate levels = §3, applied in §5.
- LIFECYCLE.md: distinct from frontier stubs — a frontier stub is "not built
  yet on a later slice"; a capability is "built once, reused everywhere".
```

## 12. Summary

```text
The Spine keeps you correct. The Registry keeps you from repeating yourself.
Capabilities live in the shared layer, have one provider, and are found by query.
Search before you build; detect duplicates mechanically; consolidate on the
second occurrence. Two axes, each for its own question.
```
