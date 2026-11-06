"""会話セッション API (`/api/sessions/*`)。

ブラウザリロード時に会話履歴 + entity_memory を復元するために使う。
インメモリ実装なのでプロセス再起動で全て消える (デモ想定)。
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from solomon.api.auth import get_user_context
from solomon.api.state import get_store
from solomon.transport.user_context import UserContext

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/{session_id}")
def get_session(
    session_id: str,
    user_ctx: Annotated[UserContext, Depends(get_user_context)],
) -> dict[str, Any]:
    # 他人のセッションは存在しない扱い (404) にして、ID の有無も漏らさない
    sess = get_store().get_session_for_user(session_id, user_ctx.user_name)
    if sess is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"No session with id={session_id}",
            },
        )
    return {
        "session_id": sess.session_id,
        "user_name": sess.user_name,
        "created_at": sess.created_at,
        "turns": [
            {
                "turn_id": t.turn_id,
                "prompt": t.prompt,
                "response_markdown": t.response_markdown,
                "artifact_ids": t.artifact_ids,
                "error_code": t.error_code,
                "created_at": t.created_at,
            }
            for t in sess.turns
        ],
        "entity_memory": sess.entity_memory,
    }
