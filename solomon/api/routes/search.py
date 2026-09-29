"""Semantic Search browser API (`/api/search/*`).

TreePane の Search タブ用。外部 OpenSearch (Cloudera Semantic Search) を参照する。
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from solomon.api.auth import require_user_context
from solomon.opensearch.client import build_client, ping
from solomon.opensearch.search import keyword_search
from solomon.transport.config import get_opensearch_config
from solomon.transport.user_context import UserContext

router = APIRouter(prefix="/api/search", tags=["search"])


def _require_opensearch_or_503() -> None:
    if get_opensearch_config() is None:
        from solomon.opensearch.mode import is_cml_opensearch_mode

        if is_cml_opensearch_mode():
            instruction = (
                "SOLOMON_OPENSEARCH_MODE=cml です。opensearch-launcher Application "
                "が Running であることを確認し、Application Log で "
                ".solomon/opensearch_endpoints.json が書き込まれるまで待ってから "
                "Solomon Application を再起動してください。"
            )
        else:
            instruction = (
                "SOLOMON_OPENSEARCH_MODE=datahub です。Data Hub の Semantic Search "
                "for AWS を Provision し、Project → Settings → Advanced → "
                "Environment Variables に SOLOMON_OPENSEARCH_CONNECTION_NAME または "
                "SOLOMON_OPENSEARCH_ENDPOINT / SOLOMON_OPENSEARCH_NAMESPACE "
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


@router.get("/documents")
def list_documents(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    q: Annotated[str, Query(max_length=512)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """インデックス済みドキュメントをキーワード検索 (空なら match_all)。"""
    _ = user_ctx
    config = get_opensearch_config()
    _require_opensearch_or_503()
    assert config is not None

    if not ping(config):
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "OPENSEARCH_CONNECT_FAILED",
                "message": "Semantic Search クラスタへ接続できません。",
            },
        )

    try:
        if q.strip():
            hits = keyword_search(config, q.strip(), top_k=limit)
        else:
            client = build_client(config)
            body = {
                "size": limit,
                "query": {"match_all": {}},
                "sort": [{"fq_name": {"order": "asc"}}],
            }
            response = client.search(index=config.index_name, body=body)
            raw_hits = response.get("hits", {}).get("hits", [])
            hits = []
            for hit in raw_hits:
                source = hit.get("_source", {})
                hits.append(
                    {
                        "fq_name": source.get("fq_name"),
                        "score": round(float(hit.get("_score", 0.0)), 4),
                        "dataset": source.get("dataset", {}),
                    }
                )
    except Exception as exc:  # noqa: BLE001
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
        "query": q,
        "documents": hits,
    }
