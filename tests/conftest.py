"""Shared pytest fixtures for API tests."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from solomon.api.main import create_app


@pytest.fixture(autouse=True)
def _no_workload_jwt(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """実行マシンの ``/tmp/jwt`` (CML Workbench) をテストに漏らさない。

    CAI の API キー未設定時は ``/tmp/jwt`` にフォールバックするため、
    既定では存在しないパスを指す。必要なテストは setenv で上書きする。
    """
    monkeypatch.setenv("SOLOMON_CML_JWT_PATH", str(tmp_path / "no-jwt"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as c:
        yield c
