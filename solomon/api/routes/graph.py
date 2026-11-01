"""PuppyGraph graph browser API (`/api/graph/*`)."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from solomon.api.auth import require_user_context
from solomon.graph import browse
from solomon.graph.config import get_graph_config
from solomon.graph.models import CypherRequest, GraphQueryResponse, GraphSchemaResponse
from solomon.graph.puppygraph_mode import is_external_puppygraph_mode, is_internal_puppygraph_mode
from solomon.graph.session import GraphSessionError
from solomon.transport.user_context import UserContext

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _require_graph_or_503() -> None:
    if get_graph_config() is not None:
        return

    if is_internal_puppygraph_mode():
        instruction = (
            "PUPPYGRAPH_MODE=internal です。puppygraph-launcher が running になるまで待ち、"
            ".solomon/puppygraph_endpoints.json が作成されたら Solomon Application を再起動。"
            "DNS 不通時は .solomon/deploy.env に PUPPYGRAPH_URI=bolt://host:7687 を設定。"
        )
    elif is_external_puppygraph_mode():
        instruction = (
            "PUPPYGRAPH_MODE=external です。.solomon/deploy.env に "
            "PUPPYGRAPH_URI=bolt://host:7687 を設定。"
            "Iceberg/PostgreSQL catalog と graph schema は PuppyGraph 側で登録済みであること。"
            "認証は PUPPYGRAPH_USERNAME / PUPPYGRAPH_PASSWORD（または secrets.env）。"
            "Solomon Application を再起動してください。"
        )
    else:
        instruction = (
            "PUPPYGRAPH_URI を .solomon/deploy.env に設定し、Application を再起動してください。"
        )

    raise HTTPException(
        status_code=503,
        detail={
            "error_code": "GRAPH_NOT_CONFIGURED",
            "message": "PuppyGraph への接続情報が設定されていません。",
            "instruction": instruction,
        },
    )


def _handle_browse_error(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "GRAPH_BAD_REQUEST", "message": str(exc)},
        ) from exc
    if isinstance(exc, GraphSessionError):
        status = 503 if exc.code == "GRAPH_NOT_CONFIGURED" else 502
        raise HTTPException(
            status_code=status,
            detail={"error_code": exc.code, "message": exc.message},
        ) from exc
    raise HTTPException(
        status_code=502,
        detail={"error_code": "GRAPH_QUERY_FAILED", "message": str(exc)},
    ) from exc


@router.get("/meta")
def graph_meta(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
) -> dict[str, Any]:
    _ = user_ctx
    return {
        "backend": "puppygraph",
        "configured": get_graph_config() is not None,
    }


@router.get("/schema", response_model=GraphSchemaResponse)
def graph_schema(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
) -> GraphSchemaResponse:
    _ = user_ctx
    _require_graph_or_503()
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
    _require_graph_or_503()
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
    _require_graph_or_503()
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
    _require_graph_or_503()
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
    _require_graph_or_503()
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
    _ = user_ctx
    _require_graph_or_503()
    try:
        return browse.visualize_entity_hint(hint, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.post("/cypher", response_model=GraphQueryResponse)
def graph_execute_cypher(
    body: CypherRequest,
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
) -> GraphQueryResponse:
    _ = user_ctx
    _require_graph_or_503()
    try:
        return browse.execute_read_cypher(
            body.cypher, limit=body.limit, params=body.params
        )
    except Exception as exc:  # noqa: BLE001
        _handle_browse_error(exc)


@router.get("/overview")
def graph_overview(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    q: Annotated[str, Query(max_length=256)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    _ = user_ctx
    _require_graph_or_503()
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
