"""業務文書インデックスの OpenSearch マッピング生成。"""

from __future__ import annotations

from typing import Any, Literal

from solomon.opensearch.doc_index import collect_filterable_field_defs

AnalyzerChoice = Literal["cjk", "kuromoji"]
KnnEngine = Literal["lucene", "faiss", "nmslib_post_filter"]


def _text_analyzer_settings(analyzer: AnalyzerChoice) -> dict[str, Any]:
    if analyzer == "kuromoji":
        return {
            "analysis": {
                "tokenizer": {
                    "docs_kuromoji": {"type": "kuromoji_tokenizer"},
                },
                "analyzer": {
                    "docs_text_analyzer": {
                        "type": "custom",
                        "tokenizer": "docs_kuromoji",
                    }
                },
            }
        }
    return {
        "analysis": {
            "analyzer": {
                "docs_text_analyzer": {"type": "cjk"},
            }
        }
    }


def _ossie_datatype_to_mapping(
    datatype: str,
    *,
    physical_type: str | None = None,
) -> dict[str, Any]:
    dt = (datatype or "String").strip()
    if dt == "String":
        return {"type": "keyword"}
    if dt in ("Date", "Time", "DateTime", "DateTimeTz"):
        return {"type": "date", "format": "strict_date_optional_time||epoch_millis"}
    if dt == "Integer":
        return {"type": "long"}
    if dt in ("Decimal", "Float"):
        return {"type": "double"}
    if dt == "Boolean":
        return {"type": "boolean"}
    if dt == "Opaque" and physical_type and "array" in physical_type.lower():
        return {"type": "keyword"}
    return {"type": "keyword"}


def _knn_method(engine: KnnEngine, *, embedding_dim: int) -> dict[str, Any]:
    if engine == "lucene":
        return {
            "name": "hnsw",
            "space_type": "cosinesimil",
            "engine": "lucene",
            "parameters": {"ef_construction": 128, "m": 16},
        }
    if engine == "faiss":
        return {
            "name": "hnsw",
            "space_type": "cosinesimil",
            "engine": "faiss",
            "parameters": {"ef_construction": 128, "m": 16},
        }
    return {
        "name": "hnsw",
        "space_type": "cosinesimil",
        "engine": "nmslib",
    }


def build_docs_mapping(
    doc_index_def: dict[str, Any] | None,
    *,
    analyzer: AnalyzerChoice = "cjk",
    embedding_dim: int = 1024,
    knn_engine: KnnEngine = "lucene",
) -> dict[str, Any]:
    """文書チャンク用インデックス body（settings + mappings）。"""
    _ = doc_index_def
    settings: dict[str, Any] = {"index.knn": True}
    settings.update(_text_analyzer_settings(analyzer))
    properties: dict[str, Any] = {
        "chunk_id": {"type": "keyword"},
        "doc_id": {"type": "keyword"},
        "chunk_no": {"type": "integer"},
        "section": {"type": "keyword"},
        "doc_type": {"type": "keyword"},
        "doc_date": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
        "title": {
            "type": "text",
            "analyzer": "docs_text_analyzer",
            "fields": {"keyword": {"type": "keyword"}},
        },
        "text": {"type": "text", "analyzer": "docs_text_analyzer"},
        "source_path": {"type": "keyword"},
        "embedding": {
            "type": "knn_vector",
            "dimension": embedding_dim,
            "method": _knn_method(knn_engine, embedding_dim=embedding_dim),
        },
    }
    for fdef in collect_filterable_field_defs():
        properties[fdef["name"]] = _ossie_datatype_to_mapping(
            str(fdef.get("datatype") or "String"),
            physical_type=fdef.get("physical_type"),
        )
    return {"settings": settings, "mappings": {"properties": properties}}


__all__ = ["build_docs_mapping", "KnnEngine"]
