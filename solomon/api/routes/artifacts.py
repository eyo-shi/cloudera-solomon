"""ResultPane タブの成果物 API (`/api/artifacts/*`)。

Wish の SSE で ``event: artifact`` として通知した ``artifact_id`` を、UI が
中央ペインで再表示するときに叩く。実際のコンテンツ (行データ / iframe URL /
markdown) は artifact.type ごとに ``ref`` の中身が異なる。
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from solomon.api.auth import get_user_context
from solomon.api.state import get_store
from solomon.transport.user_context import UserContext

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
def get_artifact(
    artifact_id: str,
    user_ctx: Annotated[UserContext, Depends(get_user_context)],
) -> dict[str, Any]:
    # 他人のセッションで作られた成果物 (SQL・行データ等) は存在しない扱い
    art = get_store().get_artifact_for_user(artifact_id, user_ctx.user_name)
    if art is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ARTIFACT_NOT_FOUND",
                "message": f"No artifact with id={artifact_id}",
            },
        )
    return {
        "id": art.artifact_id,
        "type": art.type,
        "ref": art.ref,
        "session_id": art.session_id,
        "created_at": art.created_at,
    }
