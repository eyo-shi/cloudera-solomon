"""Semantic Search browser API (`/api/search/*`) — read-only dataset catalog."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from solomon.api.auth import require_user_context
from solomon.opensearch.client import build_client, ping
from solomon.opensearch.env import opensearch_username
from solomon.opensearch.indexer import ensure_index
from solomon.opensearch.scope import search_tab_scope
from solomon.opensearch.search import keyword_search
from solomon.transport.config import get_opensearch_config
from solomon.transport.logging import get_logger
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


def _require_opensearch_or_503() -> None:
    if get_opensearch_config() is None:
        from solomon.opensearch.mode import is_internal_opensearch_mode

        if is_internal_opensearch_mode():
            instruction = (
                "OPENSEARCH_MODE=internal です。opensearch-launcher Application "
                "が Running であることを確認し、Solomon Application を再起動してください。"
            )
        else:
            instruction = (
                "OPENSEARCH_MODE=external です。Semantic Search for AWS を Provision し、"
                " OPENSEARCH_CONNECTION_NAME または OPENSEARCH_ENDPOINT を設定してください。"
            )
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "OPENSEARCH_NOT_CONFIGURED",
                "message": "Semantic Search (OpenSearch) への接続情報が設定されていません。",
                "instruction": instruction,
            },
        )


def _list_dataset_documents(config: Any, q: str, limit: int) -> list[dict[str, Any]]:
    client = build_client(config)
    ensure_index(client, config)
    if q.strip():
        return keyword_search(config, q.strip(), top_k=limit)

    body = {
        "size": limit,
        "query": {"match_all": {}},
        "sort": [{"fq_name": {"order": "asc"}}],
    }
    response = client.search(index=config.index_name, body=body)
    hits: list[dict[str, Any]] = []
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        hits.append(
            {
                "document_type": "dataset",
                "index": config.index_name,
                "fq_name": source.get("fq_name"),
                "score": round(float(hit.get("_score", 0.0)), 4),
                "title": source.get("fq_name") or hit.get("_id"),
                "subtitle": (source.get("dataset") or {}).get("description"),
                "dataset": source.get("dataset", {}),
            }
        )
    return hits


@router.get("/diagnostics")
def search_diagnostics(
    _user_ctx: Annotated[UserContext, Depends(require_user_context)],
) -> dict[str, Any]:
    config = get_opensearch_config()
    if config is None:
        return {
            "opensearch_configured": False,
            "password_set": bool((opensearch_username() or "").strip()),
            "username": opensearch_username(),
        }
    return {
        "opensearch_configured": True,
        "username": config.username,
        "password_set": bool(config.password),
        "host": config.host,
        "port": config.port,
        "url_prefix": getattr(config, "url_prefix", "") or "",
        "index": config.index_name,
        "ping_ok": ping(config),
    }


@router.get("/document")
def get_document(
    _user_ctx: Annotated[UserContext, Depends(require_user_context)],
    object_key: Annotated[str, Query(min_length=1, max_length=2048)],
) -> dict[str, Any]:
    """Chat 深リンク用: ``fq_name`` またはキーワードで dataset doc を検索。"""
    config = get_opensearch_config()
    _require_opensearch_or_503()
    assert config is not None
    if not ping(config):
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "OPENSEARCH_CONNECT_FAILED",
                "message": "OpenSearch へ接続できません。",
            },
        )
    docs = keyword_search(config, object_key, top_k=1)
    if not docs:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SEARCH_DOCUMENT_NOT_FOUND",
                "message": f"document not found: {object_key}",
            },
        )
    return {"document": docs[0]}


@router.get("/documents")
def list_documents(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    q: Annotated[str, Query(max_length=512)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """OpenSearch ``solomon-datasets`` インデックスの読み取り専用一覧。"""
    _ = user_ctx
    config = get_opensearch_config()
    _require_opensearch_or_503()
    assert config is not None

    if not ping(config):
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "OPENSEARCH_CONNECT_FAILED",
                "message": "OpenSearch へ接続できません。",
            },
        )

    try:
        documents = _list_dataset_documents(config, q.strip(), limit)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("search.documents_failed", error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "OPENSEARCH_QUERY_FAILED",
                "message": f"Semantic Search query failed: {exc}",
            },
        ) from exc

    return {
        "index": config.index_name,
        "namespace": config.namespace,
        "scope": search_tab_scope(),
        "query": q,
        "documents": documents,
    }
