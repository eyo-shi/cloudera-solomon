"""Trino environment variable names (``TRINO_*``, legacy ``SOLOMON_TRINO_*``)."""

from __future__ import annotations

from solomon.infra.env_compat import env_first


def trino_env(suffix: str) -> str | None:
    """Read ``TRINO_{suffix}``, falling back to ``SOLOMON_TRINO_{suffix}``."""
    return env_first(f"TRINO_{suffix}", f"SOLOMON_TRINO_{suffix}")


def trino_endpoint_url() -> str | None:
    """Coordinator の FQDN または ``https://host:443`` 形式の URL。"""
    return env_first(
        "TRINO_HOST",
        "SOLOMON_TRINO_HOST",
        "TRINO_ENDPOINT",
        "SOLOMON_TRINO_ENDPOINT",
        "TRINO_URL",
        "SOLOMON_TRINO_URL",
    )
