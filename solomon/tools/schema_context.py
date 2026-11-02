"""Ossie + Trino information_schema から Text2SQL 用スキーマ文脈を組み立てる。"""

from __future__ import annotations

from typing import Any, Optional

from solomon.semantic.models import (
    AIContext,
    OssieDataset,
    OssieField,
    OssieMetric,
    OssieSemanticModel,
    dataset_fq_name,
    dataset_source_ref,
)
from solomon.semantic.search import tokenize
from solomon.semantic.solomon_extension import extract_solomon_extensions
from solomon.semantic.store import load_models, search_datasets
from solomon.transport.logging import get_logger
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)

_COLUMN_CACHE: dict[tuple[str, str, str], list[dict[str, str]]] = {}


def clear_schema_context_caches() -> None:
    _COLUMN_CACHE.clear()


def _ai_synonyms(ctx: AIContext | str | None) -> list[str]:
    if ctx is None or isinstance(ctx, str):
        return []
    return list(ctx.synonyms or [])


def _ai_instructions(ctx: AIContext | str | None) -> str:
    if ctx is None:
        return ""
    if isinstance(ctx, str):
        return ctx.strip()
    return (ctx.instructions or "").strip()


def _metric_expression(metric: OssieMetric) -> str:
    expr = metric.expression
    if isinstance(expr, str):
        return expr.strip()
    if expr is not None and getattr(expr, "sql", None):
        return str(expr.sql).strip()
    return ""


def _parse_catalog_schema_table(ref: str) -> tuple[str | None, str | None, str | None]:
    parts = [p.strip() for p in ref.split(".") if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    return None, None, None


def _is_sql_table_dataset(ds: OssieDataset) -> bool:
    ext = extract_solomon_extensions(ds.custom_extensions)
    kind = str(ext.get("kind") or "table")
    if kind in ("document_index", "graph_only"):
        return False
    if ext.get("queryable") is False:
        return False
    if kind == "table":
        return True
    return ext.get("queryable") is True


def _dataset_in_schema(
    ds: OssieDataset,
    *,
    catalog: str,
    schema: str,
) -> bool:
    ref = dataset_source_ref(ds.source)
    if not ref:
        return False
    cat, sch, _tbl = _parse_catalog_schema_table(ref)
    if not cat or not sch:
        return False
    return cat.lower() == catalog.lower() and sch.lower() == schema.lower()


def _eligible_datasets(
    catalog: str,
    schema: str,
) -> list[tuple[OssieSemanticModel, OssieDataset, str]]:
    out: list[tuple[OssieSemanticModel, OssieDataset, str]] = []
    for model in load_models():
        for ds in model.datasets:
            if not _is_sql_table_dataset(ds):
                continue
            if not _dataset_in_schema(ds, catalog=catalog, schema=schema):
                continue
            fq = dataset_fq_name(model.name, ds)
            out.append((model, ds, fq))
    out.sort(key=lambda x: x[2])
    return out


def _select_datasets_for_question(
    question: str,
    eligible: list[tuple[OssieSemanticModel, OssieDataset, str]],
    *,
    max_tables: int,
) -> list[tuple[OssieSemanticModel, OssieDataset, str]]:
    if len(eligible) <= max_tables:
        return eligible
    eligible_fqs = {fq.lower(): (model, ds, fq) for model, ds, fq in eligible}
    hits = search_datasets(question, top_k=max_tables)
    selected: list[tuple[OssieSemanticModel, OssieDataset, str]] = []
    seen: set[str] = set()
    for hit in hits:
        fq = str(hit.get("fq_name") or "")
        key = fq.lower()
        if key in eligible_fqs and key not in seen:
            model, ds, fq_name = eligible_fqs[key]
            selected.append((model, ds, fq_name))
            seen.add(key)
    if not selected:
        selected = eligible[:max_tables]
    return selected


def _bigram_similarity(a: str, b: str) -> float:
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _verified_queries_for_selection(
    question: str,
    selected: list[tuple[OssieSemanticModel, OssieDataset, str]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    ds_names = {ds.name for _m, ds, _fq in selected if ds is not None}
    model_names = {m.name for m, _ds, _fq in selected if m is not None}
    candidates: list[dict[str, Any]] = []
    for model in load_models():
        if model.name not in model_names:
            continue
        ext = extract_solomon_extensions(model.custom_extensions)
        for vq in ext.get("verified_queries") or []:
            if isinstance(vq, dict) and vq.get("sql"):
                candidates.append(vq)
        for ds in model.datasets:
            if ds.name not in ds_names:
                continue
            ds_ext = extract_solomon_extensions(ds.custom_extensions)
            for vq in ds_ext.get("verified_queries") or []:
                if isinstance(vq, dict) and vq.get("sql"):
                    candidates.append(vq)
    scored: list[tuple[float, dict[str, Any]]] = []
    for vq in candidates:
        qtext = str(vq.get("question") or "")
        scored.append((_bigram_similarity(question, qtext), vq))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    seen_sql: set[str] = set()
    for sc, vq in scored:
        if sc <= 0 and out:
            continue
        sql = str(vq.get("sql") or "").strip()
        if not sql or sql in seen_sql:
            continue
        seen_sql.add(sql)
        out.append(vq)
        if len(out) >= limit:
            break
    return out


def _field_is_time(field: OssieField) -> bool:
    dim = field.dimension
    if dim is True:
        return False
    if isinstance(dim, dict):
        return bool(dim.get("is_time"))
    if hasattr(dim, "is_time"):
        return bool(dim.is_time)
    return False


def _format_field(field: OssieField) -> str:
    parts = [field.name]
    if field.datatype:
        parts.append(f"({field.datatype})")
    if _field_is_time(field):
        parts.append("[time]")
    if field.description:
        parts.append(f"- {field.description}")
    syns = _ai_synonyms(field.ai_context)
    if syns:
        parts.append(f"synonyms={syns}")
    return " ".join(parts)


def _format_metric(metric: OssieMetric, *, prefix: str = "") -> str:
    expr = _metric_expression(metric)
    line = f"{prefix}{metric.name}"
    if expr:
        line += f" = {expr}"
    if metric.description:
        line += f" — {metric.description}"
    syns = _ai_synonyms(metric.ai_context)
    if syns:
        line += f" synonyms={syns}"
    return line


def _relationship_lines(
    models: list[OssieSemanticModel],
    selected_ds_names: set[str],
) -> list[str]:
    lines: list[str] = []
    for model in models:
        for rel in model.relationships:
            from_name = rel.from_ or ""
            to_name = rel.to or ""
            if from_name not in selected_ds_names and to_name not in selected_ds_names:
                continue
            from_cols = rel.from_columns or []
            to_cols = rel.to_columns or []
            if not from_cols or not to_cols:
                continue
            pairs = ", ".join(
                f"{from_name}.{fc} = {to_name}.{tc}"
                for fc, tc in zip(from_cols, to_cols)
            )
            card = f"{from_name} 多 → {to_name} 一"
            line = f"- {pairs}（{card}）"
            instr = _ai_instructions(rel.ai_context)
            if instr:
                line += f" — {instr}"
            lines.append(line)
    return lines


def fetch_columns_information_schema(
    catalog: str,
    schema: str,
    table: str,
    *,
    user_ctx: Optional[UserContext] = None,
) -> list[dict[str, str]]:
    """プロセス内キャッシュ付き ``information_schema.columns``。"""
    key = (catalog.lower(), schema.lower(), table.lower())
    if key in _COLUMN_CACHE:
        return _COLUMN_CACHE[key]

    from solomon.tools._trino_client import trino_connection_for_user
    from solomon.transport.config import get_trino_config

    cfg = get_trino_config()
    if cfg is None:
        return []

    conn_or_err = trino_connection_for_user(user_ctx, catalog=catalog, schema=schema)
    if isinstance(conn_or_err, dict):
        _logger.debug("schema_context.trino_unavailable", table=f"{catalog}.{schema}.{table}")
        return []
    cols: list[dict[str, str]] = []
    try:
        cur = conn_or_err.cursor()
        cur.execute(
            f"SELECT column_name, data_type FROM {catalog}.information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            params=(schema, table),
        )
        for row in cur.fetchall():
            cols.append({"name": str(row[0]), "type": str(row[1])})
    except Exception as exc:  # noqa: BLE001
        _logger.debug("schema_context.columns_failed", error=str(exc))
        return []
    _COLUMN_CACHE[key] = cols
    return cols


def _fallback_tables_from_information_schema(
    catalog: str,
    schema: str,
    *,
    user_ctx: Optional[UserContext],
    max_tables: int,
) -> list[tuple[None, None, str]]:
    from solomon.tools._trino_client import trino_connection_for_user
    from solomon.transport.config import get_trino_config

    if get_trino_config() is None:
        return []
    conn_or_err = trino_connection_for_user(user_ctx, catalog=catalog, schema=schema)
    if isinstance(conn_or_err, dict):
        return []
    names: list[str] = []
    try:
        cur = conn_or_err.cursor()
        cur.execute(
            f"SELECT table_name FROM {catalog}.information_schema.tables "
            "WHERE table_schema = ? ORDER BY table_name",
            params=(schema,),
        )
        names = [str(r[0]) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        _logger.debug("schema_context.tables_failed", error=str(exc))
        return []
    out: list[tuple[None, None, str]] = []
    for name in names[:max_tables]:
        out.append((None, None, f"{catalog}.{schema}.{name}"))
    return out


def build_schema_context(
    question: str,
    *,
    catalog: str,
    schema: str,
    max_tables: int = 20,
    max_chars: int = 12000,
    user_ctx: Optional[UserContext] = None,
) -> str:
    """Text2SQL プロンプト用のスキーマ・結合・メトリクス・few-shot 文脈。"""
    eligible = _eligible_datasets(catalog, schema)
    selected = _select_datasets_for_question(question, eligible, max_tables=max_tables)
    if not selected:
        selected = _fallback_tables_from_information_schema(
            catalog,
            schema,
            user_ctx=user_ctx,
            max_tables=max_tables,
        )

    selected_ds_names = {
        ds.name for _m, ds, _fq in selected if ds is not None and ds.name
    }
    model_by_name = {m.name: m for m in load_models()}

    lines: list[str] = ["## Tables"]
    for model, ds, fq in selected:
        if ds is None:
            _cat, _sch, tbl = _parse_catalog_schema_table(fq)
            cols = fetch_columns_information_schema(
                catalog, schema, tbl or "", user_ctx=user_ctx
            )
            lines.append(f"### {fq} (information_schema only)")
            for col in cols:
                lines.append(f"  - {col['name']} ({col['type']})")
            continue

        lines.append(f"### {fq}")
        if ds.description:
            lines.append(f"description: {ds.description}")
        instr = _ai_instructions(ds.ai_context)
        if instr:
            lines.append(f"instructions: {instr}")
        lines.append("columns:")
        for field in ds.fields:
            lines.append(f"  - {_format_field(field)}")
        for metric in ds.metrics:
            lines.append(f"  - metric {_format_metric(metric)}")

    rel_lines = _relationship_lines(list(model_by_name.values()), selected_ds_names)
    if rel_lines:
        lines.append("## Joins")
        lines.extend(rel_lines)

    metric_lines: list[str] = []
    seen_models = {m.name for m, _ds, _fq in selected if m is not None}
    for model in load_models():
        if model.name not in seen_models:
            continue
        for metric in model.metrics:
            metric_lines.append(_format_metric(metric, prefix="model "))
    if metric_lines:
        lines.append("## Model metrics")
        lines.extend(f"- {m}" for m in metric_lines)

    verified = _verified_queries_for_selection(question, selected)
    if verified:
        lines.append("## Verified query examples (similar questions)")
        for vq in verified:
            q = str(vq.get("question") or "").strip()
            sql = str(vq.get("sql") or "").strip()
            notes = str(vq.get("notes") or "").strip()
            lines.append(f"- Q: {q}")
            lines.append(f"  SQL: {sql}")
            if notes:
                lines.append(f"  notes: {notes}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…(truncated)"
    return text


__all__ = [
    "build_schema_context",
    "clear_schema_context_caches",
    "fetch_columns_information_schema",
]
