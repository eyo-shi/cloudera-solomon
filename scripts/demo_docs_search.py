#!/usr/bin/env python3
"""Demo: create docs index from Ossie mapping, index sample JP chunks, search.

Usage (OpenSearch 2.11+ reachable, embedding optional for keyword-only test):

  SOLOMON_SEMANTIC_ROOT=tests/fixtures/semantic/sample_orders \\
  OPENSEARCH_MODE=internal \\
  uv run python scripts/demo_docs_search.py --query 顧客

Keyword-only without embeddings:

  uv run python scripts/demo_docs_search.py --query 問い合わせ --mode keyword
"""
from __future__ import annotations

import argparse
import json
import sys

from solomon.opensearch.docs_indexer import bulk_index_doc_chunks, ensure_docs_index
from solomon.opensearch.docs_search import search_documents
from solomon.opensearch.client import build_client
from solomon.transport.config import get_opensearch_config


def _sample_chunks() -> list[dict]:
    return [
        {
            "chunk_id": "demo-1-0",
            "doc_id": "demo-1",
            "chunk_no": 0,
            "doc_type": "inquiry",
            "title": "Customer inquiry",
            "text": "顧客から配送遅延について問い合わせがありました。",
        },
        {
            "chunk_id": "demo-2-0",
            "doc_id": "demo-2",
            "chunk_no": 0,
            "doc_type": "inquiry",
            "title": "Product question",
            "text": "商品仕様に関する一般的な質問です。",
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="顧客")
    parser.add_argument("--mode", default="hybrid", choices=["keyword", "vector", "hybrid"])
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()

    config = get_opensearch_config()
    if config is None:
        print("OpenSearch not configured", file=sys.stderr)
        return 1

    client = build_client(config)
    if not args.skip_index:
        engine = ensure_docs_index(client, config)
        print(f"docs index ready ({engine}): {config.docs_index_name}")
        bulk = bulk_index_doc_chunks(
            config,
            _sample_chunks(),
            with_embedding=args.mode != "keyword",
        )
        print("bulk index:", json.dumps(bulk, ensure_ascii=False))

    result = search_documents(
        config,
        args.query,
        top_k=5,
        mode=args.mode,
        group_by_doc=True,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
