"""OpenSearch mode switching (internal vs external)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from solomon.opensearch.endpoints_file import write_endpoints
from solomon.opensearch.mode import is_internal_opensearch_mode, opensearch_mode
from solomon.transport import config as cfg_mod

_OPENSEARCH_ENV_KEYS = (
    "OPENSEARCH_MODE",
    "SOLOMON_OPENSEARCH_MODE",
    "OPENSEARCH_CONNECTION_NAME",
    "SOLOMON_OPENSEARCH_CONNECTION_NAME",
    "OPENSEARCH_ENDPOINT",
    "SOLOMON_OPENSEARCH_ENDPOINT",
    "OPENSEARCH_HOST",
    "SOLOMON_OPENSEARCH_HOST",
    "OPENSEARCH_PORT",
    "SOLOMON_OPENSEARCH_PORT",
    "OPENSEARCH_SCHEME",
    "SOLOMON_OPENSEARCH_SCHEME",
    "OPENSEARCH_VERIFY_SSL",
    "SOLOMON_OPENSEARCH_VERIFY_SSL",
    "OPENSEARCH_NAMESPACE",
    "SOLOMON_OPENSEARCH_NAMESPACE",
    "OPENSEARCH_INDEX",
    "SOLOMON_OPENSEARCH_INDEX",
    "OPENSEARCH_ENDPOINTS_FILE",
    "SOLOMON_OPENSEARCH_ENDPOINTS_FILE",
)


@pytest.fixture(autouse=True)
def _clean_opensearch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _OPENSEARCH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cfg_mod, "_cmldata", None)
    monkeypatch.setattr(cfg_mod, "_cmldata_import_attempted", True)


def test_default_mode_is_internal() -> None:
    assert opensearch_mode() == "internal"
    assert is_internal_opensearch_mode()


def test_legacy_mode_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_OPENSEARCH_MODE", "cml")
    assert opensearch_mode() == "internal"
    monkeypatch.delenv("SOLOMON_OPENSEARCH_MODE", raising=False)
    monkeypatch.setenv("SOLOMON_OPENSEARCH_MODE", "datahub")
    assert opensearch_mode() == "external"


def test_legacy_connection_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_OPENSEARCH_MODE", "external")
    monkeypatch.setenv("SOLOMON_OPENSEARCH_ENDPOINT", "https://legacy.example.com:9200")
    cfg = cfg_mod.get_opensearch_config()
    assert cfg is not None
    assert cfg.host == "legacy.example.com"


def test_external_mode_uses_data_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSEARCH_MODE", "external")
    conn = SimpleNamespace(
        type="opensearch",
        name="css-prod",
        parameters={"host": "css.example.com", "port": 443, "scheme": "https"},
    )
    monkeypatch.setattr(cfg_mod, "_cml_list_connections", lambda: [conn])
    cfg = cfg_mod.get_opensearch_config()
    assert cfg is not None
    assert cfg.host == "css.example.com"
    assert cfg.scheme == "https"


def test_internal_mode_ignores_data_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSEARCH_MODE", "internal")
    conn = SimpleNamespace(
        type="opensearch",
        name="css-prod",
        parameters={"host": "css.example.com", "port": 443},
    )
    monkeypatch.setattr(cfg_mod, "_cml_list_connections", lambda: [conn])
    assert cfg_mod.get_opensearch_config() is None


def test_internal_mode_reads_endpoints_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OPENSEARCH_MODE", "internal")
    endpoints = tmp_path / "opensearch_endpoints.json"
    monkeypatch.setenv("OPENSEARCH_ENDPOINTS_FILE", str(endpoints))
    write_endpoints(
        {
            "internal_http": "http://cml-opensearch-demo.namespace:9200",
            "http_hosts": ["10.0.0.42:9200"],
        }
    )
    cfg = cfg_mod.get_opensearch_config()
    assert cfg is not None
    assert cfg.host == "10.0.0.42"
    assert cfg.port == 9200
    assert cfg.scheme == "http"
    assert cfg.verify_ssl is False


def test_internal_mode_explicit_endpoint_overrides_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OPENSEARCH_MODE", "internal")
    monkeypatch.setenv("OPENSEARCH_ENDPOINT", "http://override:9200")
    endpoints = tmp_path / "opensearch_endpoints.json"
    monkeypatch.setenv("OPENSEARCH_ENDPOINTS_FILE", str(endpoints))
    write_endpoints({"http_hosts": ["10.0.0.99:9200"]})
    cfg = cfg_mod.get_opensearch_config()
    assert cfg is not None
    assert cfg.host == "override"
