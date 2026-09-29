"""Trino env naming (TRINO_* with SOLOMON_TRINO_* legacy fallback)."""

from __future__ import annotations

import pytest

from solomon.trino.env import trino_env


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "TRINO_HOST",
        "SOLOMON_TRINO_HOST",
        "TRINO_CATALOG",
        "SOLOMON_TRINO_CATALOG",
    ):
        monkeypatch.delenv(key, raising=False)


def test_prefers_new_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRINO_HOST", "new.example.com")
    monkeypatch.setenv("SOLOMON_TRINO_HOST", "legacy.example.com")
    assert trino_env("HOST") == "new.example.com"


def test_legacy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_TRINO_CATALOG", "legacy_catalog")
    assert trino_env("CATALOG") == "legacy_catalog"
