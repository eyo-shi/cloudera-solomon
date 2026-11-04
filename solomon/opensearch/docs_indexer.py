"""業務文書チャンクの投入（デモローダー用。Solomon 本体からは呼ばない）。"""

from __future__ import annotations

from typing import Any

from solomon.opensearch.client import build_client
from solomon.opensearch.doc_index import primary_document_index_def
from solomon.opensearch.docs_mapping import KnnEngine, build_docs_mapping
from solomon.opensearch.embeddings import try_embed_batch
from solomon.transport.config import OpenSearchConfig
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)


def ensure_docs_index(
    client: Any,
    config: OpenSearchConfig,
    doc_index_def: dict[str, Any] | None = None,
    *,
    knn_engine: KnnEngine = "lucene",
) -> str:
    """文書インデックスを作成（存在しなければ）。使用した knn engine をログ。"""
    index_name = config.docs_index_name or config.namespace + "-docs"
    if client.indices.exists(index=index_name):
        return knn_engine
    body = build_docs_mapping(
        doc_index_def or primary_document_index_def(),
        analyzer=config.docs_analyzer,  # type: ignore[arg-type]
        embedding_dim=config.embedding_dim,
        knn_engine=knn_engine,
    )
    try:
        client.indices.create(index=index_name, body=body)
        _logger.info(
            "opensearch.docs_index_created",
            index=index_name,
            knn_engine=knn_engine,
            analyzer=config.docs_analyzer,
        )
        return knn_engine
    except Exception as exc:  # noqa: BLE001
        if knn_engine == "lucene":
            _logger.warning("opensearch.docs_index_lucene_failed", error=str(exc))
            return ensure_docs_index(
                client,
                config,
                doc_index_def,
                knn_engine="faiss",
            )
        if knn_engine == "faiss":
            _logger.warning("opensearch.docs_index_faiss_failed", error=str(exc))
            client.indices.create(
                index=index_name,
                body=build_docs_mapping(
                    doc_index_def or primary_document_index_def(),
                    analyzer=config.docs_analyzer,  # type: ignore[arg-type]
                    embedding_dim=config.embedding_dim,
                    knn_engine="nmslib_post_filter",
                ),
            )
            _logger.info(
                "opensearch.docs_index_created",
                index=index_name,
                knn_engine="nmslib_post_filter",
            )
            return "nmslib_post_filter"
        raise


def bulk_index_doc_chunks(
    config: OpenSearchConfig,
    chunks: list[dict[str, Any]],
    *,
    batch_size: int = 200,
    with_embedding: bool = True,
    embed_max_chars: int = 2000,
    ensure_index: bool = True,
) -> dict[str, Any]:
    """``opensearch.helpers.bulk`` でチャンクを投入。"""
    from opensearchpy.helpers import bulk

    client = build_client(config)
    index_name = config.docs_index_name
    if ensure_index:
        ensure_docs_index(client, config)

    indexed = 0
    errors: list[str] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        texts: list[str] = []
        for ch in batch:
            t = str(ch.get("text") or "")[:embed_max_chars]
            texts.append(t)
        embeddings: list[list[float] | None] = [None] * len(batch)
        if with_embedding:
            embeddings = try_embed_batch(texts, purpose="passage")

        actions = []
        for ch, emb in zip(batch, embeddings, strict=True):
            chunk_id = ch.get("chunk_id")
            if not chunk_id:
                errors.append("chunk missing chunk_id")
                continue
            body = dict(ch)
            body.pop("_id", None)
            if emb is not None:
                body["embedding"] = emb
            actions.append(
                {
                    "_op_type": "index",
                    "_index": index_name,
                    "_id": str(chunk_id),
                    "_source": body,
                }
            )
        if not actions:
            continue
        ok_count, bulk_errors = bulk(client, actions, refresh=False)
        indexed += int(ok_count)
        if bulk_errors:
            errors.extend(str(e) for e in bulk_errors[:5])

    client.indices.refresh(index=index_name)
    return {"indexed": indexed, "index": index_name, "errors": errors}


__all__ = ["ensure_docs_index", "bulk_index_doc_chunks"]
