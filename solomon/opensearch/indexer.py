"""Index Ossie datasets and documents into external OpenSearch."""

from __future__ import annotations

import re
from typing import Any

from solomon.opensearch.client import build_client
from solomon.opensearch.embeddings import try_embed
from solomon.transport.config import OpenSearchConfig
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def build_searchable_text(
    *,
    title: str = "",
    description: str = "",
    dataset: dict[str, Any] | None = None,
    extra_text: str = "",
) -> str:
    """検索用テキストを組み立てる。"""
    parts: list[str] = []
    for value in (title, description, extra_text):
        if value and value.strip():
            parts.append(value.strip())

    ds = dataset or {}
    for key in ("name", "fq_name", "description"):
        value = ds.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for col in ds.get("dimensions", []) + ds.get("measures", []):
        for key in ("name", "description"):
            value = col.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    for sq in ds.get("sample_queries", []):
        question = sq.get("question")
        if isinstance(question, str) and question.strip():
            parts.append(question.strip())
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
    """Neo4j Document ノード相当を OpenSearch にも投入する。"""
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


__all__ = [
    "build_searchable_text",
    "ensure_index",
    "index_document",
    "index_ossie_dataset",
    "index_graph_documents",
]
