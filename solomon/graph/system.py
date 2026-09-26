"""System / Document inference helpers for Neo4j graph ingestion."""

from __future__ import annotations

import re
from typing import Any

_SYSTEM_META_KEYS = ("system", "system_name", "application", "app", "service")


def normalize_system_id(name: str) -> str:
    """System ノード id 用に正規化する。"""
    text = name.strip().lower()
    text = re.sub(r"[^a-z0-9_\-\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+", "_", text)
    return text.strip("_") or "default"


def infer_system_name(
    *,
    key: str,
    schema: str,
    meta_kv: list[dict[str, Any]] | None = None,
    explicit: str | None = None,
) -> str:
    """S3 key / meta_kv / schema から System 名を推定する。"""
    if explicit and explicit.strip():
        return explicit.strip()

    for item in meta_kv or []:
        k = str(item.get("key", "")).lower()
        if k in _SYSTEM_META_KEYS and item.get("value"):
            return str(item["value"]).strip()

    # key like "system_a/incidents/2025/data.csv" -> system_a
    if len(key.split("/")) >= 2:
        first = key.split("/")[0].strip()
        if first and not first.startswith("."):
            return first

    return schema.strip() or "default"


def build_ingestion_documents(
    *,
    dataset_id: str,
    bucket: str,
    key: str,
    format: str,
    ossie_path: str | None = None,
    meta_kv: list[dict[str, Any]] | None = None,
):
    """Ingestion 由来の Document ノード一覧を組み立てる。"""
    from solomon.graph.neo4j_loader import DocumentGraphNode

    docs: list[DocumentGraphNode] = []
    filename = key.rsplit("/", 1)[-1]
    source_path = f"s3://{bucket}/{key}"

    docs.append(
        DocumentGraphNode(
            id=f"doc:source:{dataset_id}",
            title=filename,
            doc_type="source_file",
            path=source_path,
            content_preview=f"format={format}",
        )
    )

    if ossie_path:
        docs.append(
            DocumentGraphNode(
                id=f"doc:ossie:{dataset_id}",
                title=f"Ossie semantic layer for {dataset_id}",
                doc_type="semantic_layer",
                path=ossie_path,
                content_preview=dataset_id,
            )
        )

    for item in meta_kv or []:
        k = str(item.get("key", "")).strip()
        v = str(item.get("value", "")).strip()
        if not k:
            continue
        lower = k.lower()
        if lower in _SYSTEM_META_KEYS:
            continue
        if any(token in lower for token in ("doc", "design", "spec", "設計", "障害", "incident")):
            doc_id = f"doc:meta:{dataset_id}:{normalize_system_id(k)}"
            docs.append(
                DocumentGraphNode(
                    id=doc_id,
                    title=k,
                    doc_type="design_doc" if "設計" in k or "design" in lower else "reference",
                    path=source_path,
                    content_preview=v[:500] if v else None,
                )
            )

    return docs


__all__ = [
    "normalize_system_id",
    "infer_system_name",
    "build_ingestion_documents",
]
