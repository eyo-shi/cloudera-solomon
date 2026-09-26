"""Text-to-SQL Tool — Ossie / OpenSearch コンテキスト + Trino 実行。"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.semantic.store import search_datasets
from solomon.tools.opensearch import OpenSearchKeywordSearchTool
from solomon.tools.trino import TrinoQueryTool
from solomon.transport.config import get_opensearch_config, get_trino_config
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.llm import try_json_completion
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

_MUTATION = re.compile(
    r"^\s*(CREATE|DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


class Text2SQLArgs(BaseModel):
    question: str = Field(..., description="自然言語の分析質問")
    catalog: str = Field("iceberg")
    schema_: Optional[str] = Field(None, alias="schema")
    fq_table_hint: Optional[str] = Field(
        None, description="既知の catalog.schema.table (省略可)"
    )
    max_rows: int = Field(100, ge=1, le=1000)

    model_config = {"populate_by_name": True}


def _gather_rag_context(question: str, fq_hint: Optional[str]) -> list[dict[str, Any]]:
    """Ossie TF-IDF + (設定済みなら) OpenSearch から関連データセットを集める。"""
    contexts: list[dict[str, Any]] = []
    if fq_hint:
        contexts.append({"fq_name": fq_hint, "source": "hint"})

    for hit in search_datasets(question, top_k=3):
        contexts.append({"source": "ossie", **hit})

    if get_opensearch_config() is not None:
        os_tool = OpenSearchKeywordSearchTool()
        os_result = os_tool.run(user_ctx=None, query=question, top_k=3)
        if os_result.get("status") == "ok":
            for r in os_result.get("results", []):
                contexts.append({"source": "opensearch", **r})
    return contexts


def _build_sql_prompt(question: str, contexts: list[dict[str, Any]], catalog: str, schema: str | None) -> str:
    ctx_lines = []
    for c in contexts[:5]:
        ds = c.get("dataset") or c
        fq = c.get("fq_name") or ds.get("fq_name", "")
        desc = ds.get("description", "") if isinstance(ds, dict) else ""
        dims = ds.get("dimensions", []) if isinstance(ds, dict) else []
        measures = ds.get("measures", []) if isinstance(ds, dict) else []
        col_names = [d.get("name") for d in dims + measures if isinstance(d, dict)]
        ctx_lines.append(f"- {fq}: {desc} columns={col_names[:12]}")

    schema_hint = schema or "demo"
    return (
        f"Generate a Trino SELECT query for this question.\n"
        f"Catalog: {catalog}, default schema: {schema_hint}\n"
        f"Question: {question}\n\n"
        f"Relevant datasets:\n" + "\n".join(ctx_lines) + "\n\n"
        'Return JSON: {"sql": "SELECT ...", "fq_table": "catalog.schema.table", "reasoning": "..."}'
    )


class Text2SQLTool(BaseSolomonTool):
    """RAG コンテキストから SQL を生成し Trino で実行する (Lakehouse SQL)。"""

    name: str = "text2sql"
    description: str = (
        "Answer analytics questions by retrieving relevant dataset context (Ossie/OpenSearch), "
        "generating a read-only Trino SELECT, and executing it."
    )
    args_schema: type[BaseModel] = Text2SQLArgs

    def run(
        self,
        user_ctx: Optional[UserContext],
        question: str,
        catalog: str = "iceberg",
        schema: Optional[str] = None,
        fq_table_hint: Optional[str] = None,
        max_rows: int = 100,
        **_: Any,
    ) -> dict[str, Any]:
        if get_trino_config() is None:
            return err(
                ErrorCode.TRINO_NOT_CONFIGURED,
                "Trino is not configured.",
            )

        contexts = _gather_rag_context(question, fq_table_hint)
        llm_result = try_json_completion(
            _build_sql_prompt(question, contexts, catalog, schema),
            max_tokens=512,
        )

        sql: str | None = None
        reasoning = ""
        if llm_result and isinstance(llm_result.get("sql"), str):
            sql = llm_result["sql"].strip()
            reasoning = str(llm_result.get("reasoning", ""))

        if not sql:
            # Heuristic fallback: 最初のコンテキストテーブルから COUNT
            fq = fq_table_hint
            if not fq:
                for c in contexts:
                    fq = c.get("fq_name")
                    if fq:
                        break
            if fq:
                sql = f"SELECT COUNT(*) AS row_count FROM {fq}"
                reasoning = "LLM unavailable; fallback COUNT(*)"
            else:
                return err(
                    ErrorCode.TRINO_QUERY_FAILED,
                    "Could not generate SQL: no dataset context and LLM unavailable.",
                )

        if _MUTATION.match(sql):
            return err(ErrorCode.TRINO_QUERY_FAILED, "Generated SQL is not read-only.")

        trino = TrinoQueryTool()
        exec_result = trino.run(
            user_ctx=user_ctx,
            sql=sql,
            catalog=catalog,
            schema=schema,
            max_rows=max_rows,
        )
        if exec_result.get("status") != "ok":
            return exec_result

        return ok(
            {
                "question": question,
                "sql": sql,
                "reasoning": reasoning,
                "rag_contexts": [
                    {"fq_name": c.get("fq_name"), "source": c.get("source")}
                    for c in contexts[:5]
                ],
                "columns": exec_result.get("columns"),
                "rows": exec_result.get("rows"),
                "row_count": exec_result.get("row_count"),
            }
        )
