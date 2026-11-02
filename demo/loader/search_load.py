"""chunks.jsonl → OpenSearch。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from demo.loader.ossie_domain import DomainModel


def _doc_index_def(domain: DomainModel) -> dict[str, Any]:
    for spec in domain.tables.values():
        if spec.document_index:
            return spec.document_index
    return {}


def load_chunks(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_chunk(row: dict[str, Any], doc_index: dict[str, Any]) -> dict[str, Any]:
    out = {
        "chunk_id": row.get("chunk_id"),
        "doc_id": row.get("doc_id"),
        "section": row.get("section"),
        "text": row.get("text") or "",
        "title": row.get("title") or row.get("doc_id"),
        "doc_type": row.get("doc_type"),
        "doc_date": row.get("doc_date"),
    }
    for key, val in row.items():
        if key not in out and not key.startswith("_"):
            out[key] = val
    return {k: v for k, v in out.items() if v is not None}


def load_search(
    domain: DomainModel,
    *,
    dry_run: bool,
    recreate: bool,
    allow_missing_embedding: bool,
    skip_create: bool = False,
    index_fn: Any | None = None,
) -> dict[str, Any]:
    chunks_path = domain.domain_dir / "output" / "chunks.jsonl"
    if not chunks_path.is_file():
        return {"indexed": 0, "skipped": True}
    chunks_raw = load_chunks(chunks_path)
    doc_index = _doc_index_def(domain)
    chunks = [normalize_chunk(c, doc_index) for c in chunks_raw]
    embed_max = int(os.environ.get("DEMO_EMBED_MAX_CHARS", "2000"))

    if dry_run:
        print(f"search: {len(chunks)} chunks -> index {doc_index.get('index', '(default)')}")
        if recreate:
            print("  --recreate index")
        return {"indexed": len(chunks), "dry_run": True}

    if index_fn:
        return index_fn(chunks, doc_index, recreate=recreate, embed_max=embed_max)

    from solomon.opensearch.client import build_client
    from solomon.opensearch.doc_index import resolve_docs_index_name
    from solomon.opensearch.docs_indexer import bulk_index_doc_chunks, ensure_docs_index
    from solomon.transport.config import get_opensearch_config

    cfg = get_opensearch_config()
    if cfg is None:
        raise RuntimeError("OpenSearch not configured (OPENSEARCH_*)")

    client = build_client(cfg)
    index_name = resolve_docs_index_name(cfg)
    if recreate and client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)

    if skip_create:
        if not client.indices.exists(index=index_name):
            raise RuntimeError(
                f"index {index_name!r} missing (--skip-create); create it externally"
            )
    else:
        ensure_docs_index(client, cfg, doc_index or None)

    result = bulk_index_doc_chunks(
        cfg,
        chunks,
        with_embedding=True,
        embed_max_chars=embed_max,
        ensure_index=not skip_create,
    )
    missing = sum(1 for _ in chunks) - result.get("indexed", 0)
    if result.get("errors") and not allow_missing_embedding:
        raise RuntimeError(f"bulk index errors: {result['errors'][:3]}")
    if missing and not allow_missing_embedding:
        raise RuntimeError("embedding/index failures (use --allow-missing-embedding)")

    total = client.count(index=index_name).get("count", 0)
    print(f"search: index {index_name} _count={total}")
    by_type: dict[str, int] = {}
    agg = client.search(
        index=index_name,
        body={"size": 0, "aggs": {"by_type": {"terms": {"field": "doc_type", "size": 50}}}},
    )
    for bucket in agg.get("aggregations", {}).get("by_type", {}).get("buckets", []):
        by_type[str(bucket["key"])] = int(bucket["doc_count"])
    if by_type:
        print(f"  doc_type counts: {by_type}")
    known = {str(dt.get("id")) for dt in (doc_index.get("doc_types") or []) if isinstance(dt, dict)}
    for dt in by_type:
        if known and dt not in known:
            print(f"WARN: doc_type {dt!r} not in Ossie document_index.doc_types")
    result["total_count"] = total
    result["by_doc_type"] = by_type
    return result
