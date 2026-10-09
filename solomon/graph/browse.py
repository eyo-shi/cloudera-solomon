"""Neo4j graph browser service — schema introspection and visualization queries."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from solomon.graph.models import (
    GraphEdgeDTO,
    GraphNodeDTO,
    GraphQueryResponse,
    GraphSchemaResponse,
    GraphVisualization,
)
from solomon.graph.session import Neo4jSessionError, with_read_session

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_DEPTH = 3


def _validate_identifier(value: str, kind: str) -> str:
    if not value or not _IDENTIFIER.match(value):
        raise ValueError(f"Invalid {kind}: {value!r}")
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _node_props(node: Any) -> dict[str, Any]:
    if hasattr(node, "items"):
        return dict(node.items())
    return dict(node)


def _node_id(node: Any) -> str:
    props = _node_props(node)
    if props.get("id") is not None:
        return str(props["id"])
    element_id = getattr(node, "element_id", None)
    if element_id:
        return str(element_id)
    return str(node.id)


def _relationship_id(rel: Any) -> str:
    element_id = getattr(rel, "element_id", None)
    if element_id:
        return str(element_id)
    return f"rel-{rel.id}"


def _caption(labels: list[str], props: dict[str, Any]) -> str:
    for key in (
        "trace_id",
        "kiban",
        "at_serial",
        "customer_part_no",
        "symbol_name",
        "name",
        "fq_name",
        "title",
        "id",
        "path",
    ):
        val = props.get(key)
        if val:
            return str(val)
    return labels[0] if labels else "Node"


def _serialize_node(node: Any) -> GraphNodeDTO:
    labels = list(node.labels)
    props = _json_safe(_node_props(node))
    return GraphNodeDTO(
        id=_node_id(node),
        labels=labels,
        properties=props if isinstance(props, dict) else {},
        caption=_caption(labels, props if isinstance(props, dict) else {}),
    )


def _serialize_relationship(rel: Any) -> GraphEdgeDTO:
    start_id = _node_id(rel.start_node) if hasattr(rel, "start_node") else ""
    end_id = _node_id(rel.end_node) if hasattr(rel, "end_node") else ""
    props = _json_safe(dict(rel))
    return GraphEdgeDTO(
        id=_relationship_id(rel),
        type=rel.type,
        source=start_id,
        target=end_id,
        properties=props if isinstance(props, dict) else {},
    )


def _collect_graph(records: list[Any], *, limit: int) -> GraphVisualization:
    nodes: dict[str, GraphNodeDTO] = {}
    edges: dict[str, GraphEdgeDTO] = {}
    truncated = False

    def _is_node(value: Any) -> bool:
        return hasattr(value, "labels") and hasattr(value, "id")

    def _is_relationship(value: Any) -> bool:
        return hasattr(value, "type") and hasattr(value, "start_node")

    def _is_path(value: Any) -> bool:
        return hasattr(value, "nodes") and hasattr(value, "relationships")

    def absorb(value: Any) -> None:
        nonlocal truncated
        if _is_node(value):
            dto = _serialize_node(value)
            nodes[dto.id] = dto
        elif _is_relationship(value):
            dto = _serialize_relationship(value)
            edges[dto.id] = dto
        elif _is_path(value):
            for n in value.nodes:
                absorb(n)
            for r in value.relationships:
                absorb(r)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                absorb(item)
        elif isinstance(value, dict):
            for item in value.values():
                absorb(item)

    for record in records:
        if len(nodes) >= limit:
            truncated = True
            break
        for value in record.values():
            absorb(value)

    return GraphVisualization(
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        truncated=truncated,
    )


def _run_collect(cypher: str, params: dict[str, Any], *, limit: int) -> GraphVisualization:
    def _execute(session: Any) -> GraphVisualization:
        result = session.run(cypher, **params)
        records = list(result)
        return _collect_graph(records, limit=limit)

    return with_read_session(_execute)


def _response(
    query_type: str,
    cypher: str,
    graph: GraphVisualization,
) -> GraphQueryResponse:
    graph.query_type = query_type  # type: ignore[assignment]
    graph.cypher = cypher
    return GraphQueryResponse(
        query_type=query_type,  # type: ignore[arg-type]
        cypher=cypher,
        graph=graph,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
    )


def fetch_schema() -> GraphSchemaResponse:
    """Neo4j schema (labels / relationship types / property keys) を取得。"""

    def _execute(session: Any) -> GraphSchemaResponse:
        labels = [
            row["label"]
            for row in session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
        ]
        rel_types = [
            row["relationshipType"]
            for row in session.run(
                "CALL db.relationshipTypes() YIELD relationshipType "
                "RETURN relationshipType ORDER BY relationshipType"
            )
        ]
        prop_keys = [
            row["propertyKey"]
            for row in session.run(
                "CALL db.propertyKeys() YIELD propertyKey "
                "RETURN propertyKey ORDER BY propertyKey"
            )
        ]
        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        return GraphSchemaResponse(
            node_labels=labels,
            relationship_types=rel_types,
            property_keys=prop_keys,
            node_count=int(node_count or 0),
            relationship_count=int(rel_count or 0),
        )

    return with_read_session(_execute)


_READ_FORBIDDEN = re.compile(
    r"\b(CREATE|DELETE|DETACH|SET|REMOVE|MERGE|DROP|LOAD\s+CSV|FOREACH|CALL\s*\{)\b",
    re.IGNORECASE,
)


def execute_read_cypher(cypher: str, *, limit: int = 100) -> GraphQueryResponse:
    """Read-only Cypher を実行して Graph 可視化を返す。"""
    text = cypher.strip().rstrip(";")
    if not text:
        raise ValueError("Cypher query is empty")
    if _READ_FORBIDDEN.search(text):
        raise ValueError("Only read-only Cypher queries are allowed")
    if re.search(r"\bLIMIT\b", text, re.IGNORECASE):
        graph = _run_collect(text, {}, limit=limit)
    else:
        graph = _run_collect(f"{text} LIMIT $limit", {"limit": limit}, limit=limit)
    return _response("entity", text, graph)


def query_by_label(label: str, limit: int = 100) -> GraphQueryResponse:
    safe_label = _validate_identifier(label, "label")
    cypher = f"""
    MATCH (n:`{safe_label}`)
    RETURN n
    LIMIT $limit
    """
    graph = _run_collect(cypher, {"limit": limit}, limit=limit)
    return _response("label", cypher.strip(), graph)


def query_by_relationship_type(rel_type: str, limit: int = 100) -> GraphQueryResponse:
    safe_type = _validate_identifier(rel_type, "relationship type")
    cypher = f"""
    MATCH (a)-[r:`{safe_type}`]->(b)
    RETURN a, r, b
    LIMIT $limit
    """
    graph = _run_collect(cypher, {"limit": limit}, limit=limit)
    return _response("relationship", cypher.strip(), graph)


def query_by_property_key(key: str, limit: int = 100) -> GraphQueryResponse:
    safe_key = _validate_identifier(key, "property key")
    cypher = """
    MATCH (n)
    WHERE n[$key] IS NOT NULL
    RETURN n
    LIMIT $limit
    """
    graph = _run_collect(cypher, {"key": safe_key, "limit": limit}, limit=limit)
    return _response("property", cypher.strip(), graph)


def query_neighborhood(
    node_id: str,
    *,
    depth: int = 1,
    limit: int = 100,
) -> GraphQueryResponse:
    depth = max(1, min(depth, _MAX_DEPTH))
    # 可変長パターンの上限は Neo4j でパラメータ化できないため、検証済み depth を直埋めする
    cypher = f"""
    MATCH (n)
    WHERE coalesce(n.id, elementId(n)) = $node_id
    MATCH path = (n)-[*1..{depth}]-(m)
    WITH path
    LIMIT $limit
    UNWIND nodes(path) AS node
    UNWIND relationships(path) AS rel
    RETURN DISTINCT node, rel
    """
    graph = _run_collect(
        cypher,
        {"node_id": node_id, "depth": depth, "limit": limit},
        limit=limit,
    )
    return _response("neighborhood", cypher.strip(), graph)


def visualize_entity_hint(entity_hint: str, limit: int = 100) -> GraphQueryResponse:
    """RAG / Agent 向け: System または Dataset 中心の可視化グラフ。"""
    hint = entity_hint.strip()
    if not hint:
        cypher = """
        MATCH (d:Dataset)
        OPTIONAL MATCH (d)-[r]-(m)
        RETURN d, r, m
        LIMIT $limit
        """
        graph = _run_collect(cypher, {"limit": limit}, limit=limit)
        return _response("entity", cypher.strip(), graph)

    cypher = """
    MATCH (sys:System)
    WHERE toLower(sys.name) CONTAINS toLower($hint)
       OR toLower(sys.id) CONTAINS toLower($hint)
    OPTIONAL MATCH (sys)-[r1:OWNS_DATASET|HAS_DOCUMENT]->(child)
    OPTIONAL MATCH (child)-[r2:REFERENCES_DATASET|HAS_COLUMN|SOURCED_FROM|IN_SCHEMA]->(related)
    RETURN sys, r1, child, r2, related
    LIMIT $limit
    """
    graph = _run_collect(cypher, {"hint": hint, "limit": limit}, limit=limit)
    if graph.nodes:
        return _response("entity", cypher.strip(), graph)

    fallback = """
    MATCH (d:Dataset)
    WHERE toLower(d.fq_name) CONTAINS toLower($hint)
       OR toLower(d.name) CONTAINS toLower($hint)
    OPTIONAL MATCH (d)-[r]-(m)
    RETURN d, r, m
    LIMIT $limit
    """
    graph = _run_collect(fallback, {"hint": hint, "limit": limit}, limit=limit)
    return _response("entity", fallback.strip(), graph)


__all__ = [
    "Neo4jSessionError",
    "fetch_schema",
    "query_by_label",
    "query_by_relationship_type",
    "query_by_property_key",
    "query_neighborhood",
    "visualize_entity_hint",
    "execute_read_cypher",
]
