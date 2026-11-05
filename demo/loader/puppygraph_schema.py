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


TRINO_CATALOG_NAME_DEFAULT = "solomon_trino"

# Trino 型 → PuppyGraph 1.x の属性型
_PUPPY_TYPES = {
    "varchar": "STRING",
    "bigint": "LONG",
    "integer": "INT",
    "smallint": "INT",
    "tinyint": "INT",
    "double": "DOUBLE",
    "real": "FLOAT",
    "boolean": "BOOLEAN",
    "date": "DATE",
}


def puppy_type(field: Any) -> str:
    from demo.loader.trino_types import trino_type

    t = trino_type(field).lower()
    if t in _PUPPY_TYPES:
        return _PUPPY_TYPES[t]
    if t.startswith("decimal"):
        return "DOUBLE"
    if t.startswith("timestamp"):
        return "DATETIME"
    return "STRING"


def trino_catalog_name() -> str:
    import os

    return (os.environ.get("PUPPYGRAPH_TRINO_CATALOG") or "").strip() or TRINO_CATALOG_NAME_DEFAULT


def _trino_catalog_block(name: str) -> dict[str, Any]:
    # 接続情報は POST 時に env で置換する (生成した schema.json に実ホスト・資格情報を残さない)
    return {
        "name": name,
        "type": "trino",
        "jdbc": {
            "username": "${PUPPYGRAPH_TRINO_USER}",
            "password": "${PUPPYGRAPH_TRINO_PASSWORD}",
            "jdbcUri": "${PUPPYGRAPH_TRINO_JDBC_URI}",
        },
    }


def _edge_id_fields(spec: TableSpec, edge: dict[str, Any], ff: str, tf: str) -> list[str]:
    """辺の ID 列。``id_field`` → 主キー → (from, to) の順で決める。"""
    eid = str(edge.get("id_field") or "")
    if eid:
        return [eid]
    names = field_names(spec)
    if spec.primary_key and all(k in names for k in spec.primary_key):
        return list(spec.primary_key)
    return [ff, tf] if ff != tf else [ff]


def _external_source(
    catalog: str, spec: TableSpec, columns: list[str]
) -> dict[str, Any]:
    seen: list[str] = []
    for c in columns:
        if c not in seen:
            seen.append(c)
    return {
        "externalDataSource": {
            "enabled": True,
            "catalog": catalog,
            "schema": spec.schema,
            "table": spec.table,
            "mappedField": [
                {"sourceFieldName": c, "targetFieldName": c} for c in seen
            ],
        }
    }


def build_trino_schema(domain: DomainModel, *, catalog_name: str | None = None) -> dict[str, Any]:
    """PuppyGraph 1.15 形式 (``catalog`` / ``node`` / ``edge``) — Trino カタログ経由。

    PuppyGraph は Trino の表をそのまま読む (zero-ETL)。Iceberg 表を作った後に POST する。
    JDBC URI の catalog 部分 (``jdbc:trino://host:443/<catalog>``) は Ossie の
    ``catalog.schema.table`` の catalog と一致させる。
    """
    catalog = catalog_name or trino_catalog_name()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    labels: set[str] = set()
    for spec, label, id_field, props in _vertex_specs(domain):
        labels.add(label)
        types = {f.name: puppy_type(f) for f in spec.fields}
        nodes.append(
            {
                "label": label,
                "dataSourceGroup": _external_source(catalog, spec, [id_field, *props]),
                "id": [{"name": id_field, "type": types[id_field]}],
                "attribute": [
                    {"name": p, "type": types[p]} for p in _with_id_attribute(id_field, props)
                ],
            }
        )
    for spec, edge, elabel, fl, tl, ff, tf in _edge_specs(domain, labels):
        types = {f.name: puppy_type(f) for f in spec.fields}
        id_fields = _edge_id_fields(spec, edge, ff, tf)
        edges.append(
            {
                "label": elabel,
                "fromNodeLabel": fl,
                "toNodeLabel": tl,
                "dataSourceGroup": _external_source(catalog, spec, [*id_fields, ff, tf]),
                "id": [{"name": c, "type": types[c]} for c in id_fields],
                "fromKey": [{"name": ff, "type": types[ff]}],
                "toKey": [{"name": tf, "type": types[tf]}],
                "attribute": [],
            }
        )
    return {
        "catalog": [_trino_catalog_block(catalog)],
        "node": nodes,
        "edge": edges,
    }


def _with_id_attribute(id_field: str, props: list[str]) -> list[str]:
    """ID 列も属性に入れる。

    PuppyGraph の ID 列は ``attribute`` に無いとプロパティとして読めず、
    ``(n:Lot {lot_id: $x})`` や ``n.lot_id`` が警告付きで null になる。
    """
    return [id_field, *(p for p in props if p != id_field)]


def _vertex_specs(domain: DomainModel) -> list[tuple[TableSpec, str, str, list[str]]]:
    out: list[tuple[TableSpec, str, str, list[str]]] = []
    for spec in domain.tables.values():
        vtx = (spec.graph or {}).get("vertex")
        if not (isinstance(vtx, dict) and vtx.get("label") and vtx.get("id_field")):
            continue
        id_field = str(vtx["id_field"])
        if id_field not in field_names(spec):
            raise GraphSchemaError(f"{spec.name}: vertex id_field {id_field!r} not in fields")
        props = [str(p) for p in vtx.get("property_fields") or []]
        for p in props:
            if p not in field_names(spec):
                raise GraphSchemaError(f"{spec.name}: property {p!r} not in fields")
        out.append((spec, str(vtx["label"]), id_field, props))
    return out


def _edge_specs(
    domain: DomainModel, labels: set[str]
) -> list[tuple[TableSpec, dict[str, Any], str, str, str, str, str]]:
    out: list[tuple[TableSpec, dict[str, Any], str, str, str, str, str]] = []
    for spec in domain.tables.values():
        for edge in (spec.graph or {}).get("edges") or []:
            if not isinstance(edge, dict):
                continue
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
            for col in (ff, tf, eid):
                if col and col not in field_names(spec):
                    raise GraphSchemaError(f"{spec.name}: edge column {col!r} not in fields")
            out.append((spec, edge, elabel, fl, tl, ff, tf))
    return out


def build_puppygraph_schema(
    domain: DomainModel,
    *,
    catalog_type: str = "hms",
) -> dict[str, Any]:
    if catalog_type == "trino":
        return build_trino_schema(domain)
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
                        "attributes": [
                            {"field": p, "alias": p}
                            for p in _with_id_attribute(id_field, props)
                        ],
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
