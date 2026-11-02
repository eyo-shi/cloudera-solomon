"""PuppyGraph スキーマ POST + Bolt 検証。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from demo.loader.ossie_domain import DomainModel
from demo.loader.puppygraph_schema import build_puppygraph_schema, write_schema_json


def substitute_env(doc: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(doc)

    def repl(match: Any) -> str:
        key = match.group(1)
        return os.environ.get(key, match.group(0))

    import re

    out = re.sub(r"\$\{([A-Z0-9_]+)\}", repl, raw)
    return json.loads(out)


def post_schema(
    schema: dict[str, Any],
    *,
    dry_run: bool,
    post_fn: Callable[[str, dict], Any] | None = None,
) -> None:
    url = (os.environ.get("PUPPYGRAPH_HTTP_URL") or "").strip()
    if not url:
        url = f"http://127.0.0.1:{os.environ.get('PUPPYGRAPH_HTTP_PORT', '8081')}"
    endpoint = urljoin(url.rstrip("/") + "/", "schema")
    body = substitute_env(schema)
    if dry_run:
        print(f"POST {endpoint}")
        print(json.dumps(body, ensure_ascii=False, indent=2)[:2000])
        return
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
    resp.raise_for_status()


def load_graph(
    domain: DomainModel,
    *,
    dry_run: bool,
    catalog_type: str | None = None,
    post_fn: Callable[[str, dict], Any] | None = None,
) -> dict[str, Any]:
    cat = catalog_type or os.environ.get("DEMO_PUPPYGRAPH_CATALOG", "hms")
    out_path = domain.domain_dir / "puppygraph" / "schema.json"
    schema = write_schema_json(domain, out_path, catalog_type=cat)
    if not schema.get("vertices"):
        print("WARN: no graph vertices in Ossie model; skipping POST")
        return {"vertices": 0, "edges": 0}
    post_schema(schema, dry_run=dry_run, post_fn=post_fn)
    if not dry_run:
        _verify_bolt(domain, schema)
    return {"vertices": len(schema["vertices"]), "edges": len(schema["edges"])}


def _verify_bolt(domain: DomainModel, schema: dict[str, Any]) -> None:
    try:
        from solomon.graph.session import with_read_session
    except ImportError:
        print("WARN: graph session unavailable; skip Bolt verify")
        return

    expected_v = {v["label"] for v in schema.get("vertices") or []}
    expected_e = {e["label"] for e in schema.get("edges") or []}

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


__all__ = ["load_graph", "post_schema", "build_puppygraph_schema"]
