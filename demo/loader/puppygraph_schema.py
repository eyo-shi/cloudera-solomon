"""Ossie graph 注記 → PuppyGraph スキーマ JSON。"""

from __future__ import annotations

import json
from typing import Any

from demo.loader.ossie_domain import DomainModel, TableSpec, field_names


class GraphSchemaError(Exception):
    pass


def _catalog_block(catalog_type: str) -> dict[str, Any]:
    if catalog_type == "rest":
        return {
            "name": "${ICEBERG_CATALOG}",
            "type": "iceberg",
            "iceberg": {
                "catalog_type": "rest",
                "uri": "${ICEBERG_REST_URI}",
                "warehouse": "${ICEBERG_WAREHOUSE}",
            },
        }
    return {
        "name": "${ICEBERG_CATALOG}",
        "type": "iceberg",
        "hive": {
            "metastore_uri": "${HIVE_METASTORE_URI}",
        },
    }


def build_puppygraph_schema(
    domain: DomainModel,
    *,
    catalog_type: str = "hms",
) -> dict[str, Any]:
    vertices: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    labels: set[str] = set()
    edge_specs: list[tuple[TableSpec, dict[str, Any]]] = []

    for spec in domain.tables.values():
        g = spec.graph or {}
        vtx = g.get("vertex")
        if isinstance(vtx, dict) and vtx.get("label") and vtx.get("id_field"):
            label = str(vtx["label"])
            labels.add(label)
            id_field = str(vtx["id_field"])
            if id_field not in field_names(spec):
                raise GraphSchemaError(
                    f"{spec.name}: vertex id_field {id_field!r} not in fields"
                )
            props = [str(p) for p in vtx.get("property_fields") or []]
            for p in props:
                if p not in field_names(spec):
                    raise GraphSchemaError(
                        f"{spec.name}: property {p!r} not in fields"
                    )
            vertices.append(
                {
                    "label": label,
                    "oneToOne": {
                        "tableSource": {
                            "catalog": spec.catalog,
                            "schema": spec.schema,
                            "table": spec.table,
                        },
                        "id": {"fields": [id_field]},
                        "attributes": [{"field": p, "alias": p} for p in props],
                    },
                }
            )
        for edge in g.get("edges") or []:
            if isinstance(edge, dict):
                edge_specs.append((spec, edge))

    for spec, edge in edge_specs:
        elabel = str(edge.get("label") or "")
        fl = str(edge.get("from_label") or "")
        tl = str(edge.get("to_label") or "")
        ff = str(edge.get("from_field") or "")
        tf = str(edge.get("to_field") or "")
        eid = str(edge.get("id_field") or "")
        if not all([elabel, fl, tl, ff, tf]):
            raise GraphSchemaError(f"{spec.name}: incomplete edge {edge!r}")
        if fl not in labels or tl not in labels:
            raise GraphSchemaError(
                f"{spec.name}: edge {elabel} references unknown labels {fl}/{tl}"
            )
        for col in (ff, tf, eid) if eid else (ff, tf):
            if col and col not in field_names(spec):
                raise GraphSchemaError(
                    f"{spec.name}: edge column {col!r} not in fields"
                )
        edge_obj: dict[str, Any] = {
            "label": elabel,
            "fromLabel": fl,
            "toLabel": tl,
            "tableSource": {
                "catalog": spec.catalog,
                "schema": spec.schema,
                "table": spec.table,
            },
            "fromId": {"fields": [ff]},
            "toId": {"fields": [tf]},
        }
        if eid:
            edge_obj["id"] = {"fields": [eid]}
        edges.append(edge_obj)

    return {
        "catalogs": [_catalog_block(catalog_type)],
        "vertices": vertices,
        "edges": edges,
    }


def write_schema_json(
    domain: DomainModel,
    path: "Path",
    *,
    catalog_type: str = "hms",
) -> dict[str, Any]:
    from pathlib import Path

    doc = build_puppygraph_schema(domain, catalog_type=catalog_type)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


__all__ = ["build_puppygraph_schema", "write_schema_json", "GraphSchemaError"]
