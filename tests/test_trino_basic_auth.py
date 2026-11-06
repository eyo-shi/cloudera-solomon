"""Trino Basic vs JWT auth selection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from solomon.tools._trino_client import (
    _use_trino_basic_auth,
    _use_trino_impersonation,
    map_trino_error,
    trino_connection_for_user,
)
from solomon.transport.config import TrinoConfig


@pytest.fixture
def not_cml_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CDSW_APP_PORT", raising=False)
    monkeypatch.delenv("TASK_TYPE", raising=False)


def _basic_cfg(**overrides: object) -> TrinoConfig:
    kwargs: dict[str, object] = dict(
        host="trino.example.com",
        port=443,
        service_user="svc",
        password="pass",
        auth_mode="basic",
    )
    kwargs.update(overrides)
    return TrinoConfig(**kwargs)  # type: ignore[arg-type]


def _connect(monkeypatch: pytest.MonkeyPatch, cfg: TrinoConfig, user: str):
    monkeypatch.setattr("solomon.tools._trino_client.get_trino_config", lambda: cfg)
    mock_connect = MagicMock()
    monkeypatch.setattr("solomon.tools._trino_client.trino.dbapi.connect", mock_connect)
    ctx = SimpleNamespace(user_name=user, knox_jwt=None, request_id="r1")
    return trino_connection_for_user(ctx), mock_connect


def test_use_trino_basic_auth_auto() -> None:
    cfg = TrinoConfig(host="h", password="secret")
    assert _use_trino_basic_auth(cfg) is True
    cfg_jwt = TrinoConfig(host="h", auth_mode="jwt", password="secret")
    assert _use_trino_basic_auth(cfg_jwt) is False
    cfg_none = TrinoConfig(host="h")
    assert _use_trino_basic_auth(cfg_none) is False


def test_trino_connection_basic_without_jwt(
    monkeypatch: pytest.MonkeyPatch, not_cml_app: None
) -> None:
    result, mock_connect = _connect(monkeypatch, _basic_cfg(), "browser_user")

    assert result is mock_connect.return_value
    mock_connect.assert_called_once()
    kwargs = mock_connect.call_args.kwargs
    assert kwargs["user"] == "svc"
    from trino.auth import BasicAuthentication

    assert isinstance(kwargs["auth"], BasicAuthentication)


def test_impersonation_auto_follows_cml_app_mode(
    monkeypatch: pytest.MonkeyPatch, not_cml_app: None
) -> None:
    cfg = _basic_cfg()
    assert _use_trino_impersonation(cfg) is False
    monkeypatch.setenv("CDSW_APP_PORT", "8090")
    assert _use_trino_impersonation(cfg) is True
    assert _use_trino_impersonation(_basic_cfg(impersonation="off")) is False


def test_impersonation_runs_query_as_signed_in_user(
    monkeypatch: pytest.MonkeyPatch, not_cml_app: None
) -> None:
    """サービスアカウントで認証し、Ranger にはログインユーザーとして判定させる。"""
    result, mock_connect = _connect(
        monkeypatch, _basic_cfg(impersonation="on"), "alice"
    )
    assert result is mock_connect.return_value
    kwargs = mock_connect.call_args.kwargs
    assert kwargs["user"] == "alice"
    assert kwargs["auth"]._username == "svc"


def test_impersonation_in_cml_app_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDSW_APP_PORT", "8090")
    _result, mock_connect = _connect(monkeypatch, _basic_cfg(), "alice")
    assert mock_connect.call_args.kwargs["user"] == "alice"


def test_impersonation_refuses_unknown_user(
    monkeypatch: pytest.MonkeyPatch, not_cml_app: None
) -> None:
    # ユーザーが分からないとき、サービスアカウントの権限で代わりに実行しない
    result, mock_connect = _connect(
        monkeypatch, _basic_cfg(impersonation="on"), "anonymous"
    )
    assert isinstance(result, dict)
    assert result["error_code"] == "AUTH_MISSING"
    mock_connect.assert_not_called()


def test_impersonation_needs_service_user(
    monkeypatch: pytest.MonkeyPatch, not_cml_app: None
) -> None:
    result, mock_connect = _connect(
        monkeypatch, _basic_cfg(impersonation="on", service_user=None), "alice"
    )
    assert isinstance(result, dict)
    assert result["error_code"] == "TRINO_NOT_CONFIGURED"
    mock_connect.assert_not_called()


def test_impersonation_off_uses_service_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CDSW_APP_PORT", "8090")
    _result, mock_connect = _connect(
        monkeypatch, _basic_cfg(impersonation="off"), "alice"
    )
    assert mock_connect.call_args.kwargs["user"] == "svc"


def test_impersonation_denied_error_explains_ranger_policy() -> None:
    e = Exception("Access Denied: User svc cannot impersonate user alice")
    out = map_trino_error(e, "SELECT 1")
    assert out["error_code"] == "PERM_UNKNOWN"
    assert "impersonate" in out["message"]
    assert "TRINO_IMPERSONATION=off" in out["message"]
