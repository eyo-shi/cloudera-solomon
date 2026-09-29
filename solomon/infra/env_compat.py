"""Environment variable lookup with legacy ``SOLOMON_*`` fallbacks."""

from __future__ import annotations

import os


def env_first(*names: str) -> str | None:
    """Return the first non-empty env value among ``names``."""
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        text = raw.strip()
        if text:
            return text
    return None
