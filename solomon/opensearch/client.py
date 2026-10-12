"""External OpenSearch client builder."""

from __future__ import annotations

from typing import Any

from solomon.transport.config import OpenSearchConfig
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)


def build_client(config: OpenSearchConfig) -> Any:
    """Data Hub 上の OpenSearch クラスタへ接続する opensearch-py クライアント。"""
    try:
        from opensearchpy import OpenSearch  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "opensearch-py is not installed. Add it to project dependencies."
        ) from exc

    http_auth = None
    if config.username and config.password:
        http_auth = (config.username, config.password)

    client_kwargs: dict[str, Any] = {
        "hosts": [{"host": config.host, "port": config.port}],
        "http_auth": http_auth,
        "use_ssl": config.scheme == "https",
        "verify_certs": config.verify_ssl,
        "ssl_show_warn": False,
    }
    prefix = (getattr(config, "url_prefix", None) or "").strip()
    if prefix:
        client_kwargs["url_prefix"] = prefix if prefix.startswith("/") else f"/{prefix}"
    return OpenSearch(**client_kwargs)


def ping(config: OpenSearchConfig, *, probe_index: str | None = None) -> bool:
    """外部 OpenSearch クラスタへの接続確認。

    Knox + Ranger では ``_cluster/health`` が 403 でも ``inspection-*`` の
    read は許可されることがあるため、デモ index の ``_count`` を優先する。
    """
    try:
        client = build_client(config)
        index = (probe_index or "").strip()
        if index:
            client.count(index=index)
            return True
        health = client.cluster.health()
        if isinstance(health, dict) and health.get("cluster_name"):
            return True
        return bool(client.ping())
    except Exception as exc:  # noqa: BLE001
        _logger.debug("opensearch.ping_failed", error=str(exc), host=config.host)
        return False


def ping_inspection(config: OpenSearchConfig) -> bool:
    """Bronze ``inspection-*`` 向けの到達確認（Search タブ用）。"""
    from solomon.opensearch.inspection_indices import inspection_index_name

    if ping(config, probe_index=inspection_index_name("vb")):
        return True
    from solomon.opensearch.inspection_indices import inspection_index_pattern

    try:
        client = build_client(config)
        client.count(index=inspection_index_pattern())
        return True
    except Exception as exc:  # noqa: BLE001
        _logger.debug(
            "opensearch.ping_inspection_failed",
            error=str(exc),
            host=config.host,
        )
        return False


__all__ = ["build_client", "ping", "ping_inspection"]
