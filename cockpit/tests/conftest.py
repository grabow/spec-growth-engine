"""Shared pytest fixtures: build small spec graphs in a tmp directory."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _no_real_endpoints(monkeypatch):
    """No test sees the roles configured in cockpit/.env. app.py loads that file
    when it is imported, so without this every test after the first import ran
    with real endpoints and keys -- a test could pass only because a person's
    .env was filled, or reach a provider. A test that needs a role sets it."""
    import os
    for name in list(os.environ):
        if name.startswith("SGE_") and name.endswith(("_BASE_URL", "_API_KEY", "_MODEL",
                                                      "_HARNESS")):
            monkeypatch.delenv(name, raising=False)


def write_spec(directory: Path, body: str = "", **meta) -> Path:
    """Write a SPEC.md (frontmatter + body) into `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=False).rstrip()
    path = directory / "SPEC.md"
    path.write_text(f"---\n{fm}\n---\n\n{body}\n", encoding="utf-8")
    return path


@pytest.fixture
def graph_root(tmp_path: Path) -> Path:
    """app(system) -> api(container) -> api.hello(component, depends_on util);
    util(component) is a sibling cousin used as a legit cross-dependency."""
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n## Invariants\n- Implementation language: Python 3.12.\n",
        encoding="utf-8",
    )
    write_spec(
        tmp_path, id="app", parent=None, kind="system",
        contract={
            "purpose": "demo system",
            "provides": ["APP_PROVIDES"],
            "invariants": ["APP_INVARIANT"],
            "acceptance_criteria": ["APP_ACCEPT_MARKER"],
        },
        design={"children": ["api", "util"]}, code=[],
    )
    write_spec(
        tmp_path / "api", id="api", parent="app", kind="container",
        contract={"provides": ["http"]}, design={"children": ["api.hello"]}, code=[],
    )
    write_spec(
        tmp_path / "api" / "hello", id="api.hello", parent="api", kind="component",
        contract={
            "provides": ["greet()"],
            "invariants": ["prints hallo"],
            "acceptance_criteria": ["greet prints hallo"],
        },
        depends_on=["util"], code=["api/hello/*.py"],  # project-root-relative
        body="Leaf component.",
    )
    (tmp_path / "api" / "hello" / "greet.py").write_text(
        'print("hallo")\n', encoding="utf-8"
    )
    write_spec(
        tmp_path / "util", id="util", parent="app", kind="component",
        contract={"provides": ["log()"]}, code=["util/*.py"],
    )
    (tmp_path / "util" / "log.py").write_text("def log(m):\n    print(m)\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def ts_root(tmp_path: Path) -> Path:
    """A TS graph for drift tests: checkout imports payment (declared) and util
    (UNDECLARED -> drift). Each node owns its directory's *.ts files."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n- TS\n", encoding="utf-8")
    write_spec(tmp_path, id="app", parent=None, kind="system",
               design={"children": ["checkout", "payment", "util"]}, code=[])
    write_spec(tmp_path / "checkout", id="checkout", parent="app", kind="component",
               contract={"provides": ["createOrder()"]}, depends_on=["payment"],
               code=["checkout/*.ts"])
    write_spec(tmp_path / "payment", id="payment", parent="app", kind="component",
               contract={"provides": ["authorize()"]}, code=["payment/*.ts"])
    write_spec(tmp_path / "util", id="util", parent="app", kind="component",
               contract={"provides": ["log()"]}, code=["util/*.ts"])
    (tmp_path / "checkout" / "checkout.ts").write_text(
        'import { authorize } from "../payment/payment";\n'
        'import { log } from "../util/log";\n'
        "export function createOrder(){ log('x'); return authorize(1); }\n",
        encoding="utf-8",
    )
    (tmp_path / "payment" / "payment.ts").write_text(
        "export function authorize(n: number){ return n > 0; }\n", encoding="utf-8"
    )
    (tmp_path / "util" / "log.ts").write_text(
        "export function log(m: string){ console.log(m); }\n", encoding="utf-8"
    )
    return tmp_path
