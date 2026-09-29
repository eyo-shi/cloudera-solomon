"""Trino environment variable names (``TRINO_*``, legacy ``SOLOMON_TRINO_*``)."""

from __future__ import annotations

from solomon.infra.env_compat import env_first


def trino_env(suffix: str) -> str | None:
    """Read ``TRINO_{suffix}``, falling back to ``SOLOMON_TRINO_{suffix}``."""
    return env_first(f"TRINO_{suffix}", f"SOLOMON_TRINO_{suffix}")
