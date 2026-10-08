"""CML / headless 環境向け CrewAI ランタイム設定。"""
from __future__ import annotations

import os


def configure_crewai_runtime() -> None:
    """対話式 tracing プロンプトと telemetry を抑止する。"""
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    os.environ.setdefault("CREWAI_DISABLE_TRACING", "true")
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    # Workbench Application では stdin が無く tracing 確認プロンプトでハングする。
    os.environ.setdefault("CREWAI_TESTING", "true")
    os.environ.setdefault("CREWAI_VERBOSE", "false")


__all__ = ["configure_crewai_runtime"]
