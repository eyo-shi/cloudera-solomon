#!/usr/bin/env python3
"""Fail if demo-specific semantic tokens appear under solomon/ or solomon_ui/src/."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_DIRS = [REPO / "solomon", REPO / "solomon_ui" / "src"]
DEMO_SEMANTIC = REPO / "demo"


def _collect_terms() -> set[str]:
    terms: set[str] = set()
    if not DEMO_SEMANTIC.is_dir():
        return terms
    for path in DEMO_SEMANTIC.rglob("semantic/models/*.yaml"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"\b(term|label|id):\s*['\"]?([A-Za-z0-9_\-]{3,})", text):
            terms.add(m.group(2))
        for m in re.finditer(r"doc_types:\s*\n(?:\s+-\s+id:\s+(\w+))+", text):
            pass
        for m in re.finditer(r"id:\s*(\w+)", text):
            if m.group(1) not in ("table", "document_index", "graph_only"):
                terms.add(m.group(1))
    return {t for t in terms if len(t) >= 4}


def main() -> int:
    terms = _collect_terms()
    if not terms:
        print("check_domain_neutral: no demo semantic terms (skip)")
        return 0
    failures: list[str] = []
    for term in sorted(terms):
        for base in SCAN_DIRS:
            if not base.is_dir():
                continue
            proc = subprocess.run(
                ["rg", "-n", re.escape(term), str(base)],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                failures.append(f"{term} in {base.name}:\n{proc.stdout.strip()[:500]}")
    if failures:
        print("Domain-neutral check failed:")
        for f in failures:
            print(f)
        return 1
    print("check_domain_neutral: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
