"""Ossie ``document_index`` 定義の解決と doc_search 用メタデータ。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from solomon.semantic.context import get_semantic_context
from solomon.semantic.solomon_extension import extract_solomon_extensions
from solomon.semantic.store import load_models
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

AnalyzerChoice = Literal["cjk", "kuromoji"]


def resolve_docs_index_name(config: Any) -> str:
    from solomon.opensearch.env import opensearch_env

    env_idx = opensearch_env("DOCS_INDEX")
    if env_idx:
        return env_idx.strip()
    for doc in get_semantic_context().document_indexes:
        idx = doc.get("index")
        if isinstance(idx, str) and idx.strip():
            return idx.strip()
    namespace = getattr(config, "namespace", None) or "solomon"
    return f"{namespace}-docs"


def resolve_docs_analyzer() -> AnalyzerChoice:
    from solomon.opensearch.env import opensearch_env

    raw = (opensearch_env("DOCS_ANALYZER") or "cjk").strip().lower()
    if raw == "kuromoji":
        return "kuromoji"
    return "cjk"


def primary_document_index_def() -> dict[str, Any]:
    """最初の ``document_index`` 定義（マッピング生成の正）。"""
    docs = get_semantic_context().document_indexes
    if docs:
        return dict(docs[0])
    return {}


def doc_type_label_map(doc_index: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for dt in doc_index.get("doc_types") or []:
        if isinstance(dt, dict) and dt.get("id"):
            out[str(dt["id"])] = str(dt.get("label") or dt["id"])
    return out


def collect_filterable_field_defs() -> list[dict[str, Any]]:
    """``document_index`` を持つデータセットの filterable 列。"""
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in load_models():
        for ds in model.datasets:
            ds_ext = extract_solomon_extensions(ds.custom_extensions)
            if not ds_ext.get("document_index"):
                continue
            for field in ds.fields:
                f_ext = extract_solomon_extensions(field.custom_extensions)
                if not f_ext.get("filterable"):
                    continue
                name = field.name
                if name in seen:
                    continue
                seen.add(name)
                fields.append(
                    {
                        "name": name,
                        "label": (field.label or name).strip(),
                        "datatype": field.datatype or "String",
                        "physical_type": f_ext.get("physical_type"),
                        "description": field.description or "",
                    }
                )
    return fields


def build_doc_search_tool_description() -> str:
    """Agent 用 doc_search 説明（Ossie 由来、業種語彙なし）。"""
    doc_index = primary_document_index_def()
    lines = [
        "Search business document chunks in OpenSearch (BM25 + vector hybrid).",
        "Returns doc_id, title, snippet, score, and filterable metadata.",
    ]
    types = doc_index.get("doc_types") or []
    if types:
        lines.append("Document types (filters.doc_type):")
        for dt in types[:20]:
            if not isinstance(dt, dict):
                continue
            lines.append(
                f"  - {dt.get('id')}: {dt.get('label', '')} — "
                f"{(dt.get('description') or '')[:120]}"
            )
    filt = collect_filterable_field_defs()
    if filt:
        lines.append("Additional filters (equality / list of values):")
        for f in filt[:25]:
            lines.append(
                f"  - {f['name']} ({f.get('datatype', 'String')}): "
                f"{(f.get('description') or '')[:80]}"
            )
    lines.append("Common filters: doc_type (list), date_from, date_to (ISO dates).")
    return " ".join(lines)


__all__ = [
    "resolve_docs_index_name",
    "resolve_docs_analyzer",
    "primary_document_index_def",
    "doc_type_label_map",
    "collect_filterable_field_defs",
    "build_doc_search_tool_description",
]
