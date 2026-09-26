"""Neo4j graph integration tests (no live Neo4j required)."""

from __future__ import annotations

from gandalf.graph.neo4j_connect import iter_neo4j_connection_uris, validate_neo4j_uri_for_ingest
from gandalf.graph.neo4j_loader import ColumnGraphNode, IngestionGraphPayload
from gandalf.tools.neo4j_graph import Neo4jGraphLoadTool


def test_iter_neo4j_connection_uris_internal_host() -> None:
    uri = "bolt://cml-neo4j-abc.mlx-user-123:7687"
    candidates = iter_neo4j_connection_uris(uri)
    assert uri in candidates
    assert any(".svc.cluster.local" in c for c in candidates)


def test_validate_neo4j_uri_rejects_browser_url() -> None:
    try:
        validate_neo4j_uri_for_ingest("bolt://neo4j-launcher-abc.cloudera.site:7687")
    except ValueError as exc:
        assert "browser URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_ingestion_graph_payload_ids() -> None:
    payload = IngestionGraphPayload(
        catalog="iceberg",
        schema="demo",
        table="sales",
        columns=[ColumnGraphNode(name="id", trino_type="BIGINT")],
        bucket="data",
        key="sales.xlsx",
        format="xlsx",
    )
    assert payload.dataset_id == "iceberg.demo.sales"
    assert payload.source_id == "s3://data/sales.xlsx"


def test_neo4j_graph_load_tool_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("NEO4J_URI", raising=False)
    tool = Neo4jGraphLoadTool()
    result = tool.run(
        user_ctx=None,
        catalog="iceberg",
        schema="demo",
        table="sales",
        columns=[{"name": "id", "trino_type": "BIGINT"}],
        bucket="data",
        key="sales.xlsx",
        format="xlsx",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "NEO4J_NOT_CONFIGURED"
