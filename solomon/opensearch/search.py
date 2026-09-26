"""Keyword and vector search against external OpenSearch."""

from __future__ import annotations

from typing import Any

from solomon.opensearch.client import build_client
from solomon.opensearch.embeddings import try_embed
from solomon.transport.config import OpenSearchConfig


def _normalize_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits:
        source = hit.get("_source", {})
        out.append(
            {
                "fq_name": source.get("fq_name"),
                "score": round(float(hit.get("_score", 0.0)), 4),
                "dataset": source.get("dataset", {}),
            }
        )
    return out


def keyword_search(
    config: OpenSearchConfig,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """BM25 match クエリで外部 OpenSearch を検索する。"""
    client = build_client(config)
    body = {
        "size": top_k,
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["text^2", "name", "description", "fq_name"],
                "type": "best_fields",
            }
        },
    }
    response = client.search(index=config.index_name, body=body)
    hits = response.get("hits", {}).get("hits", [])
    return _normalize_hits(hits)


def vector_search(
    config: OpenSearchConfig,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """k-NN ベクトル検索で外部 OpenSearch を検索する。"""
    embedding = try_embed(query)
    if embedding is None:
        return []

    client = build_client(config)
    body = {
        "size": top_k,
        "query": {
            "knn": {
                "embedding": {
                    "vector": embedding,
                    "k": top_k,
                }
            }
        },
    }
    response = client.search(index=config.index_name, body=body)
    hits = response.get("hits", {}).get("hits", [])
    return _normalize_hits(hits)


def hybrid_search(
    config: OpenSearchConfig,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Keyword BM25 + k-NN を Reciprocal Rank Fusion で統合する Hybrid Search。"""
    kw_hits = keyword_search(config, query, top_k=top_k)
    vec_hits: list[dict[str, Any]] = []
    try:
        vec_hits = vector_search(config, query, top_k=top_k)
    except Exception:  # noqa: BLE001
        vec_hits = []

    if not vec_hits:
        return kw_hits

    # RRF: score = sum(1 / (k + rank)), k=60
    rrf_k = 60
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, Any]] = {}

    for rank, hit in enumerate(kw_hits):
        fq = hit.get("fq_name") or str(rank)
        scores[fq] = scores.get(fq, 0.0) + 1.0 / (rrf_k + rank + 1)
        payloads[fq] = hit

    for rank, hit in enumerate(vec_hits):
        fq = hit.get("fq_name") or f"vec_{rank}"
        scores[fq] = scores.get(fq, 0.0) + 1.0 / (rrf_k + rank + 1)
        if fq not in payloads:
            payloads[fq] = hit
        else:
            payloads[fq]["score"] = round(scores[fq], 4)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    out: list[dict[str, Any]] = []
    for fq, score in ranked:
        item = dict(payloads[fq])
        item["score"] = round(score, 4)
        item["search_mode"] = "hybrid"
        out.append(item)
    return out


__all__ = ["keyword_search", "vector_search", "hybrid_search"]
