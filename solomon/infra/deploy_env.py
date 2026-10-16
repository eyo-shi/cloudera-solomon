"""Post-deploy 設定をプロジェクト内ファイルから ``os.environ`` へマージする。

CML Project Settings への手入力の代わりに、永続ディスク上の dotenv ファイルを
Application 起動時に読む。AMP 再 Deploy 後も ``.solomon/deploy.env`` が残っていれば
設定を復元できる。

優先度 (既存の値を上書きするか):

* 既定: **空 / 未設定** のキーのみファイルで埋める (AMP フォームの空文字も上書き対象)。
* ``SOLOMON_DEPLOY_ENV_OVERRIDE=true`` のとき: ファイルに書かれたキーは **非空なら**
  既存 env も上書き (プラットフォーム注入キーは除外)。

読み込み順 (後勝ち):

1. ``.solomon/deploy.env``
2. ``.solomon/secrets.env`` (任意・Git 除外推奨)

``SOLOMON_DEPLOY_ENV_FILES`` が設定されていればカンマ区切りパス (プロジェクト root 相対)
で上書き。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

_DEFAULT_REL_PATHS = (
    ".solomon/deploy.env",
    ".solomon/secrets.env",
)

# CML / プロセス基盤 — ファイルから変更しない
_PROTECTED_EXACT = frozenset(
    {
        "PATH",
        "HOME",
        "PWD",
        "USER",
        "SHELL",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "HOSTNAME",
        "TASK_TYPE",
        "CDSW_APP_PORT",
        "CDSW_PROJECT",
        "CDSW_PROJECT_ID",
        "CDSW_API_URL",
        "CDSW_DOMAIN",
        "CDSW_USERNAME",
        "CDSW_WORKSPACE_ID",
        "CML_PROJECT_DIR",
        "CDSW_PROJECT_DIR",
    }
)

_PROTECTED_PREFIXES = (
    "CDSW_",
    "CML_",
    "KUBERNETES_",
)


@dataclass
class DeployEnvLoadResult:
    """1 回の bootstrap の結果 (ログ / テスト用)。"""

    files_attempted: list[str] = field(default_factory=list)
    files_loaded: list[str] = field(default_factory=list)
    keys_applied: list[str] = field(default_factory=list)
    keys_skipped_protected: list[str] = field(default_factory=list)
    keys_skipped_existing: list[str] = field(default_factory=list)
    override_mode: bool = False


_bootstrap_done = False


def project_dir() -> Path:
    """CML Workbench 上のプロジェクト root。"""
    for key in ("CDSW_PROJECT_DIR", "CML_PROJECT_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw)
    if Path("/home/cdsw").is_dir():
        return Path("/home/cdsw")
    return Path.cwd()


def default_deploy_env_paths() -> list[Path]:
    """既定の deploy env ファイルパス (存在しなくてよい)。"""
    root = project_dir()
    custom = (os.environ.get("SOLOMON_DEPLOY_ENV_FILES") or "").strip()
    if custom:
        rels = [p.strip() for p in custom.split(",") if p.strip()]
        return [root / rel for rel in rels]
    return [root / rel for rel in _DEFAULT_REL_PATHS]


def _is_protected_key(key: str) -> bool:
    if key in _PROTECTED_EXACT:
        return True
    return any(key.startswith(prefix) for prefix in _PROTECTED_PREFIXES)


def _env_effective_empty(key: str) -> bool:
    val = os.environ.get(key)
    return val is None or not str(val).strip()


def parse_dotenv(text: str) -> dict[str, str]:
    """最小限の dotenv パーサ (# コメント / export 接頭辞対応)。"""
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            continue
        key, _, raw_val = stripped.partition("=")
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if not val:
            continue
        out[key] = val
    return out


def _merge_file_into_environ(
    path: Path,
    *,
    override_existing: bool,
    result: DeployEnvLoadResult,
) -> None:
    result.files_attempted.append(str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _logger.debug("deploy_env.file_missing_or_unreadable", path=str(path), error=str(exc))
        return

    parsed = parse_dotenv(text)
    if not parsed:
        result.files_loaded.append(str(path))
        return

    result.files_loaded.append(str(path))
    for key, value in parsed.items():
        if _is_protected_key(key):
            result.keys_skipped_protected.append(key)
            continue
        if not override_existing and not _env_effective_empty(key):
            result.keys_skipped_existing.append(key)
            continue
        os.environ[key] = value
        result.keys_applied.append(key)


def bootstrap_deploy_env(*, force: bool = False) -> DeployEnvLoadResult:
    """deploy env ファイルを読み、``os.environ`` にマージする (プロセス 1 回のみ)。"""
    global _bootstrap_done
    result = DeployEnvLoadResult(
        override_mode=_truthy(os.environ.get("SOLOMON_DEPLOY_ENV_OVERRIDE"))
    )
    if _bootstrap_done and not force:
        return result

    for path in default_deploy_env_paths():
        _merge_file_into_environ(
            path,
            override_existing=result.override_mode,
            result=result,
        )

    _bootstrap_done = True
    if result.files_loaded:
        _logger.info(
            "deploy_env.loaded",
            files=result.files_loaded,
            keys_applied=len(result.keys_applied),
            override=result.override_mode,
        )
    return result


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def reset_deploy_env_bootstrap_for_tests() -> None:
    """テスト用: 2 回目以降の bootstrap を許可する。"""
    global _bootstrap_done
    _bootstrap_done = False


__all__ = [
    "DeployEnvLoadResult",
    "bootstrap_deploy_env",
    "default_deploy_env_paths",
    "parse_dotenv",
    "project_dir",
    "reset_deploy_env_bootstrap_for_tests",
]
