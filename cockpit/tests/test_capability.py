"""Capability Registry: registry view, search, smell gate, duplicate detector,
and concurrency claims."""
from engine import capability, parser
from tests.conftest import write_spec


def _pdf_project(tmp_path):
    """Two unrelated branches that each build a PDF->text reader (a duplicate)."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n- Python\n", encoding="utf-8")
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["invoices", "reports"]}, code=[])
    # branch A
    write_spec(tmp_path / "invoices", id="invoices", parent="app", kind="component",
               contract={"purpose": "Read invoice PDFs.",
                         "provides": ["readPdf(path): Text"]},
               code=["invoices/*.py"])
    (tmp_path / "invoices" / "pdf.py").write_text(
        "import pdfplumber\ndef readPdf(path):\n    return pdfplumber.open(path)\n",
        encoding="utf-8")
    # branch B (the accidental duplicate)
    write_spec(tmp_path / "reports", id="reports", parent="app", kind="component",
               contract={"purpose": "Extract text from PDF report files.",
                         "provides": ["extractPdfText(file): Text"]},
               code=["reports/*.py"])
    (tmp_path / "reports" / "extract.py").write_text(
        "import pdfplumber\ndef extractPdfText(file):\n    return pdfplumber.open(file)\n",
        encoding="utf-8")
    return tmp_path


def test_registry_lists_one_capability_per_provider(tmp_path):
    root = _pdf_project(tmp_path)
    nodes = parser.load_nodes(root)
    reg = capability.build_registry(nodes)
    ids = {c["node"] for c in reg}
    assert ids == {"invoices", "reports"}          # app has no provides -> not a capability
    inv = next(c for c in reg if c["node"] == "invoices")
    assert inv["id"] == "cap:invoices"
    assert inv["provides"] == ["readPdf(path): Text"]


def test_find_ranks_relevant_capability_first(tmp_path):
    root = _pdf_project(tmp_path)
    reg = capability.build_registry(parser.load_nodes(root))
    hits = capability.find(reg, "pdf to text")
    assert hits, "expected at least one match"
    assert {h["capability"]["node"] for h in hits} == {"invoices", "reports"}
    assert all(h["score"] > 0 for h in hits)


def test_find_with_signature_shape(tmp_path):
    root = _pdf_project(tmp_path)
    reg = capability.build_registry(parser.load_nodes(root))
    hits = capability.find(reg, "pdf", signature="path -> Text")
    assert hits and hits[0]["score"] > 0


def test_smells_like_capability_external_surface():
    node = {"contract": {"purpose": "Extract text from a PDF.",
                         "provides": ["readPdf(path): Text"]}}
    smells, reasons = capability.smells_like_capability(node)
    assert smells is True
    assert any("external" in r for r in reasons)


def test_does_not_smell_when_domain_local():
    node = {"contract": {"purpose": "Compute invoice total.",
                         "provides": ["total(): Money"]}}
    smells, _ = capability.smells_like_capability(node)
    assert smells is False                          # no external format/resource


def test_duplicate_detector_flags_two_pdf_readers(tmp_path):
    root = _pdf_project(tmp_path)
    nodes = parser.load_nodes(root)
    dups = capability.duplicates(nodes, str(root))
    assert dups, "expected a duplicate cluster"
    pair = {dups[0]["a"], dups[0]["b"]}
    assert pair == {"invoices", "reports"}
    assert any("shared external dependency" in r for r in dups[0]["reasons"])
    assert any("pdfplumber" in r for r in dups[0]["reasons"])


def test_realization_pair_not_flagged_as_duplicate(tmp_path):
    # parent + child with similar contracts -> ownership line, NOT a duplicate
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["pdf"]}, code=[])
    write_spec(tmp_path / "pdf", id="pdf", parent="app", kind="container",
               contract={"purpose": "Read PDFs.", "provides": ["readPdf(p): Text"]},
               design={"children": ["pdf.core"]}, code=[])
    write_spec(tmp_path / "pdf" / "core", id="pdf.core", parent="pdf", kind="component",
               contract={"purpose": "Read PDFs.", "provides": ["readPdf(p): Text"]},
               code=[])
    nodes = parser.load_nodes(tmp_path)
    dups = capability.duplicates(nodes, str(tmp_path))
    assert all({d["a"], d["b"]} != {"pdf", "pdf.core"} for d in dups)


def test_declared_dependency_pair_not_flagged(tmp_path):
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["a", "b"]}, code=[])
    write_spec(tmp_path / "a", id="a", parent="app", kind="component",
               contract={"purpose": "Read PDFs.", "provides": ["readPdf(p): Text"]},
               depends_on=["b"], code=[])
    write_spec(tmp_path / "b", id="b", parent="app", kind="component",
               contract={"purpose": "Read PDFs.", "provides": ["readPdf(p): Text"]},
               code=[])
    nodes = parser.load_nodes(tmp_path)
    dups = capability.duplicates(nodes, str(tmp_path))
    assert all({d["a"], d["b"]} != {"a", "b"} for d in dups)  # a already depends_on b


def test_find_reranker_blends_and_reorders(tmp_path):
    # injected semantic scorer prefers 'reports' although lexical favours neither
    root = _pdf_project(tmp_path)
    reg = capability.build_registry(parser.load_nodes(root))

    def fake_reranker(query, candidates):
        return {"reports": 1.0, "invoices": 0.0}

    hits = capability.find(reg, "pdf to text", reranker=fake_reranker)
    assert hits[0]["capability"]["node"] == "reports"
    assert "semantic" in hits[0] and hits[0]["semantic"] == 1.0
    # blended score = 0.5*lexical + 0.5*semantic
    assert hits[0]["score"] == round(0.5 * hits[0]["lexical"] + 0.5, 3)


def test_find_reranker_failure_falls_back_to_lexical(tmp_path):
    root = _pdf_project(tmp_path)
    reg = capability.build_registry(parser.load_nodes(root))

    def boom(query, candidates):
        raise RuntimeError("LLM down")

    hits = capability.find(reg, "pdf to text", reranker=boom)
    assert hits and all("semantic" not in h for h in hits)  # graceful fallback


def test_duplicates_judge_demotes_not_same(tmp_path):
    root = _pdf_project(tmp_path)
    nodes = parser.load_nodes(root)

    def judge(pairs):
        # the LLM decides these are similar but NOT the same capability
        return {(a, b): {"same": False, "confidence": 0.9, "reason": "one needs OCR"}
                for a, b, _ca, _cb in pairs}

    dups = capability.duplicates(nodes, str(root), judge=judge)
    assert dups and dups[0]["confidence"] == "low"
    assert dups[0]["semantic"]["same"] is False
    assert any("LLM:" in r for r in dups[0]["reasons"])


def test_claim_detects_concurrent_creation(tmp_path):
    c1, conflicts1 = capability.add_claim(
        tmp_path, "cap:pdf-to-text", "path -> Text", owner="sliceA")
    assert conflicts1 == []                         # first claim: no conflict
    c2, conflicts2 = capability.add_claim(
        tmp_path, "cap:pdf-to-text", "file -> Text", owner="sliceB")
    assert conflicts2, "second matching claim must raise a conflict"
    assert conflicts2[0]["with"]["owner"] == "sliceA"
    assert len(capability.list_claims(tmp_path)) == 2


# ---- the semantic layer against the real model's failure modes (stub client) ---

def test_a_cut_off_rerank_degrades_to_lexical(tmp_path, monkeypatch):
    """The reranker reports the cut-off (RuntimeError); the registry, as for any
    AI failure, keeps the lexical ranking."""
    from agent import semantic
    from tests.test_assist import _client_answering, _Resp
    monkeypatch.setattr(semantic, "_client", lambda: _client_answering(
        _Resp('{"scores": [{"node": "rep', "length")))
    reg = capability.build_registry(parser.load_nodes(_pdf_project(tmp_path)))
    hits = capability.find(reg, "pdf to text", reranker=semantic.make_reranker())
    assert hits and all("semantic" not in h for h in hits)


def test_a_provider_error_in_the_judge_keeps_the_lexical_verdict(tmp_path, monkeypatch):
    from agent import semantic
    from tests.test_assist import _refusing
    monkeypatch.setattr(semantic, "_client", _refusing)
    root = _pdf_project(tmp_path)
    dups = capability.duplicates(parser.load_nodes(root), root, judge=semantic.make_judge())
    assert dups and all("semantic" not in d for d in dups)
