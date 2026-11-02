"""実行時ソース (table / graph / search) と Ossie 記述の照合。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from solomon.semantic.context import get_semantic_context
from solomon.semantic.models import dataset_fq_name
from solomon.semantic.solomon_extension import extract_solomon_extensions
from solomon.semantic.store import load_models
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

DocumentStatsProvider = Callable[[str, dict[str, Any]], dict[str, Any]]


def _default_document_stats_provider(_dataset: str, _doc: dict[str, Any]) -> dict[str, Any]:
    from solomon.opensearch.docs_search import doc_type_counts
    from solomon.transport.config import get_opensearch_config

    config = get_opensearch_config()
    if config is None:
        return {"configured": False}
    try:
        return {"doc_type_counts": doc_type_counts(config)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

_TTL_SEC = 300.0
_cache_at: float = 0.0
_cache_catalog: Optional["SourceCatalog"] = None


@dataclass
class SourceCatalog:
    tables: list[dict[str, Any]] = field(default_factory=list)
    graph: dict[str, Any] = field(default_factory=dict)
    search: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_source_catalog(
    sources: set[str] | None = None,
    *,
    document_stats_provider: DocumentStatsProvider | None = None,
    force: bool = False,
) -> SourceCatalog:
    global _cache_at, _cache_catalog
    now = time.monotonic()
    if (
        not force
        and _cache_catalog is not None
        and (now - _cache_at) < _TTL_SEC
        and sources is None
    ):
        return _cache_catalog

    enabled = sources or {"table", "graph", "search"}
    catalog = SourceCatalog()
    ctx = get_semantic_context(force=force)

    if "table" in enabled:
        ossie_tables: dict[str, dict[str, Any]] = {}
        for model in load_models():
            for ds in model.datasets:
                ext = extract_solomon_extensions(ds.custom_extensions)
                kind = ext.get("kind") or "table"
                if kind == "graph_only":
                    continue
                queryable = ext.get("queryable", kind == "table")
                if not queryable:
                    continue
                fq = dataset_fq_name(model.name, ds)
                ossie_tables[fq.lower()] = {
                    "fq_name": fq,
                    "model": model.name,
                    "dataset": ds.name,
                    "in_ossie": True,
                }
        trino_tables: set[str] = set()
        try:
            from solomon.transport.config import get_trino_config

            if get_trino_config() is not None:
                from solomon.tools.trino import TrinoQueryTool

                tool = TrinoQueryTool()
                result = tool.run(
                    user_ctx=None,
                    sql=(
                        "SELECT table_catalog, table_schema, table_name "
                        "FROM information_schema.tables "
                        "WHERE table_type = 'BASE TABLE' LIMIT 500"
                    ),
                    max_rows=500,
                )
                if result.get("status") == "ok":
                    for row in result.get("rows") or []:
                        if len(row) >= 3:
                            trino_tables.add(
                                f"{row[0]}.{row[1]}.{row[2]}".lower()
                            )
        except Exception as exc:  # noqa: BLE001
            catalog.warnings.append(f"trino introspection failed: {exc}")

        seen = set(ossie_tables.keys()) | trino_tables
        for fq_lower in sorted(seen):
            entry = ossie_tables.get(fq_lower, {"fq_name": fq_lower, "in_ossie": False})
            entry = dict(entry)
            entry["in_trino"] = fq_lower in trino_tables
            if entry.get("in_ossie") and not entry.get("in_trino") and trino_tables:
                catalog.warnings.append(f"Ossie table not found in Trino: {entry['fq_name']}")
            if entry.get("in_trino") and not entry.get("in_ossie"):
                entry["note"] = "trino_only"
            catalog.tables.append(entry)

    if "graph" in enabled:
        labels_ossie: set[str] = set()
        for g in ctx.graph_definitions:
            v = g.get("vertex") or {}
            if v.get("label"):
                labels_ossie.add(str(v["label"]))
            for e in g.get("edges") or []:
                if e.get("from_label"):
                    labels_ossie.add(str(e["from_label"]))
                if e.get("to_label"):
                    labels_ossie.add(str(e["to_label"]))
        labels_live: set[str] = set()
        try:
            from solomon.graph.browse import fetch_schema
            from solomon.transport.config import get_graph_config

            if get_graph_config() is not None:
                schema = fetch_schema()
                labels_live = set(schema.node_labels)
        except Exception as exc:  # noqa: BLE001
            catalog.warnings.append(f"graph schema fetch failed: {exc}")
        catalog.graph = {
            "ossie_labels": sorted(labels_ossie),
            "live_labels": sorted(labels_live),
        }
        if labels_live:
            for lb in labels_ossie - labels_live:
                catalog.warnings.append(f"Ossie graph label missing in PuppyGraph: {lb}")
            for lb in labels_live - labels_ossie:
                _logger.debug("source_catalog.graph_label_not_in_ossie", label=lb)

    if "search" in enabled:
        stats_provider = document_stats_provider or _default_document_stats_provider
        for doc in ctx.document_indexes:
            item = dict(doc)
            try:
                item["stats"] = stats_provider(doc.get("dataset") or "", doc)
            except Exception as exc:  # noqa: BLE001
                catalog.warnings.append(f"document stats failed: {exc}")
            catalog.search.append(item)

    if sources is None:
        _cache_at = now
        _cache_catalog = catalog
    return catalog


__all__ = ["SourceCatalog", "build_source_catalog", "DocumentStatsProvider"]
