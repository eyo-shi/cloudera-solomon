"""Setup probe API — UI が Deploy 後の設定不足を起動時に検出する。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from solomon.api.setup_checks import llm_not_configured_payload

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/llm")
def check_llm_setup() -> dict[str, str]:
    """LLM プロバイダが設定済みか確認。未設定なら HTTP 503 + SetupGuide ペイロード。"""
    detail = llm_not_configured_payload()
    if detail is not None:
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ok"}
