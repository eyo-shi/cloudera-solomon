"""Semantic Search browser API (`/api/search/*`) — read-only dataset catalog."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from solomon.api.auth import require_user_context
from solomon.opensearch.client import build_client, ping
from solomon.opensearch.env import opensearch_username
from solomon.opensearch.indexer import ensure_index
from solomon.opensearch.scope import search_tab_scope
from solomon.opensearch.docs_search import get_document_chunks, search_documents
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


def _search_business_documents(
    config: Any, q: str, limit: int, *, strict: bool
) -> list[dict[str, Any]]:
    """業務文書チャンクを検索し、文書単位 (最高スコアのチャンク) で返す。

    ``strict=False`` (scope=both) では文書インデックスが無くても空で返す。
    """
    result = search_documents(config, q, top_k=limit, group_by_doc=True)
    if result.get("status") == "error":
        missing = result.get("error_code") == "OPENSEARCH_DOCS_INDEX_MISSING"
        if not strict and missing:
            return []
        raise HTTPException(
            status_code=404 if missing else 502,
            detail={
                "error_code": result.get("error_code"),
                "message": result.get("message"),
            },
        )
    return [
        {**doc, "document_type": "doc", "index": config.docs_index_name}
        for doc in result.get("documents") or []
    ]


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
    object_key: Annotated[str | None, Query(max_length=2048)] = None,
    doc_id: Annotated[str | None, Query(max_length=512)] = None,
) -> dict[str, Any]:
    """Chat 深リンク用: ``object_key``（dataset）または ``doc_id``（業務文書）。"""
    if not object_key and not doc_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": "object_key or doc_id is required",
            },
        )
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
    if doc_id:
        from solomon.opensearch.document_payload import business_document_entry

        entry = business_document_entry(config, doc_id.strip())
        if not entry:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "SEARCH_DOCUMENT_NOT_FOUND",
                    "message": f"document not found: {doc_id}",
                },
            )
        return {"document": entry}

    assert object_key is not None
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
    scope: Annotated[str, Query(max_length=16)] = "",
) -> dict[str, Any]:
    """OpenSearch 読み取り専用一覧（datasets / docs）。"""
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

    effective_scope = (scope or search_tab_scope()).lower()
    if effective_scope not in ("datasets", "docs", "both"):
        effective_scope = search_tab_scope()

    query = q.strip()
    # documents は scope によらず常に配列 (Search タブは配列として描画する)。
    # 業務文書は検索語が必要なので、空の q では datasets だけ (docs は空) を返す
    try:
        if effective_scope == "docs":
            documents = (
                _search_business_documents(config, query, limit, strict=True)
                if query
                else []
            )
            index_name = config.docs_index_name
        elif effective_scope == "both" and query:
            documents = _list_dataset_documents(config, query, limit)
            documents += _search_business_documents(config, query, limit, strict=False)
            index_name = f"{config.index_name},{config.docs_index_name}"
        else:
            documents = _list_dataset_documents(config, q.strip(), limit)
            index_name = config.index_name
    except HTTPException:
        raise
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
        "index": index_name,
        "namespace": config.namespace,
        "scope": effective_scope,
        "query": q,
        "documents": documents,
    }


@router.get("/doc")
def get_business_document(
    _user_ctx: Annotated[UserContext, Depends(require_user_context)],
    doc_id: Annotated[str, Query(min_length=1, max_length=512)],
) -> dict[str, Any]:
    """文書全体（チャンク連結）。"""
    config = get_opensearch_config()
    _require_opensearch_or_503()
    assert config is not None
    chunks = get_document_chunks(config, doc_id)
    if not chunks:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SEARCH_DOCUMENT_NOT_FOUND",
                "message": f"document not found: {doc_id}",
            },
        )
    meta = chunks[0]
    full_text = "\n\n".join(str(c.get("text") or "") for c in chunks)
    return {
        "doc_id": doc_id,
        "title": meta.get("title"),
        "doc_type": meta.get("doc_type"),
        "doc_type_label": meta.get("doc_type_label"),
        "metadata": meta.get("metadata"),
        "chunk_count": len(chunks),
        "text": full_text[:50000],
        "chunks": chunks,
    }
