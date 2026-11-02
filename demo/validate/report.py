"""Markdown / CSV reports under ``demo/<domain>/reports/``."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from demo.validate.model import CheckResult


def new_report_dir(domain_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = domain_dir / "reports" / stamp
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_summary_md(
    path: Path,
    *,
    title: str,
    level: str,
    metadata: dict[str, Any],
    results: list[CheckResult],
    sections: dict[str, str] | None = None,
) -> None:
    ok = sum(1 for r in results if r.ok)
    fail = sum(1 for r in results if not r.ok)
    lines = [
        f"# {title}",
        "",
        f"- **level**: `{level}`",
        f"- **time**: {datetime.now().isoformat(timespec='seconds')}",
        f"- **passed**: {ok} / **failed**: {fail}",
        "",
        "## Run metadata",
        "",
    ]
    for k, v in sorted(metadata.items()):
        lines.append(f"- `{k}`: {v}")
    lines.extend(["", "## Checks", ""])
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        cat = f" ({r.category})" if r.category else ""
        lines.append(f"- [{mark}]{cat} **{r.name}**: {r.detail or '—'}")
    if sections:
        for heading, body in sections.items():
            lines.extend(["", f"## {heading}", "", body])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def print_summary(results: list[CheckResult]) -> None:
    ok = sum(1 for r in results if r.ok)
    fail = len(results) - ok
    print(f"validate: {ok} passed, {fail} failed")
    for r in results:
        if not r.ok:
            print(f"  FAIL {r.name}: {r.detail}")


__all__ = ["new_report_dir", "write_summary_md", "write_csv", "print_summary"]
