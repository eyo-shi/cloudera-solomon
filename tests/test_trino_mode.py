"""Trino mode switching (internal warehouse vs external CDW)."""

from __future__ import annotations

import pytest

from solomon.transport.config import get_trino_config
from solomon.trino.endpoints_file import write_endpoints
from solomon.trino.mode import is_internal_trino_mode, trino_mode

_TRINO_ENV_KEYS = (
    "TRINO_MODE",
    "SOLOMON_TRINO_MODE",
    "TRINO_HOST",
    "SOLOMON_TRINO_HOST",
    "TRINO_CONNECTION_NAME",
    "TRINO_ENDPOINT",
    "TRINO_ENDPOINTS_FILE",
    "SOLOMON_TRINO_ENDPOINTS_FILE",
)


@pytest.fixture(autouse=True)
def _clean_trino_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _TRINO_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_default_mode_is_internal() -> None:
    assert trino_mode() == "internal"
    assert is_internal_trino_mode()


def test_legacy_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_TRINO_MODE", "external")
    assert trino_mode() == "external"


def test_internal_mode_reads_endpoints_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRINO_MODE", "internal")
    endpoints = tmp_path / "trino_endpoints.json"
    monkeypatch.setenv("TRINO_ENDPOINTS_FILE", str(endpoints))
    write_endpoints(
        {
            "http_hosts": ["10.0.0.20:8080"],
            "internal_http": "http://cml-trino-demo.namespace:8080",
        }
    )
    cfg = get_trino_config()
    assert cfg is not None
    assert cfg.internal is True
    assert cfg.host == "10.0.0.20"
    assert cfg.port == 8080
    assert cfg.scheme == "http"
    assert cfg.catalog == "iceberg"


def test_external_mode_uses_env_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRINO_MODE", "external")
    monkeypatch.setenv("TRINO_HOST", "cdw.example.com")
    cfg = get_trino_config()
    assert cfg is not None
    assert cfg.internal is False
    assert cfg.host == "cdw.example.com"


def test_internal_mode_without_launcher_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRINO_MODE", "internal")
    assert get_trino_config() is None
