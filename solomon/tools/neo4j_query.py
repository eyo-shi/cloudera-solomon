"""Neo4j read-only graph query Tool (Entity / Relationship traversal)."""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.graph.config import get_neo4j_config
from solomon.graph.neo4j_connect import iter_neo4j_connection_uris
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.logging import get_logger
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)

_FORBIDDEN_CYPHER = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+\{)\b",
    re.IGNORECASE,
)


def validate_readonly_cypher(cypher: str) -> str | None:
    """読取専用 Cypher か検証。問題があればエラーメッセージを返す。"""
    stripped = cypher.strip()
    if not stripped:
        return "Cypher query is empty."
    if _FORBIDDEN_CYPHER.search(stripped):
        return "Only read-only Cypher (MATCH/RETURN) is allowed."
    if not re.match(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|CALL\s+\{?\s*MATCH)", stripped, re.I):
        return "Query must start with MATCH or WITH."
    return None


class Neo4jGraphQueryArgs(BaseModel):
    cypher: str = Field(..., description="Read-only Cypher (MATCH ... RETURN ...)")
    params: dict[str, Any] = Field(default_factory=dict, description="Cypher parameters")


class Neo4jGraphQueryTool(BaseSolomonTool):
    """Neo4j グラフを読取専用 Cypher で travers する。

    Dataset / Column / SourceFile / Schema ノードと HAS_COLUMN / IN_SCHEMA /
    SOURCED_FROM リレーションを探索する。書き込み系 Cypher は拒否する。
    """

    name: str = "neo4j_graph_query"
    description: str = (
        "Run a read-only Cypher query against Neo4j to explore datasets, columns, "
        "source files, and relationships (lineage). Mutations are rejected."
    )
    args_schema: type[BaseModel] = Neo4jGraphQueryArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        cypher: str,
        params: Optional[dict[str, Any]] = None,
        **_: Any,
    ) -> dict[str, Any]:
        config = get_neo4j_config()
        if config is None:
            return err(
                ErrorCode.NEO4J_NOT_CONFIGURED,
                "NEO4J_URI is not configured.",
            )
        validation = validate_readonly_cypher(cypher)
        if validation:
            return err(ErrorCode.NEO4J_QUERY_FAILED, validation)

        try:
            from neo4j import GraphDatabase
        except ImportError:
            return err(ErrorCode.NEO4J_CONNECT_FAILED, "neo4j driver is not installed.")

        params = params or {}
        last_error: Exception | None = None
        for uri in iter_neo4j_connection_uris(config.uri):
            driver = GraphDatabase.driver(uri, auth=(config.username, config.password))
            try:
                driver.verify_connectivity()
                with driver.session() as session:
                    result = session.run(cypher, **params)
                    records = [dict(r) for r in result]
                return ok({"neo4j_uri": uri, "records": records, "count": len(records)})
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                _logger.debug("neo4j_query.failed", uri=uri, error=str(exc))
            finally:
                driver.close()

        return err(
            ErrorCode.NEO4J_CONNECT_FAILED,
            f"Neo4j query failed: {last_error}",
        )


# ------------------------------------------------------------------ #
# テンプレートクエリ (Orchestrator から利用)
# ------------------------------------------------------------------ #

def query_dataset_lineage(entity_hint: str) -> dict[str, Any]:
    """Dataset 名 / fq_name に部分一致するリネージを返す。"""
    tool = Neo4jGraphQueryTool()
    cypher = """
    MATCH (d:Dataset)
    WHERE toLower(d.fq_name) CONTAINS toLower($hint)
       OR toLower(d.name) CONTAINS toLower($hint)
    OPTIONAL MATCH (d)-[:HAS_COLUMN]->(c:Column)
    OPTIONAL MATCH (d)-[:SOURCED_FROM]->(s:SourceFile)
    OPTIONAL MATCH (d)-[:IN_SCHEMA]->(sch:Schema)
    RETURN d.id AS dataset_id, d.fq_name AS fq_name,
           collect(DISTINCT c.name) AS columns,
           s.path AS source_path, sch.id AS schema_id
    LIMIT 10
    """
    return tool.run(user_ctx=None, cypher=cypher, params={"hint": entity_hint})


def query_system_assets(system_hint: str) -> dict[str, Any]:
    """System に紐づく Dataset / Document を travers する。"""
    tool = Neo4jGraphQueryTool()
    cypher = """
    MATCH (sys:System)
    WHERE toLower(sys.name) CONTAINS toLower($hint)
       OR toLower(sys.id) CONTAINS toLower($hint)
    OPTIONAL MATCH (sys)-[:OWNS_DATASET]->(d:Dataset)
    OPTIONAL MATCH (sys)-[:HAS_DOCUMENT]->(doc:Document)
    OPTIONAL MATCH (doc)-[:REFERENCES_DATASET]->(d2:Dataset)
    RETURN sys.id AS system_id, sys.name AS system_name,
           collect(DISTINCT d.fq_name) AS datasets,
           collect(DISTINCT {id: doc.id, title: doc.title, type: doc.doc_type, path: doc.path}) AS documents,
           collect(DISTINCT d2.fq_name) AS referenced_datasets
    LIMIT 5
    """
    return tool.run(user_ctx=None, cypher=cypher, params={"hint": system_hint})


def query_all_datasets(limit: int = 20) -> dict[str, Any]:
    """登録済み Dataset 一覧。"""
    tool = Neo4jGraphQueryTool()
    cypher = """
    MATCH (d:Dataset)
    OPTIONAL MATCH (d)-[:SOURCED_FROM]->(s:SourceFile)
    RETURN d.fq_name AS fq_name, d.format AS format, s.path AS source_path
    ORDER BY d.ingested_at DESC
    LIMIT $limit
    """
    return tool.run(user_ctx=None, cypher=cypher, params={"limit": limit})
