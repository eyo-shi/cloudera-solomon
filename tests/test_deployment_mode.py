"""Shared internal / external deployment mode parsing."""

from __future__ import annotations

import pytest

from solomon.infra.deployment_mode import deployment_mode, is_internal_mode


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "internal"),
        ("internal", "internal"),
        ("cml", "internal"),
        ("external", "external"),
        ("datahub", "external"),
    ],
)
def test_deployment_mode(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: str) -> None:
    monkeypatch.delenv("TEST_MODE", raising=False)
    if raw is not None:
        monkeypatch.setenv("TEST_MODE", raw)
    assert deployment_mode("TEST_MODE", default="internal") == expected
    assert is_internal_mode("TEST_MODE", default="internal") == (expected == "internal")
