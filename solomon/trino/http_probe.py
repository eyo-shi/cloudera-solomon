"""Lightweight Trino coordinator HTTP readiness checks."""

from __future__ import annotations

import urllib.error
import urllib.request


def probe_trino_info(url: str, *, timeout: float = 3.0) -> tuple[bool, str | None]:
    """Return (ok, error_message). Trino requires ``Accept: application/json``."""
    probe = f"{url.rstrip('/')}/v1/info"
    request = urllib.request.Request(
        probe,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if resp.status < 500:
                return True, None
            return False, f"{probe}: HTTP status {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"{probe}: HTTP Error {exc.code}: {exc.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"{probe}: {exc}"
