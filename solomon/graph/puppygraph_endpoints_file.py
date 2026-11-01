"""Bolt endpoints for co-located PuppyGraph (optional internal launcher)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from solomon.infra.env_compat import env_first

_ENDPOINTS_REL = Path(".solomon") / "puppygraph_endpoints.json"


def _project_dir() -> Path:
    for key in ("CDSW_PROJECT_DIR", "CML_PROJECT_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw)
    return Path.cwd()


def endpoints_file_path() -> Path:
    override = (
        env_first("PUPPYGRAPH_ENDPOINTS_FILE", "SOLOMON_PUPPYGRAPH_ENDPOINTS_FILE") or ""
    ).strip()
    if override:
        return Path(override)
    return _project_dir() / _ENDPOINTS_REL


def write_endpoints(payload: dict[str, Any]) -> Path:
    path = endpoints_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_bolt_uris() -> list[str]:
    path = endpoints_file_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    uris: list[str] = []
    seen: set[str] = set()

    def add_uri(raw: str | None) -> None:
        text = (raw or "").strip()
        if not text or text in seen:
            return
        if "://" not in text:
            text = f"bolt://{text}"
        seen.add(text)
        uris.append(text)

    for host in data.get("bolt_hosts") or []:
        if not isinstance(host, str):
            continue
        text = host.strip()
        if not text:
            continue
        if "://" in text:
            add_uri(text)
        elif ":" in text:
            add_uri(f"bolt://{text}")
        else:
            add_uri(f"bolt://{text}:7687")
    add_uri(data.get("internal_bolt") if isinstance(data.get("internal_bolt"), str) else None)
    add_uri(data.get("external_bolt") if isinstance(data.get("external_bolt"), str) else None)
    add_uri(data.get("bolt_uri") if isinstance(data.get("bolt_uri"), str) else None)
    return uris
