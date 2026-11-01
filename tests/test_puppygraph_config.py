"""PuppyGraph Bolt config from deploy env."""

from __future__ import annotations

import pytest

from solomon.graph.config import get_graph_config

_ENV_KEYS = (
    "PUPPYGRAPH_MODE",
    "PUPPYGRAPH_URI",
    "PUPPYGRAPH_BOLT_URI",
    "PUPPYGRAPH_USERNAME",
    "PUPPYGRAPH_PASSWORD",
    "PUPPYGRAPH_ENDPOINTS_FILE",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_default_mode_is_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    from solomon.graph.puppygraph_mode import puppygraph_mode

    assert puppygraph_mode() == "internal"
    assert get_graph_config() is None


def test_external_requires_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUPPYGRAPH_MODE", "external")
    assert get_graph_config() is None
    monkeypatch.setenv("PUPPYGRAPH_URI", "bolt://pg.example:7687")
    cfg = get_graph_config()
    assert cfg is not None
    assert cfg.uri == "bolt://pg.example:7687"
    assert cfg.username == "puppygraph"


def test_uri_without_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUPPYGRAPH_URI", "pg.internal:7687")
    cfg = get_graph_config()
    assert cfg is not None
    assert cfg.uri == "bolt://pg.internal:7687"
