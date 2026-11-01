"""PuppyGraph read-only openCypher query Tool."""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.graph.bolt_driver import open_driver
from solomon.graph.config import get_graph_config
from solomon.graph.session import graph_connection_uris
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
    stripped = cypher.strip()
    if not stripped:
        return "Cypher query is empty."
    if _FORBIDDEN_CYPHER.search(stripped):
        return "Only read-only Cypher (MATCH/RETURN/CALL db.*) is allowed."
    if re.match(r"^\s*CALL\s+db\.", stripped, re.I):
        return None
    if not re.match(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH)", stripped, re.I):
        return "Query must start with MATCH, WITH, or CALL db.*."
    return None


class GraphCypherQueryArgs(BaseModel):
    cypher: str = Field(..., description="Read-only openCypher (MATCH ... RETURN ...)")
    params: dict[str, Any] = Field(default_factory=dict, description="Cypher parameters")


class GraphCypherQueryTool(BaseSolomonTool):
    """PuppyGraph (Iceberg / RDB) を読取専用 openCypher で travers する。"""

    name: str = "graph_cypher_query"
    description: str = (
        "Run read-only openCypher against PuppyGraph (Lakehouse/RDB-backed graph) "
        "for lineage and relationship traversals. Mutations are rejected."
    )
    args_schema: type[BaseModel] = GraphCypherQueryArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        cypher: str,
        params: Optional[dict[str, Any]] = None,
        **_: Any,
    ) -> dict[str, Any]:
        if get_graph_config() is None:
            return err(
                ErrorCode.GRAPH_NOT_CONFIGURED,
                "PUPPYGRAPH_URI is not configured.",
            )
        validation = validate_readonly_cypher(cypher)
        if validation:
            return err(ErrorCode.GRAPH_QUERY_FAILED, validation)

        config = get_graph_config()
        assert config is not None

        params = params or {}
        last_error: Exception | None = None
        for uri in graph_connection_uris(config.uri):
            try:
                driver = open_driver(uri, username=config.username, password=config.password)
            except ImportError as exc:
                return err(ErrorCode.GRAPH_CONNECT_FAILED, str(exc))
            try:
                driver.verify_connectivity()
                with driver.session() as session:
                    result = session.run(cypher, **params)
                    records = [dict(r) for r in result]
                return ok({"bolt_uri": uri, "records": records, "count": len(records)})
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                _logger.debug("graph_cypher_query.failed", uri=uri, error=str(exc))
            finally:
                driver.close()

        return err(
            ErrorCode.GRAPH_CONNECT_FAILED,
            f"PuppyGraph query failed: {last_error}",
        )


def query_dataset_lineage(entity_hint: str) -> dict[str, Any]:
    tool = GraphCypherQueryTool()
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
    tool = GraphCypherQueryTool()
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
    tool = GraphCypherQueryTool()
    cypher = """
    MATCH (d:Dataset)
    OPTIONAL MATCH (d)-[:SOURCED_FROM]->(s:SourceFile)
    RETURN d.fq_name AS fq_name, d.format AS format, s.path AS source_path
    ORDER BY d.ingested_at DESC
    LIMIT $limit
    """
    return tool.run(user_ctx=None, cypher=cypher, params={"limit": limit})
