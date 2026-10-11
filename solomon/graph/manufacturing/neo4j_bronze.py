"""Spark / sample Cypher 投入の Neo4j モデル (Product / Kiban / SourceFile) 参照。"""
from __future__ import annotations

from typing import Any

from solomon.graph.config import get_neo4j_config
from solomon.graph.neo4j_connect import iter_neo4j_connection_uris

_CYPHER_KIBAN_FILES = """
MATCH (k:Kiban {id: $trace_id})<-[:HAS_KIBAN]-(p:Product)<-[:INGESTED_INTO]-(f:SourceFile)
RETURN f.key AS key, f.format AS format, f.etag AS etag, p.trace_id AS product_trace_id
ORDER BY f.format, f.key
"""

_CYPHER_VB_LINKS = """
MATCH (k:Kiban {id: $trace_id})-[r:TESTED_ON_VB]->(v:VbMachine)
RETURN v.id AS vb_machine_no, r.link_type AS link_type, r.confidence AS confidence
LIMIT 5
"""


def fetch_bronze_graph_context(trace_id: str) -> dict[str, Any]:
    """Kiban に紐づく SourceFile 一覧（数値メトリクスは Iceberg 側）。"""
    config = get_neo4j_config()
    if config is None:
        return {"trace_id": trace_id, "error": "NEO4J_NOT_CONFIGURED"}

    try:
        from neo4j import GraphDatabase
    except ImportError:
        return {"trace_id": trace_id, "error": "neo4j driver not installed"}

    last_error: str | None = None
    for uri in iter_neo4j_connection_uris(config.uri):
        driver = GraphDatabase.driver(uri, auth=(config.username, config.password))
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                files = [dict(r) for r in session.run(_CYPHER_KIBAN_FILES, trace_id=trace_id)]
                vb_links = [dict(r) for r in session.run(_CYPHER_VB_LINKS, trace_id=trace_id)]
            if not files:
                return {"trace_id": trace_id, "error": "NOT_FOUND", "model": "bronze"}
            by_format: dict[str, int] = {}
            for row in files:
                fmt = str(row.get("format") or "unknown")
                by_format[fmt] = by_format.get(fmt, 0) + 1
            notes_parts = [
                f"Neo4j: Kiban `{trace_id}` に SourceFile {len(files)} 件"
            ]
            if by_format:
                fmt_summary = ", ".join(f"{k}={v}" for k, v in sorted(by_format.items()))
                notes_parts.append(f"（{fmt_summary}）")
            if vb_links:
                notes_parts.append(f"TESTED_ON_VB {len(vb_links)} 件")
            return {
                "trace_id": trace_id,
                "source": "neo4j",
                "model": "bronze",
                "neo4j_source_files": files,
                "neo4j_vb_links": vb_links,
                "notes": "。".join(notes_parts) + "。",
            }
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        finally:
            driver.close()

    return {"trace_id": trace_id, "error": last_error or "NEO4J_QUERY_FAILED", "model": "bronze"}


__all__ = ["fetch_bronze_graph_context"]
