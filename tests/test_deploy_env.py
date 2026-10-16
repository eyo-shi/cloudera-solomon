"""deploy_env — dotenv マージと優先度。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from solomon.infra.deploy_env import (
    bootstrap_deploy_env,
    parse_dotenv,
    reset_deploy_env_bootstrap_for_tests,
)


def test_parse_dotenv_comments_and_export() -> None:
    text = """
# comment
export FOO=bar
BAZ="quoted"
EMPTY=
"""
    assert parse_dotenv(text) == {"FOO": "bar", "BAZ": "quoted"}


def test_bootstrap_fills_empty_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_deploy_env_bootstrap_for_tests()
    env_dir = tmp_path / ".solomon"
    env_dir.mkdir()
    (env_dir / "deploy.env").write_text(
        "SOLOMON_TEST_DEPLOY_A=from_file\nSOLOMON_TEST_DEPLOY_B=second\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CDSW_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("SOLOMON_TEST_DEPLOY_A", raising=False)
    monkeypatch.setenv("SOLOMON_TEST_DEPLOY_B", "already_set")
    monkeypatch.delenv("SOLOMON_DEPLOY_ENV_OVERRIDE", raising=False)

    result = bootstrap_deploy_env(force=True)

    assert os.environ.get("SOLOMON_TEST_DEPLOY_A") == "from_file"
    assert os.environ.get("SOLOMON_TEST_DEPLOY_B") == "already_set"
    assert "SOLOMON_TEST_DEPLOY_A" in result.keys_applied
    assert "SOLOMON_TEST_DEPLOY_B" in result.keys_skipped_existing


def test_bootstrap_override_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_deploy_env_bootstrap_for_tests()
    env_dir = tmp_path / ".solomon"
    env_dir.mkdir()
    (env_dir / "deploy.env").write_text(
        "SOLOMON_TEST_DEPLOY_C=from_file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CDSW_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("SOLOMON_TEST_DEPLOY_C", "old")
    monkeypatch.setenv("SOLOMON_DEPLOY_ENV_OVERRIDE", "true")

    bootstrap_deploy_env(force=True)

    assert os.environ.get("SOLOMON_TEST_DEPLOY_C") == "from_file"


def test_bootstrap_skips_protected_cdsW(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_deploy_env_bootstrap_for_tests()
    env_dir = tmp_path / ".solomon"
    env_dir.mkdir()
    (env_dir / "deploy.env").write_text(
        "CDSW_APP_PORT=9999\nSOLOMON_TEST_DEPLOY_D=ok\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CDSW_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CDSW_APP_PORT", "8080")

    result = bootstrap_deploy_env(force=True)

    assert os.environ.get("CDSW_APP_PORT") == "8080"
    assert os.environ.get("SOLOMON_TEST_DEPLOY_D") == "ok"
    assert "CDSW_APP_PORT" in result.keys_skipped_protected
