"""Ossie モデルから集約した意味コンテキスト。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from solomon.semantic.models import AIContext, OssieSemanticModel, dataset_fq_name
from solomon.semantic.solomon_extension import extract_solomon_extensions, glossary_from_extension
from solomon.semantic.store import load_models, semantic_generation, semantic_root


@dataclass
class SemanticContext:
    models: list[OssieSemanticModel] = field(default_factory=list)
    glossary: list[dict[str, Any]] = field(default_factory=list)
    tool_hints: dict[str, str] = field(default_factory=dict)
    graph_examples: list[dict[str, Any]] = field(default_factory=list)
    verified_queries: list[dict[str, Any]] = field(default_factory=list)
    datasets: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    graph_definitions: list[dict[str, Any]] = field(default_factory=list)
    document_indexes: list[dict[str, Any]] = field(default_factory=list)
    example_questions: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        """``GET /api/semantic/context`` 用 (秘密・SQL 本文は含めない)。"""
        return {
            "models": [m.name for m in self.models],
            "business_descriptions": [
                {"model": m.name, "description": m.description or ""}
                for m in self.models
            ],
            "glossary": self.glossary,
            "tool_hints": self.tool_hints,
            "datasets": [
                {
                    "model": d["model"],
                    "name": d["name"],
                    "fq_name": d["fq_name"],
                    "description": d.get("description", ""),
                    "kind": d.get("kind", "table"),
                }
                for d in self.datasets
            ],
            "example_questions": self.example_questions[:30],
            "graph_labels": sorted(
                {
                    g.get("vertex", {}).get("label")
                    for g in self.graph_definitions
                    if g.get("vertex", {}).get("label")
                }
            ),
            "document_types": [
                dt
                for idx in self.document_indexes
                for dt in (idx.get("doc_types") or [])
            ],
        }


_cache_key: tuple[str, float] = ("", 0.0)
_cache_ctx: Optional[SemanticContext] = None


def _instructions(ctx: AIContext | str | None) -> str:
    if ctx is None:
        return ""
    if isinstance(ctx, str):
        return ctx
    return ctx.instructions or ""


def _examples(ctx: AIContext | str | None) -> list[str]:
    if ctx is None:
        return []
    if isinstance(ctx, str):
        return []
    return list(ctx.examples or [])


def get_semantic_context(*, force: bool = False) -> SemanticContext:
    global _cache_key, _cache_ctx
    root = str(semantic_root())
    models = load_models(force=force)
    key = (root, semantic_generation())
    if not force and _cache_ctx is not None and _cache_key == key:
        return _cache_ctx

    ctx = SemanticContext(models=models)
    for model in models:
        model_ext = extract_solomon_extensions(model.custom_extensions)
        ctx.glossary.extend([g.model_dump() for g in glossary_from_extension(model_ext)])
        for hint_key in ("table", "graph", "search"):
            if model_ext.get("tool_hints", {}).get(hint_key):
                ctx.tool_hints[hint_key] = str(model_ext["tool_hints"][hint_key])
        ctx.graph_examples.extend(model_ext.get("graph_examples") or [])
        ctx.verified_queries.extend(model_ext.get("verified_queries") or [])
        ctx.example_questions.extend(_examples(model.ai_context))

        for ds in model.datasets:
            fq = dataset_fq_name(model.name, ds)
            ds_ext = extract_solomon_extensions(ds.custom_extensions)
            kind = ds_ext.get("kind") or "table"
            ctx.datasets.append(
                {
                    "model": model.name,
                    "name": ds.name,
                    "fq_name": fq,
                    "description": ds.description or "",
                    "kind": kind,
                    "queryable": ds_ext.get("queryable", kind == "table"),
                    "fields": [f.name for f in ds.fields],
                    "dimension_fields": [f.name for f in ds.fields if f.is_dimension()],
                    "metrics": [m.name for m in ds.metrics],
                }
            )
            if ds_ext.get("graph"):
                ctx.graph_definitions.append(ds_ext["graph"])
            if ds_ext.get("document_index"):
                doc = dict(ds_ext["document_index"])
                doc["dataset"] = ds.name
                doc["model"] = model.name
                ctx.document_indexes.append(doc)
            ctx.example_questions.extend(_examples(ds.ai_context))
            ctx.verified_queries.extend(ds_ext.get("verified_queries") or [])

        for rel in model.relationships:
            ctx.relationships.append(rel.model_dump(by_alias=True, exclude_none=True))
        for metric in model.metrics:
            ctx.metrics.append(metric.model_dump(by_alias=True, exclude_none=True))

    _cache_key = key
    _cache_ctx = ctx
    return ctx


def render_business_context(max_chars: int = 8000) -> str:
    ctx = get_semantic_context()
    lines: list[str] = ["## 業務コンテキスト"]
    for m in ctx.models:
        if m.description:
            lines.append(f"- **{m.name}**: {m.description}")
        instr = _instructions(m.ai_context)
        if instr:
            lines.append(f"  - {instr[:400]}")
    for g in ctx.glossary[:50]:
        lines.append(f"- 用語 **{g.get('term')}**: {g.get('description', '')[:200]}")
    text = "\n".join(lines)
    return text[:max_chars]


def render_table_catalog(max_chars: int = 8000) -> str:
    ctx = get_semantic_context()
    lines = ["## テーブルカタログ"]
    for d in ctx.datasets:
        if d.get("kind") == "graph_only":
            continue
        lines.append(f"- `{d['fq_name']}`: {(d.get('description') or '')[:120]}")
    return "\n".join(lines)[:max_chars]


def render_graph_schema(max_chars: int = 8000) -> str:
    ctx = get_semantic_context()
    lines = ["## グラフ定義 (Ossie SOLOMON 拡張)"]
    vertices: list[str] = []
    edges: list[str] = []
    for g in ctx.graph_definitions:
        v = g.get("vertex") or {}
        if v.get("label"):
            vertices.append(f"- 頂点 `{v.get('label')}` id=`{v.get('id_field')}`")
        for e in g.get("edges") or []:
            edges.append(
                f"- 辺 `{e.get('label')}`: ({e.get('from_label')})-[:{e.get('label')}]->"
                f"({e.get('to_label')})"
            )
    lines.extend(vertices)
    lines.extend(edges)

    # 例は Cypher ごと渡す（質問文だけでは可変長パスの書き方が伝わらない）
    examples: list[str] = []
    for ex in ctx.graph_examples[:10]:
        question = str(ex.get("question") or "").strip()[:80]
        cypher = " ".join(str(ex.get("cypher") or "").split())
        notes = str(ex.get("notes") or "").strip()
        if not question and not cypher:
            continue
        entry = f"- 例: {question}" if question else "- 例:"
        if notes:
            entry += f"（{notes[:80]}）"
        if cypher:
            entry += f"\n  `{cypher[:600]}`"
        examples.append(entry)
    if examples:
        lines.append("### クエリ例")
        lines.extend(examples)
    return "\n".join(lines)[:max_chars]


def render_document_catalog(max_chars: int = 8000) -> str:
    ctx = get_semantic_context()
    lines = ["## 文書インデックス"]
    for doc in ctx.document_indexes:
        lines.append(f"- dataset={doc.get('dataset')} index={doc.get('index', '(default)')}")
        for dt in doc.get("doc_types") or []:
            lines.append(f"  - 種別 `{dt.get('id')}`: {dt.get('label', '')}")
    return "\n".join(lines)[:max_chars]


def render_tool_hints() -> str:
    ctx = get_semantic_context()
    if not ctx.tool_hints:
        return ""
    lines = ["## ツールヒント"]
    for k, v in ctx.tool_hints.items():
        lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)


__all__ = [
    "SemanticContext",
    "get_semantic_context",
    "render_business_context",
    "render_document_catalog",
    "render_graph_schema",
    "render_table_catalog",
    "render_tool_hints",
]
