"""``python -m demo.validate`` CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from demo.validate.levels.agent import SOURCE_CONFIGS, run_agent
from demo.validate.levels.cluster import run_cluster
from demo.validate.levels.local import run_local
from demo.validate.levels.semantic import run_semantic
from demo.validate.metadata import collect_run_metadata
from demo.validate.report import new_report_dir, print_summary, write_csv, write_summary_md

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demo.validate")
    parser.add_argument("--domain-dir", required=True)
    parser.add_argument(
        "--level",
        choices=["semantic", "local", "cluster", "agent"],
        required=True,
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--questions", default="", help="Q1,Q2,...")
    parser.add_argument(
        "--configs",
        default="table,table_graph,table_search,all",
        help="agent source configs",
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Extra HTTP header Name:Value (repeatable). Also DEMO_VALIDATE_HTTP_HEADERS JSON.",
    )
    args = parser.parse_args(argv)

    domain_dir = Path(args.domain_dir)
    if not domain_dir.is_absolute():
        domain_dir = (REPO_ROOT / domain_dir).resolve()

    report_dir = new_report_dir(domain_dir)
    metadata = collect_run_metadata(domain_dir)
    metadata["level"] = args.level

    extra_headers: dict[str, str] = {}
    for h in args.header:
        if ":" in h:
            k, v = h.split(":", 1)
            extra_headers[k.strip()] = v.strip()

    results = []
    sections: dict[str, str] = {}
    csv_rows: list[dict] = []

    if args.level == "semantic":
        results = run_semantic(domain_dir)
    elif args.level == "local":
        results = run_local(domain_dir)
    elif args.level == "cluster":
        results, sc_rows, md = run_cluster(domain_dir)
        if sc_rows:
            csv_rows.extend(sc_rows)
        if md:
            sections["Search checks"] = md
    elif args.level == "agent":
        qids = [x.strip() for x in args.questions.split(",") if x.strip()] or None
        configs = [x.strip() for x in args.configs.split(",") if x.strip()]
        for c in configs:
            if c not in SOURCE_CONFIGS:
                print(f"WARN: unknown config {c!r}, known: {list(SOURCE_CONFIGS)}")
        configs = [c for c in configs if c in SOURCE_CONFIGS]
        results, csv_rows, md = run_agent(
            domain_dir,
            api_base=args.api,
            runs=max(1, args.runs),
            question_ids=qids,
            configs=configs or list(SOURCE_CONFIGS),
            extra_headers=extra_headers,
        )
        sections["Agent matrix"] = md
        metadata["agent_api"] = args.api
        metadata["agent_runs"] = args.runs

    write_summary_md(
        report_dir / "summary.md",
        title=f"Demo validate — {domain_dir.name}",
        level=args.level,
        metadata=metadata,
        results=results,
        sections=sections or None,
    )
    if csv_rows:
        write_csv(
            report_dir / "details.csv",
            csv_rows,
            fieldnames=list(csv_rows[0].keys()),
        )

    print_summary(results)
    print(f"report: {report_dir}")
    failed = any(not r.ok for r in results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
