"""OpenSearch environment variable names (``OPENSEARCH_*``, legacy ``SOLOMON_OPENSEARCH_*``)."""

from __future__ import annotations

from solomon.infra.env_compat import env_first


def opensearch_env(suffix: str) -> str | None:
    """Read ``OPENSEARCH_{suffix}``, falling back to ``SOLOMON_OPENSEARCH_{suffix}``."""
    return env_first(f"OPENSEARCH_{suffix}", f"SOLOMON_OPENSEARCH_{suffix}")
