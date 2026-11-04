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


def _is_authorization_error(exc: Exception) -> bool:
    """HTTP 403 (認証済み・権限不足)。401 (認証失敗) は含めない。"""
    try:
        from opensearchpy.exceptions import AuthorizationException  # type: ignore
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, AuthorizationException)


def ping(config: OpenSearchConfig, *, probe_index: str | None = None) -> bool:
    """外部 OpenSearch クラスタへの接続確認。"""
    try:
        client = build_client(config)
        index = (probe_index or "").strip()
        if index:
            client.count(index=index)
            return True
        try:
            health = client.cluster.health()
        except Exception as exc:  # noqa: BLE001
            if _is_authorization_error(exc):
                # 認証は通ったが cluster:monitor 権限が無い (Ranger 管理の
                # Semantic Search で一般的)。到達性と認証は確認できている。
                _logger.debug(
                    "opensearch.ping_cluster_monitor_forbidden", host=config.host
                )
                return True
            raise
        if isinstance(health, dict) and health.get("cluster_name"):
            return True
        return bool(client.ping())
    except Exception as exc:  # noqa: BLE001
        _logger.debug("opensearch.ping_failed", error=str(exc), host=config.host)
        return False


__all__ = ["build_client", "ping"]
