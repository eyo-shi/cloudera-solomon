"""PuppyGraph スキーマ POST + Bolt 検証。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from demo.loader.ossie_domain import DomainModel
from demo.loader.puppygraph_schema import build_puppygraph_schema, write_schema_json


_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


class GraphLoadError(RuntimeError):
    pass


def default_catalog_type() -> str:
    """``DEMO_PUPPYGRAPH_CATALOG`` 未指定なら、Trino JDBC URI があれば trino、無ければ hms。"""
    raw = (os.environ.get("DEMO_PUPPYGRAPH_CATALOG") or "").strip().lower()
    if raw:
        return raw
    if (os.environ.get("PUPPYGRAPH_TRINO_JDBC_URI") or "").strip():
        return "trino"
    return "hms"


def trino_jdbc_defaults(trino_catalog: str | None = None) -> dict[str, str]:
    """``PUPPYGRAPH_TRINO_*`` 未設定時に Solomon の ``TRINO_*`` から補う値。

    PuppyGraph から見た Trino の URL が Solomon と同じ場合だけ使える
    (別ネットワークなら ``PUPPYGRAPH_TRINO_JDBC_URI`` を明示する)。
    """
    from solomon.trino.env import trino_endpoint_url, trino_env

    out: dict[str, str] = {}
    endpoint = (trino_endpoint_url() or "").strip()
    if endpoint:
        from solomon.transport.config import _parse_trino_host_port_scheme

        host, port, scheme = _parse_trino_host_port_scheme(
            endpoint,
            default_port=int(trino_env("PORT") or "443"),
            default_scheme=trino_env("SCHEME") or "https",
            port_env=trino_env("PORT"),
            scheme_env=trino_env("SCHEME"),
        )
        if host:
            catalog = trino_catalog or trino_env("CATALOG") or "iceberg"
            ssl = "?SSL=true" if scheme == "https" else ""
            out["PUPPYGRAPH_TRINO_JDBC_URI"] = f"jdbc:trino://{host}:{port}/{catalog}{ssl}"
    user = (trino_env("USER") or "").strip()
    if user:
        out["PUPPYGRAPH_TRINO_USER"] = user
    password = (trino_env("PASSWORD") or "").strip()
    if password:
        out["PUPPYGRAPH_TRINO_PASSWORD"] = password
    return out


def substitute_env(
    doc: dict[str, Any], defaults: dict[str, str] | None = None
) -> dict[str, Any]:
    """``${ENV}`` を環境変数 (空なら ``defaults``) で置換する。未解決はそのまま残す。"""
    fallback = defaults or {}

    def value_for(key: str, original: str) -> str:
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
        return fallback.get(key, original)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            return _PLACEHOLDER.sub(lambda m: value_for(m.group(1), m.group(0)), node)
        return node

    return walk(doc)


def unresolved_placeholders(doc: Any) -> list[str]:
    found = _PLACEHOLDER.findall(json.dumps(doc))
    return sorted(set(found))


def _drop_unset_password(doc: dict[str, Any]) -> dict[str, Any]:
    """パスワード未設定の Trino カタログは ``password`` キー自体を外す (認証なし Trino)。"""
    for cat in doc.get("catalog") or []:
        jdbc = cat.get("jdbc") if isinstance(cat, dict) else None
        if isinstance(jdbc, dict) and _PLACEHOLDER.fullmatch(str(jdbc.get("password", ""))):
            jdbc.pop("password", None)
    return doc


def resolve_schema(
    schema: dict[str, Any], defaults: dict[str, str] | None = None
) -> dict[str, Any]:
    body = _drop_unset_password(substitute_env(schema, defaults))
    missing = unresolved_placeholders(body)
    if missing:
        raise GraphLoadError(
            "PuppyGraph schema has unset variables: "
            + ", ".join(missing)
            + " (deploy.env または実行時の環境変数に設定してください)"
        )
    return body


def _redacted(body: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(body))
    for cat in out.get("catalog") or out.get("catalogs") or []:
        jdbc = cat.get("jdbc") if isinstance(cat, dict) else None
        if isinstance(jdbc, dict) and jdbc.get("password"):
            jdbc["password"] = "***"
    return out


def post_schema(
    schema: dict[str, Any],
    *,
    dry_run: bool,
    post_fn: Callable[[str, dict], Any] | None = None,
    defaults: dict[str, str] | None = None,
) -> None:
    url = (os.environ.get("PUPPYGRAPH_HTTP_URL") or "").strip()
    if not url:
        url = f"http://127.0.0.1:{os.environ.get('PUPPYGRAPH_HTTP_PORT', '8081')}"
    endpoint = urljoin(url.rstrip("/") + "/", "schema")
    if dry_run:
        body = _drop_unset_password(substitute_env(schema, defaults))
        print(f"POST {endpoint}")
        missing = unresolved_placeholders(body)
        if missing:
            print(f"  (unset: {', '.join(missing)})")
        print(json.dumps(_redacted(body), ensure_ascii=False, indent=2)[:2000])
        return
    body = resolve_schema(schema, defaults)
    if post_fn:
        post_fn(endpoint, body)
        return
    import base64

    import httpx

    user = os.environ.get("PUPPYGRAPH_USERNAME", "puppygraph")
    pwd = os.environ.get("PUPPYGRAPH_PASSWORD", "")
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    resp = httpx.post(
        endpoint,
        json=body,
        headers={"Authorization": f"Basic {auth}"},
        timeout=120.0,
    )
    if resp.status_code >= 400:
        raise GraphLoadError(
            f"PuppyGraph schema POST failed: HTTP {resp.status_code} {resp.text[:1000]}"
        )
    print(f"POST {endpoint} -> HTTP {resp.status_code}")


def load_graph(
    domain: DomainModel,
    *,
    dry_run: bool,
    catalog_type: str | None = None,
    post_fn: Callable[[str, dict], Any] | None = None,
) -> dict[str, Any]:
    cat = catalog_type or default_catalog_type()
    out_path = domain.domain_dir / "puppygraph" / "schema.json"
    schema = write_schema_json(domain, out_path, catalog_type=cat)
    vertex_labels, edge_labels = schema_labels(schema)
    print(f"puppygraph catalog: {cat} -> {out_path}")
    if not vertex_labels:
        print("WARN: no graph vertices in Ossie model; skipping POST")
        return {"vertices": 0, "edges": 0}
    defaults: dict[str, str] = {}
    if cat == "trino":
        catalogs = {
            spec.catalog for spec in domain.tables.values() if spec.graph
        }
        defaults = trino_jdbc_defaults(next(iter(catalogs)) if len(catalogs) == 1 else None)
    post_schema(schema, dry_run=dry_run, post_fn=post_fn, defaults=defaults)
    if not dry_run:
        _verify_bolt(domain, schema)
    return {"vertices": len(vertex_labels), "edges": len(edge_labels)}


def schema_labels(schema: dict[str, Any]) -> tuple[set[str], set[str]]:
    """旧形式 (vertices/edges) と 1.15 形式 (node/edge) の両方からラベルを取る。"""
    vertices = schema.get("node") or schema.get("vertices") or []
    edges = schema.get("edge") or schema.get("edges") or []
    return {v["label"] for v in vertices}, {e["label"] for e in edges}


def _verify_bolt(domain: DomainModel, schema: dict[str, Any]) -> None:
    try:
        from solomon.graph.session import with_read_session
    except ImportError:
        print("WARN: graph session unavailable; skip Bolt verify")
        return

    expected_v, expected_e = schema_labels(schema)

    def _run(session: Any) -> None:
        labels_raw = session.run("CALL db.labels()").single()
        rels_raw = session.run("CALL db.relationshipTypes()").single()
        labels = set(labels_raw.values()) if labels_raw else set()
        rels = set(rels_raw.values()) if rels_raw else set()
        print(f"graph Bolt labels: {sorted(labels)}")
        print(f"graph Bolt relationshipTypes: {sorted(rels)}")
        if expected_v - labels:
            print(f"WARN: missing vertex labels in Bolt: {sorted(expected_v - labels)}")
        if expected_e - rels:
            print(f"WARN: missing edge types in Bolt: {sorted(expected_e - rels)}")
        for label in sorted(expected_v):
            rec = session.run(
                f"MATCH (n:`{label}`) RETURN count(n) AS c",
            ).single()
            if rec:
                print(f"  {label}: {rec['c']} nodes")

    try:
        with_read_session(_run)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Bolt verify failed: {exc}")


__all__ = [
    "GraphLoadError",
    "build_puppygraph_schema",
    "default_catalog_type",
    "load_graph",
    "post_schema",
    "resolve_schema",
    "substitute_env",
    "trino_jdbc_defaults",
]
