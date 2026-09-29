"""Deploy / startup bootstrap for the Semantic Search index."""

from __future__ import annotations

from solomon.opensearch.client import build_client, ping
from solomon.opensearch.indexer import ensure_index
from solomon.transport.config import OpenSearchConfig, get_opensearch_config
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)


def bootstrap_search_index(config: OpenSearchConfig | None = None) -> bool:
    """Create the search index (e.g. ``solomon-datasets``) when OpenSearch is reachable.

    Idempotent: no-op if the index already exists. Returns True when the index
    is ready, False when OpenSearch is not configured or not yet reachable.
    """
    if config is None:
        config = get_opensearch_config()
    if config is None:
        _logger.info("opensearch.bootstrap.skipped", reason="not_configured")
        return False
    if not ping(config):
        _logger.warning(
            "opensearch.bootstrap.skipped",
            reason="ping_failed",
            host=config.host,
            port=config.port,
        )
        return False
    client = build_client(config)
    ensure_index(client, config)
    _logger.info("opensearch.bootstrap.index_ready", index=config.index_name)
    return True
