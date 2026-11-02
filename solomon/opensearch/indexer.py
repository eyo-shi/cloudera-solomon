"""Index Ossie datasets and documents into external OpenSearch."""

from __future__ import annotations

from typing import Any

from solomon.opensearch.client import build_client
from solomon.opensearch.embeddings import try_embed
from solomon.semantic.models import AIContext
from solomon.semantic.search import tokenize
from solomon.transport.config import OpenSearchConfig
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)


def _ai_text(ctx: AIContext | str | dict[str, Any] | None) -> list[str]:
    if ctx is None:
        return []
    if isinstance(ctx, str):
        return [ctx]
    if isinstance(ctx, dict):
        parts: list[str] = []
        if isinstance(ctx.get("instructions"), str):
            parts.append(ctx["instructions"])
        for s in ctx.get("synonyms") or []:
            if isinstance(s, str):
                parts.append(s)
        for ex in ctx.get("examples") or []:
            if isinstance(ex, str):
                parts.append(ex)
        return parts
    parts = []
    if ctx.instructions:
        parts.append(ctx.instructions)
    parts.extend(ctx.synonyms or [])
    parts.extend(ctx.examples or [])
    return parts


def _dataset_search_parts(ds: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("name", "description"):
        v = ds.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    parts.extend(_ai_text(ds.get("ai_context")))
    for field in ds.get("fields") or []:
        if not isinstance(field, dict):
            continue
        for key in ("name", "label", "description"):
            v = field.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        parts.extend(_ai_text(field.get("ai_context")))
    for metric in ds.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        for key in ("name", "description"):
            v = metric.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    return parts


def build_searchable_text(
    *,
    title: str = "",
    description: str = "",
    dataset: dict[str, Any] | None = None,
    extra_text: str = "",
) -> str:
    """検索用テキストを組み立てる (本家 Ossie フィールド対象)。"""
    parts: list[str] = []
    for value in (title, description, extra_text):
        if value and value.strip():
            parts.append(value.strip())

    ds = dataset or {}
    parts.extend(_dataset_search_parts(ds))
    # トークン化で正規化した語も混ぜる (日本語対応)
    blob = " ".join(parts)
    tokens = tokenize(blob)
    if tokens:
        parts.append(" ".join(tokens))
    return " ".join(parts)


def ensure_index(client: Any, config: OpenSearchConfig) -> None:
    """k-NN 対応インデックスを作成 (存在しなければ)。"""
    if client.indices.exists(index=config.index_name):
        return
    body = {
        "settings": {"index.knn": True},
        "mappings": {
            "properties": {
                "doc_id": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "fq_name": {"type": "keyword"},
                "system_id": {"type": "keyword"},
                "title": {"type": "text"},
                "description": {"type": "text"},
                "text": {"type": "text"},
                "path": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": config.embedding_dim,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                    },
                },
                "dataset": {"type": "object", "enabled": False},
            }
        },
    }
    client.indices.create(index=config.index_name, body=body)
    _logger.info("opensearch.index_created", index=config.index_name)


def index_document(
    config: OpenSearchConfig,
    *,
    doc_id: str,
    doc_type: str,
    title: str,
    text: str,
    path: str = "",
    fq_name: str | None = None,
    system_id: str | None = None,
    description: str = "",
    dataset: dict[str, Any] | None = None,
    with_embedding: bool = True,
) -> dict[str, Any]:
    """1 ドキュメントを OpenSearch に upsert する。"""
    client = build_client(config)
    ensure_index(client, config)

    body: dict[str, Any] = {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "title": title,
        "description": description,
        "text": text,
        "path": path,
        "fq_name": fq_name,
        "system_id": system_id,
        "dataset": dataset,
    }

    if with_embedding and text.strip():
        embedding = try_embed(text)
        if embedding is not None:
            body["embedding"] = embedding

    client.index(index=config.index_name, id=doc_id, body=body, refresh=True)
    _logger.info("opensearch.indexed", doc_id=doc_id, index=config.index_name)
    return {
        "doc_id": doc_id,
        "index": config.index_name,
        "has_embedding": "embedding" in body,
    }


def index_ossie_dataset(
    config: OpenSearchConfig,
    fq_name: str,
    dataset: dict[str, Any],
    *,
    system_id: str | None = None,
    with_embedding: bool = True,
) -> dict[str, Any]:
    """Ossie dataset を OpenSearch にインデックスする。"""
    text = build_searchable_text(
        title=dataset.get("name", fq_name),
        description=str(dataset.get("description", "")),
        dataset=dataset,
    )
    return index_document(
        config,
        doc_id=fq_name,
        doc_type="dataset",
        title=str(dataset.get("name", fq_name.rsplit(".", 1)[-1])),
        description=str(dataset.get("description", "")),
        text=text,
        path=f"ossie://{fq_name}",
        fq_name=fq_name,
        system_id=system_id,
        dataset=dataset,
        with_embedding=with_embedding,
    )


def index_graph_documents(
    config: OpenSearchConfig,
    *,
    system_id: str,
    dataset_id: str,
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Graph Document ノード相当を OpenSearch にも投入する。"""
    results: list[dict[str, Any]] = []
    for doc in documents:
        doc_id = str(doc.get("id", ""))
        if not doc_id:
            continue
        text = build_searchable_text(
            title=str(doc.get("title", "")),
            description=str(doc.get("content_preview", "")),
            extra_text=f"system={system_id} dataset={dataset_id} type={doc.get('doc_type')}",
        )
        results.append(
            index_document(
                config,
                doc_id=doc_id,
                doc_type=str(doc.get("doc_type", "reference")),
                title=str(doc.get("title", doc_id)),
                description=str(doc.get("content_preview", "")),
                text=text,
                path=str(doc.get("path", "")),
                fq_name=dataset_id,
                system_id=system_id,
                with_embedding=True,
            )
        )
    return results


def ensure_docs_index(client: Any, config: OpenSearchConfig, doc_index_def: dict | None = None) -> str:
    """文書インデックスを作成（:mod:`docs_indexer` への委譲）。"""
    from solomon.opensearch.docs_indexer import ensure_docs_index as _ensure

    return _ensure(client, config, doc_index_def)


__all__ = [
    "build_searchable_text",
    "ensure_index",
    "ensure_docs_index",
    "index_document",
    "index_ossie_dataset",
    "index_graph_documents",
]