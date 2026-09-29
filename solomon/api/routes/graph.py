"""Neo4j graph browser API (`/api/graph/*`).

TreePane Graph タブ + ResultPane Graph 可視化 + Agent artifact 用。
Cypher は solomon.graph.browse で生成・実行する。
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from solomon.api.auth import require_user_context
from solomon.graph import browse
from solomon.graph.config import get_neo4j_config
from solomon.graph.models import CypherRequest, GraphQueryResponse, GraphSchemaResponse
from solomon.graph.session import Neo4jSessionError
from solomon.transport.user_context import UserContext

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _require_neo4j_or_503() -> None:
    if get_neo4j_config() is None:
        from solomon.graph.mode import is_external_neo4j_mode, is_internal_neo4j_mode

        if is_internal_neo4j_mode():
            instruction = (
                "NEO4J_MODE=internal です。neo4j-launcher Application "
                "が Running であることを確認し、Application Log で "
                ".solomon/neo4j_endpoints.json が書き込まれるまで待ってから "
                "Solomon Application を再起動してください。"
            )
        elif is_external_neo4j_mode():
            instruction = (
                "NEO4J_MODE=external です。Project → Settings → Advanced → "
                "Environment Variables に NEO4J_URI / NEO4J_USERNAME / "
                "NEO4J_PASSWORD を設定し、Application を再起動してください。"
            )
        else:
            instruction = (
                "Project → Settings → Advanced → Environment Variables に "
                "NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD を設定し、"
                "Application を再起動してください。"
            )
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "NEO4J_NOT_CONFIGURED",
                "message": "Neo4j への接続情報が設定されていません。",
                "instruction": instruction,
            },
        )


def _handle_browse_error(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "NEO4J_BAD_REQUEST", "message": str(exc)},
        ) from exc
    if isinstance(exc, Neo4jSessionError):
        status = 503 if exc.code == "NEO4J_NOT_CONFIGURED" else 502
        raise HTTPException(
            status_code=status,
            detail={"error_code": exc.code, "message": exc.message},
        ) from exc
    raise HTTPException(
        status_code=502,
        detail={"error_code": "NEO4J_QUERY_FAILED", "message": str(exc)},
    ) from exc


@router.get("/schema", response_model=GraphSchemaResponse)
def graph_schema(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
) -> GraphSchemaResponse:
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        return browse.fetch_schema()
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.get("/nodes", response_model=GraphQueryResponse)
def graph_nodes(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    label: Annotated[str, Query(min_length=1, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GraphQueryResponse:
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        return browse.query_by_label(label, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.get("/relationships", response_model=GraphQueryResponse)
def graph_relationships(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    type: Annotated[str, Query(min_length=1, max_length=128, alias="type")],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GraphQueryResponse:
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        return browse.query_by_relationship_type(type, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.get("/properties", response_model=GraphQueryResponse)
def graph_properties(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    key: Annotated[str, Query(min_length=1, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GraphQueryResponse:
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        return browse.query_by_property_key(key, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.get("/neighborhood/{node_id}", response_model=GraphQueryResponse)
def graph_neighborhood(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    node_id: str,
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GraphQueryResponse:
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        return browse.query_neighborhood(node_id, depth=depth, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.get("/entity", response_model=GraphQueryResponse)
def graph_entity(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    hint: Annotated[str, Query(max_length=256)] = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GraphQueryResponse:
    """Agent / RAG 向け: entity_hint から可視化グラフを返す。"""
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        return browse.visualize_entity_hint(hint, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.post("/cypher", response_model=GraphQueryResponse)
def graph_execute_cypher(
    body: CypherRequest,
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
) -> GraphQueryResponse:
    """Read-only Cypher を実行 (Graph タブのクエリ入力用)。"""
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        return browse.execute_read_cypher(body.cypher, limit=body.limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.get("/overview")
def graph_overview(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    q: Annotated[str, Query(max_length=256)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """後方互換: System / Dataset 概要 (旧 GraphView 用)。"""
    _ = user_ctx
    _require_neo4j_or_503()
    try:
        result = browse.visualize_entity_hint(q, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)
    systems: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    for node in result.graph.nodes:
        if "System" in node.labels:
            systems.append(
                {
                    "system_id": node.id,
                    "system_name": node.properties.get("name") or node.caption,
                    "datasets": [],
                    "documents": [],
                }
            )
        elif "Dataset" in node.labels:
            datasets.append(
                {
                    "fq_name": node.properties.get("fq_name") or node.caption,
                    "format": node.properties.get("format"),
                    "source_path": node.properties.get("source_path"),
                }
            )
    return {"systems": systems, "datasets": datasets}
