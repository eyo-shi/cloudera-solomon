"""OpenSearch external connection tests (no live cluster required)."""

from __future__ import annotations

from types import SimpleNamespace

from solomon.tools.opensearch import (
    OpenSearchIndexTool,
    OpenSearchKeywordSearchTool,
    OpenSearchPingTool,
    OpenSearchVectorSearchTool,
)
from solomon.transport import config as cfg_mod


def test_opensearch_config_not_configured(monkeypatch) -> None:
    for key in (
        "SOLOMON_OPENSEARCH_CONNECTION_NAME",
        "SOLOMON_OPENSEARCH_ENDPOINT",
        "SOLOMON_OPENSEARCH_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    assert cfg_mod.get_opensearch_config() is None


def test_opensearch_config_from_endpoint_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "SOLOMON_OPENSEARCH_ENDPOINT", "https://css.example.com:9200"
    )
    monkeypatch.setenv("SOLOMON_OPENSEARCH_NAMESPACE", "myproject")
    config = cfg_mod.get_opensearch_config()
    assert config is not None
    assert config.host == "css.example.com"
    assert config.port == 9200
    assert config.scheme == "https"
    assert config.namespace == "myproject"
    assert config.index_name == "myproject-datasets"


def test_opensearch_config_from_data_connection(monkeypatch) -> None:
    monkeypatch.setenv("SOLOMON_OPENSEARCH_CONNECTION_NAME", "css-prod")
    conn = SimpleNamespace(
        type="opensearch",
        name="css-prod",
        parameters={
            "endpoint": "https://css.internal.example:9200",
            "namespace": "solomon",
            "username": "admin",
            "password": "secret",
        },
    )
    monkeypatch.setattr(cfg_mod, "_cml_get_connection", lambda name: conn)
    config = cfg_mod.get_opensearch_config()
    assert config is not None
    assert config.host == "css.internal.example"
    assert config.connection_name == "css-prod"
    assert config.username == "admin"


def test_opensearch_tools_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("SOLOMON_OPENSEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("SOLOMON_OPENSEARCH_HOST", raising=False)

    kw = OpenSearchKeywordSearchTool().run(user_ctx=None, query="sales", top_k=3)
    assert kw["status"] == "error"
    assert kw["error_code"] == "OPENSEARCH_NOT_CONFIGURED"

    vec = OpenSearchVectorSearchTool().run(user_ctx=None, query="sales", top_k=3)
    assert vec["error_code"] == "OPENSEARCH_NOT_CONFIGURED"

    ping = OpenSearchPingTool().run(user_ctx=None)
    assert ping["error_code"] == "OPENSEARCH_NOT_CONFIGURED"

    idx = OpenSearchIndexTool().run(
        user_ctx=None,
        fq_name="iceberg.demo.sales",
        dataset={"name": "sales"},
    )
    assert idx["status"] == "ok"
    assert idx["skipped"] is True
