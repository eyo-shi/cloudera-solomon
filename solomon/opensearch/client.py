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


def ping(config: OpenSearchConfig) -> bool:
    """外部 OpenSearch クラスタへの接続確認。

    Knox CSS ゲートウェイはルートへの ``HEAD`` を 403 にすることがあるため、
    ``cluster.health`` (GET) を優先する。
    """
    try:
        client = build_client(config)
        health = client.cluster.health()
        if isinstance(health, dict) and health.get("cluster_name"):
            return True
        return bool(client.ping())
    except Exception as exc:  # noqa: BLE001
        _logger.debug("opensearch.ping_failed", error=str(exc), host=config.host)
        return False


__all__ = ["build_client", "ping"]
