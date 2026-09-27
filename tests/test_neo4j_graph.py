"""Neo4j graph integration tests (no live Neo4j required)."""

from __future__ import annotations

from solomon.graph.neo4j_connect import iter_neo4j_connection_uris, validate_neo4j_uri_for_ingest
from solomon.graph.neo4j_loader import ColumnGraphNode, IngestionGraphPayload
from solomon.tools.neo4j_graph import Neo4jGraphLoadTool


def test_iter_neo4j_connection_uris_internal_host(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.neo4j_connect.resolve_bolt_uris_from_k8s",
        lambda *args, **kwargs: [],
    )
    uri = "bolt://cml-neo4j-abc.mlx-user-123:7687"
    candidates = iter_neo4j_connection_uris(uri)
    assert uri in candidates
    assert any(".svc.cluster.local" in c for c in candidates)
    assert "bolt://cml-neo4j-abc:7687" in candidates


def test_iter_neo4j_connection_uris_prefers_bolt_host_override(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_BOLT_HOST", "10.42.1.17")
    monkeypatch.setattr(
        "solomon.graph.neo4j_connect.resolve_bolt_uris_from_k8s",
        lambda *args, **kwargs: [],
    )
    candidates = iter_neo4j_connection_uris("bolt://cml-neo4j-abc.mlx-user-123:7687")
    assert candidates[0] == "bolt://10.42.1.17:7687"


def test_iter_neo4j_connection_uris_includes_external_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "NEO4J_EXTERNAL_URI",
        "bolt://abc.elb.amazonaws.com:7687",
    )
    monkeypatch.setattr(
        "solomon.graph.neo4j_connect.resolve_bolt_uris_from_k8s",
        lambda *args, **kwargs: [],
    )
    uri = "bolt://cml-neo4j-abc.mlx-user-123:7687"
    candidates = iter_neo4j_connection_uris(uri)
    assert "bolt://abc.elb.amazonaws.com:7687" in candidates


def test_iter_neo4j_connection_uris_skips_unset_optional_env(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_EXTERNAL_URI", "-")
    monkeypatch.setenv("NEO4J_INTERNAL_URI", "-")
    uri = "bolt://abc.elb.amazonaws.com:7687"
    candidates = iter_neo4j_connection_uris(uri)
    assert candidates == ["bolt://abc.elb.amazonaws.com:7687"]
    assert "bolt://-:7687" not in candidates


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
