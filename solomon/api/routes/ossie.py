"""Ossie semantic dataset reference API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from solomon.semantic.store import read_dataset

router = APIRouter(prefix="/api/ossie", tags=["ossie"])


@router.get("/{name_or_fq:path}")
def get_ossie(name_or_fq: str) -> dict[str, Any]:
    """``catalog.schema.table`` または ``model.dataset`` 形式のキーで読む。"""
    key = (name_or_fq or "").strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "BAD_REQUEST", "message": "dataset key is required"},
        )
    result = read_dataset(key)
    if result.get("status") == "error":
        code = result.get("error_code", "OSSIE_NOT_FOUND")
        status = 404 if code == "OSSIE_NOT_FOUND" else 502
        raise HTTPException(status_code=status, detail=result)
    return result
