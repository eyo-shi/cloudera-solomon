"""Trino Basic vs JWT auth selection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from solomon.tools._trino_client import _use_trino_basic_auth, trino_connection_for_user
from solomon.transport.config import TrinoConfig


def test_use_trino_basic_auth_auto() -> None:
    cfg = TrinoConfig(host="h", password="secret")
    assert _use_trino_basic_auth(cfg) is True
    cfg_jwt = TrinoConfig(host="h", auth_mode="jwt", password="secret")
    assert _use_trino_basic_auth(cfg_jwt) is False
    cfg_none = TrinoConfig(host="h")
    assert _use_trino_basic_auth(cfg_none) is False


def test_trino_connection_basic_without_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TrinoConfig(
        host="trino.example.com",
        port=443,
        service_user="svc",
        password="pass",
        auth_mode="basic",
    )
    monkeypatch.setattr(
        "solomon.tools._trino_client.get_trino_config",
        lambda: cfg,
    )
    mock_connect = MagicMock()
    monkeypatch.setattr("solomon.tools._trino_client.trino.dbapi.connect", mock_connect)

    ctx = SimpleNamespace(user_name="browser_user", knox_jwt=None, request_id="r1")
    result = trino_connection_for_user(ctx)

    assert result is mock_connect.return_value
    mock_connect.assert_called_once()
    kwargs = mock_connect.call_args.kwargs
    assert kwargs["user"] == "svc"
    from trino.auth import BasicAuthentication

    assert isinstance(kwargs["auth"], BasicAuthentication)
