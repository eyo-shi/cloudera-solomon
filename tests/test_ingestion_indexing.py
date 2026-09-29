"""Ingestion indexing integration tests (Neo4j System/Document + OpenSearch)."""

from __future__ import annotations

from solomon.graph.neo4j_loader import IngestionGraphPayload
from solomon.graph.system import build_ingestion_documents, infer_system_name, normalize_system_id
from solomon.opensearch.indexer import build_searchable_text
from solomon.tools.opensearch import OpenSearchIndexTool


def test_normalize_system_id() -> None:
    assert normalize_system_id("System A") == "system_a"


def test_infer_system_from_s3_key() -> None:
    name = infer_system_name(
        key="billing_app/incidents/2025.csv",
        schema="demo",
        meta_kv=[],
    )
    assert name == "billing_app"


def test_infer_system_from_meta_kv() -> None:
    name = infer_system_name(
        key="data.csv",
        schema="demo",
        meta_kv=[{"key": "system", "value": "CoreBanking"}],
    )
    assert name == "CoreBanking"


def test_build_ingestion_documents() -> None:
    docs = build_ingestion_documents(
        dataset_id="iceberg.demo.incidents",
        bucket="data",
        key="billing_app/incidents.csv",
        format="csv",
        ossie_path="datasets/iceberg/demo/incidents.yaml",
        meta_kv=[{"key": "設計書", "value": "障害管理仕様 v2"}],
    )
    types = {d.doc_type for d in docs}
    assert "source_file" in types
    assert "semantic_layer" in types
    assert "design_doc" in types


def test_ingestion_payload_system_id() -> None:
    payload = IngestionGraphPayload(
        catalog="iceberg",
        schema="demo",
        table="incidents",
        columns=[],
        bucket="data",
        key="app_a/incidents.csv",
        format="csv",
        system_name="app_a",
    )
    assert payload.system_id == "app_a"


def test_build_searchable_text_includes_description() -> None:
    text = build_searchable_text(
        dataset={
            "name": "incidents",
            "fq_name": "iceberg.demo.incidents",
            "description": "Monthly incident records",
            "dimensions": [{"name": "severity", "description": "Severity level"}],
        }
    )
    assert "incidents" in text
    assert "Monthly incident" in text
    assert "severity" in text


def test_opensearch_index_skips_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("OPENSEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENSEARCH_HOST", raising=False)
    result = OpenSearchIndexTool().run(
        user_ctx=None,
        fq_name="iceberg.demo.incidents",
        dataset={"name": "incidents", "fq_name": "iceberg.demo.incidents"},
        system_id="app_a",
        documents=[{"id": "doc:1", "title": "spec", "doc_type": "design_doc", "path": "s3://x"}],
    )
    assert result["status"] == "ok"
    assert result["skipped"] is True
