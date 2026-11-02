"""Ossie セマンティックレイヤ操作 Tool (本家形式読取・検索)。"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.semantic.store import read_dataset, search_datasets
from solomon.transport.errors import ok
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext


class OssieReadArgs(BaseModel):
    fq_name: str = Field(
        ...,
        description="Dataset fq_name (catalog.schema.table) or model.dataset name",
    )


class OssieReadTool(BaseSolomonTool):
    """1 データセットの Ossie 定義 (fields / metrics / ai_context / relationships) を返す。"""

    name: str = "ossie_read"
    description: str = (
        "Read one Ossie semantic dataset by fq_name or model.dataset. "
        "Returns official-format fields, metrics, ai_context, and related relationships."
    )
    args_schema: type[BaseModel] = OssieReadArgs
    requires_auth: bool = False

    def run(
        self, user_ctx: Optional[UserContext], fq_name: str, **_: Any
    ) -> dict[str, Any]:
        return read_dataset(fq_name)


class OssieSearchArgs(BaseModel):
    query: str = Field(..., description="Natural-language query (Text2SQL RAG)")
    top_k: int = Field(3, ge=1, le=10)


class OssieSearchTool(BaseSolomonTool):
    """クエリに関連する Ossie データセットを返す。"""

    name: str = "ossie_search"
    description: str = (
        "Find top-k Ossie datasets relevant to a natural-language query "
        "(supports Japanese and English tokenization)."
    )
    args_schema: type[BaseModel] = OssieSearchArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        query: str,
        top_k: int = 3,
        **_: Any,
    ) -> dict[str, Any]:
        hits = search_datasets(query, top_k=top_k)
        return ok({"query": query, "top_k": top_k, "results": hits})
