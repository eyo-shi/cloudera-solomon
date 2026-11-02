"""Aggregated semantic context API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from solomon.semantic.context import get_semantic_context

router = APIRouter(prefix="/api/semantic", tags=["semantic"])


@router.get("/context")
def get_context() -> dict[str, Any]:
    """UI / 検証用の業務コンテキスト (秘密情報・SQL 本文は含めない)。"""
    return get_semantic_context().to_public_dict()
