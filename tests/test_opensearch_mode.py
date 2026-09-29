"""OpenSearch mode switching (datahub vs CML launcher)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from solomon.opensearch.endpoints_file import write_endpoints
from solomon.transport import config as cfg_mod


@pytest.fixture(autouse=True)
def _clean_opensearch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SOLOMON_OPENSEARCH_MODE",
        "SOLOMON_OPENSEARCH_CONNECTION_NAME",
        "SOLOMON_OPENSEARCH_ENDPOINT",
        "SOLOMON_OPENSEARCH_HOST",
        "SOLOMON_OPENSEARCH_PORT",
        "SOLOMON_OPENSEARCH_SCHEME",
        "SOLOMON_OPENSEARCH_VERIFY_SSL",
        "SOLOMON_OPENSEARCH_NAMESPACE",
        "SOLOMON_OPENSEARCH_INDEX",
        "SOLOMON_OPENSEARCH_ENDPOINTS_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cfg_mod, "_cmldata", None)
    monkeypatch.setattr(cfg_mod, "_cmldata_import_attempted", True)


def test_datahub_mode_uses_data_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLOMON_OPENSEARCH_MODE", "datahub")
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


def test_cml_mode_ignores_data_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLOMON_OPENSEARCH_MODE", "cml")
    conn = SimpleNamespace(
        type="opensearch",
        name="css-prod",
        parameters={"host": "css.example.com", "port": 443},
    )
    monkeypatch.setattr(cfg_mod, "_cml_list_connections", lambda: [conn])
    assert cfg_mod.get_opensearch_config() is None


def test_cml_mode_reads_endpoints_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SOLOMON_OPENSEARCH_MODE", "cml")
    endpoints = tmp_path / "opensearch_endpoints.json"
    monkeypatch.setenv("SOLOMON_OPENSEARCH_ENDPOINTS_FILE", str(endpoints))
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


def test_cml_mode_explicit_endpoint_overrides_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SOLOMON_OPENSEARCH_MODE", "cml")
    monkeypatch.setenv("SOLOMON_OPENSEARCH_ENDPOINT", "http://override:9200")
    endpoints = tmp_path / "opensearch_endpoints.json"
    monkeypatch.setenv("SOLOMON_OPENSEARCH_ENDPOINTS_FILE", str(endpoints))
    write_endpoints({"http_hosts": ["10.0.0.99:9200"]})
    cfg = cfg_mod.get_opensearch_config()
    assert cfg is not None
    assert cfg.host == "override"
