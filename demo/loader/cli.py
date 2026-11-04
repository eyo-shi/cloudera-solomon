"""``python -m demo.loader --domain-dir ...``"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from demo.loader.graph_load import load_graph
from demo.loader.iceberg_load import load_iceberg
from demo.loader.ossie_domain import load_domain
from demo.loader.search_load import load_search

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demo.loader")
    parser.add_argument("--domain-dir", required=True, help="e.g. demo/mfg_quality")
    parser.add_argument(
        "--target",
        choices=["all", "iceberg", "graph", "search"],
        default="all",
    )
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--iceberg-method", choices=["a", "b"], default=None)
    parser.add_argument("--allow-missing-embedding", action="store_true")
    parser.add_argument("--skip-create", action="store_true", help="OpenSearch index create skip")
    parser.add_argument(
        "--graph-schema-out",
        type=Path,
        default=None,
        help="PuppyGraph に POST せず、置換済み schema JSON を書く (UI Upload 用)",
    )
    args = parser.parse_args(argv)

    domain_dir = Path(args.domain_dir)
    if not domain_dir.is_absolute():
        domain_dir = (REPO_ROOT / domain_dir).resolve()

    domain = load_domain(domain_dir, validate=True)

    execute_fn = None
    query_fn = None
    if not args.dry_run and args.target in ("all", "iceberg"):
        from demo.loader.trino_runtime import make_trino_callbacks

        execute_fn, query_fn = make_trino_callbacks()

    if args.target in ("all", "iceberg"):
        print("== iceberg ==")
        load_iceberg(
            domain,
            dry_run=args.dry_run,
            recreate=args.recreate,
            method=args.iceberg_method,
            execute_fn=execute_fn,
            query_fn=query_fn,
        )

    if args.target in ("all", "graph"):
        print("== graph ==")
        load_graph(domain, dry_run=args.dry_run, schema_out=args.graph_schema_out)

    if args.target in ("all", "search"):
        print("== search ==")
        if args.skip_create and not args.dry_run:
            print("skip-create: ensure index exists externally")
        load_search(
            domain,
            dry_run=args.dry_run,
            recreate=args.recreate,
            allow_missing_embedding=args.allow_missing_embedding,
            skip_create=args.skip_create,
        )

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
