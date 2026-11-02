"""demo.loader unit tests (no external services)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DOMAIN = REPO / "tests" / "fixtures" / "demo_loader"
MFG = REPO / "demo" / "mfg_quality"


@pytest.fixture
def neutral_domain(tmp_path: Path) -> Path:
    domain = tmp_path / "demo_domain"
    sem = domain / "semantic" / "models"
    sem.mkdir(parents=True)
    src = FIXTURE_DOMAIN / "semantic" / "models" / "demo_neutral.yaml"
    (sem / "demo_neutral.yaml").write_text(src.read_text(encoding="utf-8"))
    (domain / "output").mkdir()
    return domain


def test_trino_type_mapping() -> None:
    from demo.loader.trino_types import create_table_ddl, trino_type
    from solomon.semantic.models import OssieField

    assert trino_type(OssieField(name="x", datatype="Integer")) == "bigint"
    assert trino_type(OssieField(name="d", datatype="Decimal")) == "decimal(18,4)"
    ddl = create_table_ddl(
        "iceberg.demo_schema.entities",
        [OssieField(name="entity_id", datatype="String")],
    )
    assert "varchar" in ddl
    assert "iceberg.demo_schema.entities" in ddl


def test_puppygraph_schema_from_ossie(neutral_domain: Path) -> None:
    from demo.loader.ossie_domain import load_domain
    from demo.loader.puppygraph_schema import build_puppygraph_schema

    domain = load_domain(neutral_domain, validate=False)
    schema = build_puppygraph_schema(domain, catalog_type="hms")
    assert len(schema["vertices"]) == 1
    assert schema["vertices"][0]["label"] == "Entity"
    assert len(schema["edges"]) == 1
    edge = schema["edges"][0]
    assert edge["fromLabel"] == "Entity"
    assert edge["toLabel"] == "Entity"
    assert edge["fromId"]["fields"] == ["from_id"]


def test_docs_mapping_from_ossie(neutral_domain: Path) -> None:
    from demo.loader.ossie_domain import load_domain
    from demo.loader.search_load import _doc_index_def
    from solomon.opensearch.docs_mapping import build_docs_mapping

    domain = load_domain(neutral_domain, validate=False)
    doc_def = _doc_index_def(domain)
    body = build_docs_mapping(doc_def, analyzer="cjk", embedding_dim=1024)
    props = body["mappings"]["properties"]
    assert "text" in props
    assert "embedding" in props


def test_dry_run_no_network(neutral_domain: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "demo.loader",
            "--domain-dir",
            str(neutral_domain),
            "--target",
            "all",
            "--dry-run",
        ],
        cwd=REPO,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "POST" in proc.stdout
    assert "Entity" in proc.stdout


@pytest.mark.skipif(not MFG.is_dir(), reason="demo/mfg_quality missing")
def test_mfg_semantic_validates() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "solomon.semantic",
            "validate",
            "--root",
            str(MFG / "semantic"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(not MFG.is_dir(), reason="demo/mfg_quality missing")
def test_mfg_puppygraph_schema_has_consumed_by() -> None:
    from demo.loader.ossie_domain import load_domain
    from demo.loader.puppygraph_schema import build_puppygraph_schema

    domain = load_domain(MFG, validate=True)
    schema = build_puppygraph_schema(domain)
    labels = {e["label"] for e in schema["edges"]}
    assert "CONSUMED_BY" in labels
