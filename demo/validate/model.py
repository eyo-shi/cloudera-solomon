"""Shared result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "category": self.category,
        }


@dataclass
class RunContext:
    domain_dir: Path
    scenario: dict[str, Any]
    report_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)
