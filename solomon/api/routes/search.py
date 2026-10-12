"""Semantic Search browser API (`/api/search/*`).

TreePane の Search タブ用。既定は CDE Bronze 取込の ``inspection-*`` インデックス。
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from solomon.api.auth import require_user_context
from solomon.opensearch.client import build_client, ping_inspection
from solomon.opensearch.env import opensearch_env, opensearch_username
from solomon.opensearch.indexer import ensure_index
from solomon.opensearch.inspection_indices import (
    inspection_index_pattern,
    search_inspection_documents,
    search_tab_scope,
)
from solomon.opensearch.search import keyword_search
from solomon.transport.config import get_opensearch_config
from solomon.transport.logging import get_logger
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

ScopeParam = Literal["inspection", "datasets", "both"]


def _require_opensearch_or_503() -> None:
    if get_opensearch_config() is None:
        from solomon.opensearch.mode import is_internal_opensearch_mode

        if is_internal_opensearch_mode():
            instruction = (
                "OPENSEARCH_MODE=internal です。opensearch-launcher Application "
                "が Running であることを確認し、Application Log で "
                ".solomon/opensearch_endpoints.json が書き込まれるまで待ってから "
                "Solomon Application を再起動してください。"
            )
        else:
            instruction = (
                "OPENSEARCH_MODE=external です。Data Hub の Semantic Search "
                "for AWS を Provision し、Project → Settings → Advanced → "
                "Environment Variables に OPENSEARCH_CONNECTION_NAME または "
                "OPENSEARCH_ENDPOINT / OPENSEARCH_NAMESPACE "
                "を設定して Application を再起動してください。"
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


def _resolve_scope(scope: ScopeParam | None) -> ScopeParam:
    if scope is not None:
        return scope
    return search_tab_scope()


@router.get("/diagnostics")
def search_diagnostics(
    _user_ctx: Annotated[UserContext, Depends(require_user_context)],
) -> dict[str, Any]:
    """Search タブ用。Application env の OpenSearch 設定と inspection 到達性（秘密は返さない）。"""
    config = get_opensearch_config()
    if config is None:
        return {
            "opensearch_configured": False,
            "password_set": bool((opensearch_env("PASSWORD") or "").strip()),
            "username": opensearch_username(),
        }
    prefix = getattr(config, "url_prefix", "") or ""
    return {
        "opensearch_configured": True,
        "username": config.username,
        "password_set": bool(config.password),
        "host": config.host,
        "port": config.port,
        "url_prefix": prefix,
        "inspection_index_pattern": inspection_index_pattern(),
        "inspection_ping_ok": ping_inspection(config),
    }


@router.get("/documents")
def list_documents(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    q: Annotated[str, Query(max_length=512)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    scope: Annotated[
        ScopeParam | None,
        Query(description="inspection=Bronze CDE indices (default), datasets=solomon-datasets"),
    ] = None,
) -> dict[str, Any]:
    """OpenSearch ドキュメント一覧。既定は ``inspection-*`` (Bronze 1 ファイル = 1 doc)。"""
    _ = user_ctx
    config = get_opensearch_config()
    _require_opensearch_or_503()
    assert config is not None

    if not ping_inspection(config):
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "OPENSEARCH_CONNECT_FAILED",
                "message": (
                    "OpenSearch（inspection インデックス）へ接続できません。"
                    " OPENSEARCH_USER/PASSWORD と Ranger（inspection-*）を確認してください。"
                ),
            },
        )

    resolved = _resolve_scope(scope)
    query = q.strip()

    try:
        documents: list[dict[str, Any]] = []
        if resolved in ("inspection", "both"):
            documents.extend(
                search_inspection_documents(config, query, limit=limit)
            )
        if resolved in ("datasets", "both"):
            dataset_limit = limit if resolved == "datasets" else max(1, limit // 2)
            documents.extend(_list_dataset_documents(config, query, dataset_limit))
        if resolved == "both":
            documents.sort(
                key=lambda d: (-float(d.get("score") or 0.0), str(d.get("title") or "")),
            )
            documents = documents[:limit]

        index_label = (
            config.index_name
            if resolved == "datasets"
            else inspection_index_pattern()
            if resolved == "inspection"
            else f"{inspection_index_pattern()}, {config.index_name}"
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("search.documents_failed", error=str(exc), scope=resolved)
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "OPENSEARCH_QUERY_FAILED",
                "message": f"Semantic Search query failed: {exc}",
            },
        ) from exc

    return {
        "index": index_label,
        "namespace": config.namespace,
        "scope": resolved,
        "query": q,
        "documents": documents,
    }
