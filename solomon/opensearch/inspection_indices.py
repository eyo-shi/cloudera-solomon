"""CDE Spark が投入する ``inspection-*`` インデックス（Bronze 1 ファイル = 1 doc）。"""
from __future__ import annotations

import os
from typing import Any, Literal

from solomon.opensearch.client import build_client
from solomon.opensearch.env import opensearch_env
from solomon.transport.config import OpenSearchConfig, get_opensearch_config
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

SearchScope = Literal["inspection", "datasets", "both"]

_FORMAT_SUFFIXES = (
    "vb",
    "j5_main_id",
    "kanken",
    "j5_shukken_id",
)


def inspection_index_prefix() -> str:
    raw = (
        os.environ.get("OPENSEARCH_INSPECTION_INDEX_PREFIX")
        or os.environ.get("OPENSEARCH_INDEX_PREFIX")
        or "inspection"
    ).strip()
    return raw or "inspection"


def inspection_index_name(format_suffix: str) -> str:
    return f"{inspection_index_prefix()}-{format_suffix}"


def inspection_index_pattern() -> str:
    return f"{inspection_index_prefix()}-*"


def inspection_index_list_csv() -> str:
    return ",".join(inspection_index_name(s) for s in _FORMAT_SUFFIXES)


def search_tab_scope() -> SearchScope:
    raw = (opensearch_env("SEARCH_SCOPE") or "inspection").strip().lower()
    if raw in ("inspection", "datasets", "both"):
        return raw  # type: ignore[return-value]
    return "inspection"


def _payload_summary(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("_truncated"):
        return f"payload truncated ({payload.get('original_chars')} chars)"
    parts: list[str] = []
    for key in (
        "kiban",
        "at_kiban",
        "hinban",
        "customer_hinban",
        "judge",
        "test_no",
        "vb_machine_no",
        "passed_at",
    ):
        val = payload.get(key)
        if val not in (None, ""):
            parts.append(f"{key}={val}")
    return " · ".join(parts[:5]) if parts else None


def normalize_inspection_hit(hit: dict[str, Any]) -> dict[str, Any]:
    src = hit.get("_source") or {}
    object_key = src.get("object_key") or ""
    payload = src.get("payload")
    name = object_key.rsplit("/", 1)[-1] if object_key else str(hit.get("_id") or "document")
    trace_id = src.get("trace_id") or ""
    vb_machine_no = src.get("vb_machine_no") or ""
    fmt = src.get("format") or ""
    meta_bits = [x for x in (fmt, trace_id, vb_machine_no) if x]
    subtitle = _payload_summary(payload) or (" · ".join(meta_bits) if meta_bits else None)
    return {
        "document_type": "inspection",
        "index": hit.get("_index"),
        "score": round(float(hit.get("_score", 0.0)), 4),
        "object_key": object_key or None,
        "format": fmt or None,
        "trace_id": trace_id or None,
        "vb_machine_no": vb_machine_no or None,
        "title": name,
        "subtitle": subtitle,
        "payload": payload,
    }


def _inspection_search_body(query: str, *, size: int) -> dict[str, Any]:
    q = query.strip()
    if not q:
        # 複数 index 横断では sort フィールド差分で 400 になりやすいため match_all は sort なし
        return {
            "size": size,
            "query": {"match_all": {}},
        }
    return {
        "size": size,
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": q,
                            "fields": [
                                "trace_id^5",
                                "object_key^4",
                                "vb_machine_no^3",
                                "format^2",
                                "payload.kiban^3",
                                "payload.at_kiban^3",
                                "payload.hinban^2",
                                "payload.customer_hinban^2",
                                "payload.judge",
                                "payload.test_no",
                                "payload.title_line",
                            ],
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                        }
                    },
                    {
                        "simple_query_string": {
                            "query": q,
                            "fields": ["object_key", "trace_id", "vb_machine_no"],
                            "default_operator": "and",
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        },
    }


_OS_SEARCH_PARAMS = {"ignore_unavailable": "true", "allow_no_indices": "true"}


def search_inspection_documents(
    config: OpenSearchConfig,
    query: str = "",
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search タブ向け: ``inspection-*`` をキーワード検索 (空なら match_all)。"""
    client = build_client(config)
    body = _inspection_search_body(query, size=limit)
    index_candidates = (
        inspection_index_pattern(),
        inspection_index_list_csv(),
    )
    last_exc: Exception | None = None
    for index in index_candidates:
        try:
            response = client.search(
                index=index,
                body=body,
                params=_OS_SEARCH_PARAMS,
            )
            hits = response.get("hits", {}).get("hits", [])
            return [normalize_inspection_hit(h) for h in hits]
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _logger.debug(
                "opensearch.inspection_search_failed",
                index=index,
                error=str(exc),
            )
    if last_exc is not None:
        raise last_exc
    return []


def search_documents_by_trace_id(
    trace_id: str,
    *,
    config: OpenSearchConfig | None = None,
    size: int = 20,
) -> list[dict[str, Any]]:
    """``trace_id``（KIBAN）に一致する Bronze ファイル doc を検索する。"""
    cfg = config or get_opensearch_config()
    if cfg is None:
        return []

    client = build_client(cfg)
    body = {
        "size": size,
        "query": {
            "bool": {
                "should": [
                    {"term": {"trace_id.keyword": trace_id}},
                    {"term": {"trace_id": trace_id}},
                    {"match_phrase": {"trace_id": trace_id}},
                ],
                "minimum_should_match": 1,
            }
        },
    }
    try:
        response = client.search(
            index=inspection_index_pattern(),
            body=body,
            params=_OS_SEARCH_PARAMS,
        )
    except Exception:  # noqa: BLE001
        return []

    return [normalize_inspection_hit(h) for h in response.get("hits", {}).get("hits", [])]


def summarize_trace_documents(docs: list[dict[str, Any]]) -> str | None:
    if not docs:
        return None
    by_format: dict[str, int] = {}
    for doc in docs:
        fmt = str(doc.get("format") or "unknown")
        by_format[fmt] = by_format.get(fmt, 0) + 1
    fmt_part = ", ".join(f"{k}={v}" for k, v in sorted(by_format.items()))
    return f"OpenSearch: trace_id に一致する Bronze doc {len(docs)} 件（{fmt_part}）。"


__all__ = [
    "SearchScope",
    "inspection_index_prefix",
    "inspection_index_name",
    "inspection_index_pattern",
    "inspection_index_list_csv",
    "normalize_inspection_hit",
    "search_inspection_documents",
    "search_tab_scope",
    "search_documents_by_trace_id",
    "summarize_trace_documents",
]
