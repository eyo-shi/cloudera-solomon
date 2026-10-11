"""OpenSearch environment variable names (``OPENSEARCH_*``, legacy ``SOLOMON_OPENSEARCH_*``)."""

from __future__ import annotations

from solomon.infra.env_compat import env_first


def opensearch_env(suffix: str) -> str | None:
    """Read ``OPENSEARCH_{suffix}``, falling back to ``SOLOMON_OPENSEARCH_{suffix}``."""
    return env_first(f"OPENSEARCH_{suffix}", f"SOLOMON_OPENSEARCH_{suffix}")


def opensearch_endpoint_url() -> str | None:
    """CDE の ``OPENSEARCH_URL`` と Solomon の ``OPENSEARCH_ENDPOINT`` を同一視する。"""
    return env_first(
        "OPENSEARCH_ENDPOINT",
        "SOLOMON_OPENSEARCH_ENDPOINT",
        "OPENSEARCH_HOST",
        "SOLOMON_OPENSEARCH_HOST",
        "OPENSEARCH_URL",
        "SOLOMON_OPENSEARCH_URL",
    )


def opensearch_username() -> str | None:
    return env_first(
        "OPENSEARCH_USERNAME",
        "SOLOMON_OPENSEARCH_USERNAME",
        "OPENSEARCH_USER",
        "SOLOMON_OPENSEARCH_USER",
    )
