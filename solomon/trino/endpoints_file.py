"""Shared Trino HTTP endpoints written by warehouse-launcher for Solomon."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from solomon.trino.env import trino_env

_ENDPOINTS_REL = Path(".solomon") / "trino_endpoints.json"


def _project_dir() -> Path:
    for key in ("CDSW_PROJECT_DIR", "CML_PROJECT_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw)
    # CML Workbench sessions usually cwd=/home/cdsw even when env is unset.
    if Path("/home/cdsw").is_dir():
        return Path("/home/cdsw")
    return Path.cwd()


def endpoints_file_path() -> Path:
    override = (trino_env("ENDPOINTS_FILE") or "").strip()
    if override:
        return Path(override)
    return _project_dir() / _ENDPOINTS_REL


def write_endpoints(payload: dict[str, Any]) -> Path:
    path = endpoints_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_http_endpoints() -> dict[str, Any]:
    path = endpoints_file_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_http_hosts() -> list[str]:
    """Return host:port strings suitable for internal Trino HTTP."""
    data = load_http_endpoints()
    hosts: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        text = (raw or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        hosts.append(text)

    for host in data.get("http_hosts") or []:
        if isinstance(host, str):
            add(host)
    internal = data.get("internal_http")
    if isinstance(internal, str):
        from urllib.parse import urlparse

        parsed = urlparse(internal)
        if parsed.hostname:
            port = parsed.port or 8080
            add(f"{parsed.hostname}:{port}")

    return hosts
