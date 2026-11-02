"""OpenSearch 文書 → Chat / Search タブ用 API ペイロード。"""

from __future__ import annotations

from typing import Any

from solomon.opensearch.doc_index import (
    collect_filterable_field_defs,
    doc_type_label_map,
    primary_document_index_def,
    resolve_docs_index_name,
)
from solomon.opensearch.docs_search import get_document_chunks
from solomon.transport.config import OpenSearchConfig


def metadata_labels_for_docs() -> dict[str, str]:
    labels: dict[str, str] = {}
    for fdef in collect_filterable_field_defs():
        name = str(fdef.get("name") or "")
        if name:
            labels[name] = str(fdef.get("label") or name)
    return labels


def business_document_entry(
    config: OpenSearchConfig,
    doc_id: str,
) -> dict[str, Any] | None:
    chunks = get_document_chunks(config, doc_id)
    if not chunks:
        return None
    meta = chunks[0]
    label_map = doc_type_label_map(primary_document_index_def())
    doc_type = meta.get("doc_type")
    doc_type_label = meta.get("doc_type_label") or (
        label_map.get(str(doc_type)) if doc_type else None
    )
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    meta_labels = metadata_labels_for_docs()
    text = "\n\n".join(str(c.get("text") or "") for c in chunks)
    return {
        "document_type": "doc",
        "doc_id": doc_id,
        "title": meta.get("title") or doc_id,
        "doc_type": doc_type,
        "doc_type_label": doc_type_label,
        "doc_date": meta.get("doc_date"),
        "metadata": metadata,
        "metadata_labels": meta_labels,
        "index": resolve_docs_index_name(config),
        "chunks": [
            {
                "chunk_id": c.get("chunk_id"),
                "section": c.get("section"),
                "text": c.get("text"),
            }
            for c in chunks
        ],
        "text": text[:50000],
    }


__all__ = ["business_document_entry", "metadata_labels_for_docs"]
