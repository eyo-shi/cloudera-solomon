"""業務文書チャンク検索（データセット用 search.py とは別）。"""

from __future__ import annotations

from typing import Any

from solomon.opensearch.client import build_client
from solomon.opensearch.doc_index import (
    collect_filterable_field_defs,
    doc_type_label_map,
    primary_document_index_def,
)
from solomon.opensearch.embeddings import try_embed
from solomon.transport.config import OpenSearchConfig
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

_SNIPPET_LEN = 300
_TEXT_MAX = 2000
_RRF_K = 60

_FILTERABLE_NAMES: set[str] | None = None


def _filterable_names() -> set[str]:
    global _FILTERABLE_NAMES
    if _FILTERABLE_NAMES is None:
        _FILTERABLE_NAMES = {f["name"] for f in collect_filterable_field_defs()}
    return _FILTERABLE_NAMES


def docs_index_exists(client: Any, config: OpenSearchConfig) -> bool:
    return bool(client.indices.exists(index=config.docs_index_name))


def _parse_filters(
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """OpenSearch bool filter 句と警告、正規化済み filters。"""
    if not filters:
        return [], [], {}
    warnings: list[str] = []
    allowed = _filterable_names()
    clauses: list[dict[str, Any]] = []
    norm: dict[str, Any] = {}

    doc_types = filters.get("doc_type")
    if doc_types is not None:
        if isinstance(doc_types, str):
            doc_types = [doc_types]
        if isinstance(doc_types, list):
            clauses.append({"terms": {"doc_type": doc_types}})
            norm["doc_type"] = doc_types

    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from or date_to:
        rng: dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        clauses.append({"range": {"doc_date": rng}})
        if date_from:
            norm["date_from"] = date_from
        if date_to:
            norm["date_to"] = date_to

    for key, value in filters.items():
        if key in ("doc_type", "date_from", "date_to"):
            continue
        if key not in allowed:
            warnings.append(f"unknown filter key ignored: {key}")
            continue
        if isinstance(value, list):
            clauses.append({"terms": {key: value}})
        else:
            clauses.append({"term": {key: value}})
        norm[key] = value

    return clauses, warnings, norm


def _metadata_from_source(source: dict[str, Any]) -> dict[str, Any]:
    skip = {
        "chunk_id",
        "doc_id",
        "chunk_no",
        "section",
        "doc_type",
        "doc_date",
        "title",
        "text",
        "source_path",
        "embedding",
    }
    meta: dict[str, Any] = {}
    for key in _filterable_names():
        if key in source:
            meta[key] = source[key]
    for key, val in source.items():
        if key not in skip and key not in meta:
            meta[key] = val
    return meta


def _normalize_doc_hit(
    hit: dict[str, Any],
    *,
    match: str,
    label_map: dict[str, str],
    rrf_score: float | None = None,
) -> dict[str, Any]:
    source = hit.get("_source") or hit
    text = str(source.get("text") or "")
    title = str(source.get("title") or source.get("doc_id") or "")
    doc_type = source.get("doc_type")
    score = rrf_score if rrf_score is not None else round(float(hit.get("_score", 0.0)), 4)
    return {
        "chunk_id": source.get("chunk_id"),
        "doc_id": source.get("doc_id"),
        "chunk_no": source.get("chunk_no"),
        "section": source.get("section"),
        "title": title,
        "snippet": text[:_SNIPPET_LEN],
        "text": text[:_TEXT_MAX],
        "doc_type": doc_type,
        "doc_type_label": label_map.get(str(doc_type), str(doc_type or "")),
        "doc_date": source.get("doc_date"),
        "metadata": _metadata_from_source(source),
        "score": score,
        "match": match,
    }


def _keyword_search_docs(
    client: Any,
    config: OpenSearchConfig,
    query: str,
    *,
    top_k: int,
    filter_clauses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bool_q: dict[str, Any] = {
        "must": [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["text^2", "title^1.5"],
                    "type": "best_fields",
                }
            }
        ],
    }
    if filter_clauses:
        bool_q["filter"] = filter_clauses
    body = {"size": top_k, "query": {"bool": bool_q}}
    response = client.search(index=config.docs_index_name, body=body)
    return response.get("hits", {}).get("hits", [])


def _vector_search_docs(
    client: Any,
    config: OpenSearchConfig,
    query: str,
    *,
    top_k: int,
    filter_clauses: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    embedding = try_embed(query, purpose="query")
    if embedding is None:
        return [], "embedding unavailable"
    knn: dict[str, Any] = {
        "vector": embedding,
        "k": top_k,
    }
    if filter_clauses:
        knn["filter"] = {"bool": {"filter": filter_clauses}}
    body = {
        "size": top_k,
        "query": {"knn": {"embedding": knn}},
    }
    try:
        response = client.search(index=config.docs_index_name, body=body)
        return response.get("hits", {}).get("hits", []), None
    except Exception as exc:  # noqa: BLE001
        _logger.warning("opensearch.docs_vector_failed", error=str(exc))
        expanded_k = top_k * 10
        knn_fallback = {"vector": embedding, "k": expanded_k}
        body2 = {"size": expanded_k, "query": {"knn": {"embedding": knn_fallback}}}
        try:
            response = client.search(index=config.docs_index_name, body=body2)
        except Exception as exc2:  # noqa: BLE001
            return [], f"{exc}; fallback: {exc2}"
        hits = response.get("hits", {}).get("hits", [])
        if filter_clauses:
            filtered = []
            for h in hits:
                src = h.get("_source", {})
                ok = True
                for clause in filter_clauses:
                    if "term" in clause:
                        for field, val in clause["term"].items():
                            if src.get(field) != val:
                                ok = False
                    if "terms" in clause:
                        for field, vals in clause["terms"].items():
                            if src.get(field) not in vals:
                                ok = False
                if ok:
                    filtered.append(h)
            hits = filtered[:top_k]
        return hits, str(exc)


def _rrf_merge(
    kw_hits: list[dict[str, Any]],
    vec_hits: list[dict[str, Any]],
    *,
    top_k: int,
    label_map: dict[str, str],
    vector_error: str | None,
) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, Any]] = {}
    match_kind: dict[str, set[str]] = {}

    for rank, hit in enumerate(kw_hits):
        src = hit.get("_source", {})
        cid = str(src.get("chunk_id") or hit.get("_id") or rank)
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        payloads[cid] = hit
        match_kind.setdefault(cid, set()).add("keyword")

    for rank, hit in enumerate(vec_hits):
        src = hit.get("_source", {})
        cid = str(src.get("chunk_id") or hit.get("_id") or f"v{rank}")
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        if cid not in payloads:
            payloads[cid] = hit
        match_kind.setdefault(cid, set()).add("vector")

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    out: list[dict[str, Any]] = []
    for cid, rrf in ranked:
        kinds = match_kind.get(cid, set())
        match = "both" if len(kinds) > 1 else (next(iter(kinds)) if kinds else "keyword")
        row = _normalize_doc_hit(
            payloads[cid],
            match=match,
            label_map=label_map,
            rrf_score=round(rrf, 6),
        )
        if vector_error:
            row["vector_error"] = vector_error
        out.append(row)
    return out


_ORIGINAL_QUERY_RRF_WEIGHT = 1.0
_VARIANT_QUERY_RRF_WEIGHT = 0.7


def merge_expanded_document_results(
    ranked_lists: list[tuple[str, float, list[dict[str, Any]]]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """複数クエリの結果を chunk_id キー RRF（重み付き）で統合。"""
    scores: dict[str, float] = {}
    best_doc: dict[str, dict[str, Any]] = {}
    matched: dict[str, list[str]] = {}

    for query_text, weight, documents in ranked_lists:
        for rank, doc in enumerate(documents):
            cid = str(doc.get("chunk_id") or doc.get("doc_id") or f"r{rank}")
            scores[cid] = scores.get(cid, 0.0) + weight * (
                1.0 / (_RRF_K + rank + 1)
            )
            if cid not in best_doc:
                best_doc[cid] = doc
            matched.setdefault(cid, [])
            if query_text not in matched[cid]:
                matched[cid].append(query_text)

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    out: list[dict[str, Any]] = []
    for cid, sc in ordered:
        row = dict(best_doc[cid])
        row["score"] = round(sc, 6)
        row["matched_queries"] = matched.get(cid, [])
        out.append(row)
    return out


def search_documents_with_expansion(
    config: OpenSearchConfig,
    query: str,
    *,
    top_k: int = 8,
    filters: dict[str, Any] | None = None,
    mode: str = "hybrid",
    expand: bool | None = None,
    max_variants: int | None = None,
    group_by_doc: bool = False,
) -> dict[str, Any]:
    """単一または言い換え複数クエリで検索し RRF 統合。"""
    from solomon.opensearch.query_expansion import (
        doc_search_expansion_enabled,
        doc_search_max_variants,
        expand_query,
    )

    use_expand = doc_search_expansion_enabled() if expand is None else expand
    variants: list[str] = []
    if use_expand and mode != "off":
        variants = expand_query(
            query,
            max_variants=max_variants or doc_search_max_variants(),
        )

    if not variants:
        result = search_documents(
            config,
            query,
            top_k=top_k,
            filters=filters,
            mode=mode,
            group_by_doc=group_by_doc,
        )
        if result.get("status") == "ok":
            for doc in result.get("documents") or []:
                doc["matched_queries"] = [query]
            result["expanded_queries"] = []
        return result

    ranked: list[tuple[str, float, list[dict[str, Any]]]] = []
    warnings: list[str] = []
    for q_text, weight in [(query, _ORIGINAL_QUERY_RRF_WEIGHT)] + [
        (v, _VARIANT_QUERY_RRF_WEIGHT) for v in variants
    ]:
        partial = search_documents(
            config,
            q_text,
            top_k=top_k,
            filters=filters,
            mode=mode,
            group_by_doc=False,
        )
        if partial.get("status") == "error":
            return partial
        warnings.extend(partial.get("warnings") or [])
        ranked.append((q_text, weight, partial.get("documents") or []))

    documents = merge_expanded_document_results(ranked, top_k=top_k)
    if group_by_doc:
        by_doc: dict[str, dict[str, Any]] = {}
        for doc in documents:
            did = str(doc.get("doc_id") or "")
            prev = by_doc.get(did)
            if prev is None or float(doc.get("score") or 0) > float(prev.get("score") or 0):
                by_doc[did] = doc
        documents = sorted(
            by_doc.values(), key=lambda d: float(d.get("score") or 0), reverse=True
        )[:top_k]

    return {
        "status": "ok",
        "query": query,
        "index": config.docs_index_name,
        "documents": documents,
        "warnings": list(dict.fromkeys(warnings)),
        "count": len(documents),
        "expanded_queries": variants,
    }


def search_documents(
    config: OpenSearchConfig,
    query: str,
    *,
    top_k: int = 8,
    filters: dict[str, Any] | None = None,
    mode: str = "hybrid",
    group_by_doc: bool = False,
) -> dict[str, Any]:
    """文書チャンク検索。戻り値に ``documents`` と ``warnings``。"""
    client = build_client(config)
    if not docs_index_exists(client, config):
        return {
            "status": "error",
            "error_code": "OPENSEARCH_DOCS_INDEX_MISSING",
            "message": (
                f"Document index {config.docs_index_name!r} does not exist. "
                "Create it with ensure_docs_index / bulk_index_doc_chunks."
            ),
            "documents": [],
            "warnings": [],
        }

    filter_clauses, warnings, _norm = _parse_filters(filters)
    label_map = doc_type_label_map(primary_document_index_def())
    mode_l = (mode or "hybrid").lower()

    kw_hits: list[dict[str, Any]] = []
    vec_hits: list[dict[str, Any]] = []
    vector_error: str | None = None

    if mode_l in ("keyword", "hybrid"):
        kw_hits = _keyword_search_docs(
            client, config, query, top_k=top_k, filter_clauses=filter_clauses
        )
    if mode_l in ("vector", "hybrid"):
        vec_hits, vector_error = _vector_search_docs(
            client, config, query, top_k=top_k, filter_clauses=filter_clauses
        )

    if mode_l == "keyword":
        documents = [
            _normalize_doc_hit(h, match="keyword", label_map=label_map)
            for h in kw_hits[:top_k]
        ]
    elif mode_l == "vector":
        documents = []
        for h in vec_hits[:top_k]:
            row = _normalize_doc_hit(h, match="vector", label_map=label_map)
            if vector_error:
                row["vector_error"] = vector_error
            documents.append(row)
    elif not vec_hits and vector_error:
        documents = [
            _normalize_doc_hit(h, match="keyword", label_map=label_map)
            for h in kw_hits[:top_k]
        ]
        if documents and vector_error:
            documents[0]["vector_error"] = vector_error
    else:
        documents = _rrf_merge(
            kw_hits,
            vec_hits,
            top_k=top_k,
            label_map=label_map,
            vector_error=vector_error,
        )

    if group_by_doc:
        by_doc: dict[str, dict[str, Any]] = {}
        for doc in documents:
            did = str(doc.get("doc_id") or "")
            prev = by_doc.get(did)
            if prev is None or float(doc.get("score") or 0) > float(prev.get("score") or 0):
                by_doc[did] = doc
        documents = list(by_doc.values())
        documents.sort(key=lambda d: float(d.get("score") or 0), reverse=True)
        documents = documents[:top_k]

    return {
        "status": "ok",
        "query": query,
        "index": config.docs_index_name,
        "documents": documents,
        "warnings": warnings,
        "count": len(documents),
    }


def get_document_chunks(config: OpenSearchConfig, doc_id: str) -> list[dict[str, Any]]:
    client = build_client(config)
    if not docs_index_exists(client, config):
        return []
    body = {
        "size": 500,
        "query": {"term": {"doc_id": doc_id}},
        "sort": [{"chunk_no": {"order": "asc"}}],
    }
    response = client.search(index=config.docs_index_name, body=body)
    label_map = doc_type_label_map(primary_document_index_def())
    out: list[dict[str, Any]] = []
    for hit in response.get("hits", {}).get("hits", []):
        out.append(_normalize_doc_hit(hit, match="keyword", label_map=label_map))
    return out


def doc_type_counts(config: OpenSearchConfig) -> dict[str, int]:
    client = build_client(config)
    if not docs_index_exists(client, config):
        return {}
    body = {
        "size": 0,
        "aggs": {"types": {"terms": {"field": "doc_type", "size": 50}}},
    }
    response = client.search(index=config.docs_index_name, body=body)
    buckets = (
        response.get("aggregations", {}).get("types", {}).get("buckets", [])
    )
    return {str(b.get("key")): int(b.get("doc_count", 0)) for b in buckets}


__all__ = [
    "search_documents",
    "search_documents_with_expansion",
    "merge_expanded_document_results",
    "get_document_chunks",
    "doc_type_counts",
    "docs_index_exists",
]
