"""Per-node test attribution (engine.attribution)."""
from engine import attribution, lifecycle


def _py_project(tmp_path):
    """Two components under one build root; only `store` has a test."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    src = tmp_path / "src"
    (src / "store").mkdir(parents=True)
    (src / "ingest").mkdir(parents=True)
    (src / "store" / "store.py").write_text("def read():\n    return 1\n", encoding="utf-8")
    (src / "ingest" / "ingest.py").write_text("def run():\n    return 2\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_store.py").write_text(
        "from src.store.store import read\n\n\ndef test_read():\n    assert read() == 1\n",
        encoding="utf-8")
    nodes = {
        "app": {"id": "app", "kind": "system", "parent": None, "code": [], "status": "specd"},
        "app.store": {"id": "app.store", "kind": "component", "parent": "app",
                      "code": ["src/store/**"], "status": "verified"},
        "app.ingest": {"id": "app.ingest", "kind": "component", "parent": "app",
                       "code": ["src/ingest/**"], "status": "verified"},
    }
    return nodes, str(tmp_path)


# ---- recognising tests ------------------------------------------------------

def test_recognises_test_files_by_directory_and_by_name():
    for p in ("tests/test_x.py", "src/test/java/com/FooTest.java", "a/foo_test.dart",
              "web/src/foo.spec.ts", "web/__tests__/x.ts", "pkg/x.test.tsx",
              "src/test/kotlin/BarTests.kt", "it/OrderIT.java"):
        assert attribution.is_test_file(p), p


def test_does_not_mistake_production_code_for_tests():
    for p in ("src/store/store.py", "src/latest/index.ts", "src/contest/Entry.java",
              "src/protest.py", "README.md", "pom.xml", "src/attestation/Attest.kt"):
        assert not attribution.is_test_file(p), p


def test_build_output_is_not_scanned(tmp_path):
    (tmp_path / "target" / "test-classes").mkdir(parents=True)
    (tmp_path / "target" / "test-classes" / "FooTest.java").write_text("x", encoding="utf-8")
    assert attribution.find_test_files(tmp_path) == []


# ---- attributing ------------------------------------------------------------

def test_attributes_a_test_to_the_node_whose_code_it_imports(tmp_path):
    nodes, root = _py_project(tmp_path)
    by_node = attribution.attribute(nodes, root)
    assert [p.split("/")[-1] for p in by_node["app.store"]] == ["test_store.py"]
    assert by_node["app.ingest"] == set()   # no test reaches it


def test_attributes_a_test_the_node_owns_outright(tmp_path):
    """A Maven-style component owning its own test tree needs no import edge."""
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    d = tmp_path / "src" / "test" / "java" / "app" / "pay"
    d.mkdir(parents=True)
    (d / "PayTest.java").write_text("package app.pay;\nclass PayTest {}\n", encoding="utf-8")
    nodes = {"app.pay": {"id": "app.pay", "kind": "component", "parent": "app",
                         "code": ["src/test/java/**/pay/**"], "status": "verified"}}
    assert attribution.attribute(nodes, str(tmp_path))["app.pay"]


def test_unattributed_names_the_node_the_build_root_carried(tmp_path):
    nodes, root = _py_project(tmp_path)
    assert attribution.unattributed(nodes, root) == ["app.ingest"]


def test_unattributed_only_considers_the_given_statuses(tmp_path):
    nodes, root = _py_project(tmp_path)
    nodes["app.ingest"]["status"] = "implemented"
    assert attribution.unattributed(nodes, root) == []


def test_blind_scanner_reports_nothing_rather_than_everything(tmp_path):
    """If attribution works for no node at all, the honest answer is 'unknown'.
    Claiming every node is untested would be worse than saying nothing."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    nodes = {"app.a": {"id": "app.a", "kind": "component", "parent": "app",
                       "code": ["src/**"], "status": "verified"}}
    assert attribution.unattributed(nodes, str(tmp_path)) == []


# ---- the gate ---------------------------------------------------------------

def test_gate_warns_about_the_node_no_test_reaches(tmp_path):
    nodes, root = _py_project(tmp_path)
    lifecycle.record_evidence(root, list(nodes), "pass", "uv run pytest", root)
    issues = lifecycle.status_issues(nodes, root)
    warns = [m for sev, m in issues if sev == "WARN" and "no test attributes" in m]
    assert len(warns) == 1 and "app.ingest" in warns[0]
    assert not [m for sev, m in issues if sev == "HARD"]  # still passes the gate


def test_evidence_record_keeps_the_attributed_test_files(tmp_path):
    nodes, root = _py_project(tmp_path)
    by_node = attribution.attribute(nodes, root)
    lifecycle.record_evidence(root, list(nodes), "pass", "uv run pytest", root,
                              tests_by_node=by_node)
    ev = lifecycle.load_evidence(root)
    assert ev["app.store"]["tests"] and ev["app.ingest"]["tests"] == []
    assert ev["app.store"]["build_root"] == root  # the coarse fact is still recorded
