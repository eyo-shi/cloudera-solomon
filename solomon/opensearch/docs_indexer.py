"""業務文書チャンクの投入（デモローダー用。Solomon 本体からは呼ばない）。"""

from __future__ import annotations

import json
from typing import Any

from solomon.opensearch.client import build_client
from solomon.opensearch.doc_index import primary_document_index_def
from solomon.opensearch.docs_mapping import KnnEngine, build_docs_mapping
from solomon.opensearch.embeddings import try_embed_batch
from solomon.opensearch.env import opensearch_env
from solomon.transport.config import OpenSearchConfig
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

BULK_HEADERS = {"Content-Type": "application/x-ndjson"}

#: 1 回の ``_bulk`` 本文の上限 (bytes)。CDP Semantic Search の Knox は再送用に
#: 本文を約 16 KiB までしか保持できず、超えると 500 (NonRepeatableRequestException)
#: になる (12 KiB は通り 16 KiB で失敗することを実測)。``OPENSEARCH_BULK_MAX_BYTES`` で変更可
DEFAULT_BULK_MAX_BYTES = 12 * 1024


def bulk_max_bytes() -> int:
    raw = opensearch_env("BULK_MAX_BYTES")
    try:
        value = int(raw) if raw else DEFAULT_BULK_MAX_BYTES
    except ValueError:
        value = DEFAULT_BULK_MAX_BYTES
    return value if value > 0 else DEFAULT_BULK_MAX_BYTES


def _action_bytes(action: dict[str, Any]) -> int:
    """``helpers.bulk`` が送る 1 アクション分 (メタ行 + 本文行) のバイト数。"""
    meta = {"index": {"_index": action["_index"], "_id": action["_id"]}}
    lines = [meta, action["_source"]]
    return sum(
        len(json.dumps(x, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        for x in lines
    )


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
    max_bytes = bulk_max_bytes()

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
            action = {
                "_op_type": "index",
                "_index": index_name,
                "_id": str(chunk_id),
                "_source": body,
            }
            size = _action_bytes(action)
            if size > max_bytes:
                # 単独でも上限を超えるものは gateway で必ず失敗し、bulk 全体が止まる
                _logger.warning(
                    "opensearch.bulk_action_too_large",
                    chunk_id=str(chunk_id),
                    bytes=size,
                    max_bytes=max_bytes,
                )
                errors.append(
                    f"chunk {chunk_id}: {size} bytes > OPENSEARCH_BULK_MAX_BYTES={max_bytes}"
                )
                continue
            actions.append(action)
        if not actions:
            continue
        # CDP Semantic Search の gateway は application/json の body を正規化して
        # 末尾改行を落とすため、_bulk は ndjson で送る
        ok_count, bulk_errors = bulk(
            client,
            actions,
            refresh=False,
            headers=BULK_HEADERS,
            max_chunk_bytes=max_bytes,
        )
        indexed += int(ok_count)
        if bulk_errors:
            errors.extend(str(e) for e in bulk_errors[:5])

    client.indices.refresh(index=index_name)
    return {"indexed": indexed, "index": index_name, "errors": errors}


__all__ = ["ensure_docs_index", "bulk_index_doc_chunks"]
