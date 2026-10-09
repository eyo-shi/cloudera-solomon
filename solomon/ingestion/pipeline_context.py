"""Ingestion Crew 実行中の直前タスク出力 (guardrail フォールバック用)。"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

from solomon.ingestion.models import (
    ConflictAndPermissionsResult,
    ProposeSchemaAndNameResult,
)
from solomon.transport.guardrail import parse_guardrail_model

_propose: ContextVar[Optional[ProposeSchemaAndNameResult]] = ContextVar(
    "ingestion_last_propose", default=None
)
_check: ContextVar[Optional[ConflictAndPermissionsResult]] = ContextVar(
    "ingestion_last_check", default=None
)


def reset_ingestion_pipeline_context() -> None:
    _propose.set(None)
    _check.set(None)


def record_ingestion_task_output(task_index: int, output: Any) -> None:
    """task_callback から propose / check の出力を保持する。"""
    if task_index == 3:
        model, _ = parse_guardrail_model(output, ProposeSchemaAndNameResult)
        if model is not None:
            _propose.set(model)
    elif task_index == 4:
        model, _ = parse_guardrail_model(output, ConflictAndPermissionsResult)
        if model is not None:
            _check.set(model)


def get_last_propose() -> Optional[ProposeSchemaAndNameResult]:
    return _propose.get()


def get_last_check() -> Optional[ConflictAndPermissionsResult]:
    return _check.get()


__all__ = [
    "reset_ingestion_pipeline_context",
    "record_ingestion_task_output",
    "get_last_propose",
    "get_last_check",
]
