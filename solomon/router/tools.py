"""Router Crew 用 Tool 定義。

* :class:`EntityMemoryReadTool` — `solomon.api.state.InMemoryStore` から現在の
  セッションの ``entity_memory`` (last_table / last_dashboard_id / ...) を返す。
  IntentClassifierAgent が「そのテーブル」等の代名詞を解決するために使う。

* :class:`AnalyticsKickoffTool` — DispatcherAgent 用の補助 Tool。
  実際の Analytics 起動は Python 側 (wish SSE) が担当する。

**セキュリティ**: これらの Tool は Knox JWT / STS を LLM に露出させない。
UserContext は ContextVar から取り出し、Tool 引数には決して含めない。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from solomon.transport.errors import err, ok
from solomon.transport.logging import get_logger
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# EntityMemoryReadTool
# ------------------------------------------------------------------ #
class EntityMemoryReadArgs(BaseModel):
    session_id: str = Field(..., description="対象セッション ID (X-Solomon-Session-Id)")


class EntityMemoryReadTool(BaseSolomonTool):
    """会話セッションに保持された ``entity_memory`` スナップショットを返す。"""

    name: str = "entity_memory_read"
    description: str = (
        "Read the current chat session's entity memory (last_table, "
        "last_dashboard_id, last_s3_path, last_ossie_path, ...) so that "
        "you can resolve pronouns like 'そのテーブル' / 'that dashboard'."
    )
    args_schema: type[BaseModel] = EntityMemoryReadArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        session_id: str,
        **_: Any,
    ) -> dict[str, Any]:
        from solomon.api.state import get_store

        store = get_store()
        sess = store.get_session(session_id)
        if sess is None:
            return ok(
                {
                    "session_id": session_id,
                    "found": False,
                    "entity_memory": {},
                    "turn_count": 0,
                }
            )
        return ok(
            {
                "session_id": session_id,
                "found": True,
                "entity_memory": dict(sess.entity_memory),
                "turn_count": len(sess.turns),
            }
        )


# ------------------------------------------------------------------ #
# AnalyticsKickoffTool  (Dispatcher 補助; 本番は Python 側 kickoff)
# ------------------------------------------------------------------ #
class AnalyticsKickoffArgs(BaseModel):
    mode: Literal["summary", "dashboard"] = Field(
        ..., description="summary は例3、dashboard は例2"
    )
    fq_table_name: str = Field(
        ..., min_length=1, description="対象 Iceberg テーブルの fq 名"
    )
    question: Optional[str] = Field(
        None, description="ユーザーの元の日本語質問 (Text2SQL のヒント)"
    )


class AnalyticsKickoffTool(BaseSolomonTool):
    """Analytics Crew を起動する (未実装のためスタブ)。

    Analytics Crew (solomon.analytics) は wish API から直接 kickoff される。
    LLM が Tool を呼んだ場合は NOT_IMPLEMENTED を返す。
    """

    name: str = "analytics_kickoff"
    description: str = (
        "Kick off the Analytics Crew for summary or dashboard on the given "
        "fully-qualified Iceberg table. Prefer Python-side dispatch in production."
    )
    args_schema: type[BaseModel] = AnalyticsKickoffArgs

    def run(
        self,
        user_ctx: Optional[UserContext],
        mode: str,
        fq_table_name: str,
        question: Optional[str] = None,
        **_: Any,
    ) -> dict[str, Any]:
        return err(
            "NOT_IMPLEMENTED",
            f"AnalyticsCrew ({mode}) は Router Tool からは起動しません。",
            fq_table_name=fq_table_name,
        )


__all__ = [
    "EntityMemoryReadTool",
    "AnalyticsKickoffTool",
]
