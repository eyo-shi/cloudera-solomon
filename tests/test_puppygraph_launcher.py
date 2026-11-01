"""PuppyGraph launcher endpoints file (no Kubernetes)."""

from __future__ import annotations

import json

import pytest

from solomon.graph.config import get_graph_config
from solomon.graph.puppygraph_endpoints_file import load_bolt_uris, write_endpoints


def test_internal_config_from_endpoints_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("PUPPYGRAPH_MODE", "internal")
    path = tmp_path / "puppygraph_endpoints.json"
    monkeypatch.setenv("PUPPYGRAPH_ENDPOINTS_FILE", str(path))
    write_endpoints(
        {
            "bolt_uri": "bolt://10.0.0.50:7687",
            "bolt_hosts": ["10.0.0.50:7687"],
        }
    )
    cfg = get_graph_config()
    assert cfg is not None
    assert cfg.uri == "bolt://10.0.0.50:7687"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["bolt_uri"].startswith("bolt://")
    assert load_bolt_uris() == ["bolt://10.0.0.50:7687"]
