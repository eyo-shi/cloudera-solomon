"""Text-to-SQL Tool — Ossie スキーマ文脈 + Trino 実行（1 回自己修正）。"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.semantic.store import search_datasets
from solomon.tools.opensearch import OpenSearchKeywordSearchTool
from solomon.tools.schema_context import build_schema_context
from solomon.tools.sql_guard import validate_readonly_sql
from solomon.tools.trino import TrinoQueryTool
from solomon.transport.config import get_opensearch_config, get_trino_config
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.llm import try_json_completion
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

_PROMPT_RULES = (
    "Generate Trino SQL for the question below.\n"
    "Rules:\n"
    "- Use Trino SQL dialect.\n"
    "- Start with SELECT or WITH only (read-only).\n"
    "- Use column and metric names only from the schema context.\n"
    "- Date literals: DATE 'YYYY-MM-DD'.\n"
    "- Include a reasonable LIMIT.\n"
    "- When the question uses synonyms, map them to the matching columns or metric expressions.\n"
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


def _gather_rag_context(
    question: str,
    fq_hint: Optional[str],
    *,
    use_search_context: bool = True,
) -> list[dict[str, Any]]:
    """Ossie 検索 + (設定済みなら) OpenSearch から関連データセットを集める。"""
    contexts: list[dict[str, Any]] = []
    if fq_hint:
        contexts.append({"fq_name": fq_hint, "source": "hint"})

    for hit in search_datasets(question, top_k=3):
        contexts.append({"source": "ossie", **hit})

    if use_search_context and get_opensearch_config() is not None:
        os_tool = OpenSearchKeywordSearchTool()
        os_result = os_tool.run(user_ctx=None, query=question, top_k=3)
        if os_result.get("status") == "ok":
            for r in os_result.get("results", []):
                contexts.append({"source": "opensearch", **r})
    return contexts


def _build_sql_prompt(
    question: str,
    schema_block: str,
    catalog: str,
    schema: str,
    *,
    correction: dict[str, str] | None = None,
) -> str:
    parts = [
        _PROMPT_RULES,
        f"Catalog: {catalog}, default schema: {schema}\n",
        schema_block,
        f"\nQuestion: {question}\n",
    ]
    if correction:
        parts.append(
            "The previous SQL failed on Trino. Fix it using the same rules and schema.\n"
            f"Previous SQL:\n{correction.get('sql', '')}\n"
            f"Trino error:\n{correction.get('error', '')}\n"
        )
    parts.append('Return JSON only: {"sql": "SELECT ...", "reasoning": "..."}')
    return "\n".join(parts)


def _llm_sql(
    prompt: str,
) -> tuple[str | None, str]:
    # strong は推論モデルのことがあり、思考に token と時間を使うため余裕を持たせる
    parsed = try_json_completion(
        prompt,
        agent_key="text2sql",
        max_tokens=4096,
        timeout=60.0,
    )
    if not parsed or not isinstance(parsed.get("sql"), str):
        return None, ""
    sql = parsed["sql"].strip()
    reasoning = str(parsed.get("reasoning", ""))
    return sql, reasoning


def execute_readonly_sql_with_retry(
    user_ctx: Optional[UserContext],
    *,
    question: str,
    catalog: str,
    schema: str,
    max_rows: int,
    sql: str | None = None,
    schema_block: str | None = None,
) -> dict[str, Any]:
    """SQL 生成（省略可）+ Trino 実行。失敗時 1 回だけ LLM 再生成。"""
    attempts: list[dict[str, str]] = []
    reasoning = ""
    current_sql = (sql or "").strip()

    if not current_sql:
        block = schema_block or build_schema_context(
            question,
            catalog=catalog,
            schema=schema,
            user_ctx=user_ctx,
        )
        current_sql, reasoning = _llm_sql(
            _build_sql_prompt(question, block, catalog, schema),
        )
        if not current_sql:
            return {
                "status": "error",
                "message": "Could not generate SQL from LLM.",
                "attempts": attempts,
            }

    trino = TrinoQueryTool()
    for attempt_idx in range(2):
        guard = validate_readonly_sql(current_sql)
        if guard:
            # 読み取り専用チェックに落ちた SQL は決して実行しない。
            # LLM が書いた 1 回目だけ、理由を添えて書き直させる
            if sql and attempt_idx == 0:
                return {"status": "error", "message": guard, "attempts": attempts}
            attempts.append({"sql": current_sql, "error": guard})
            if attempt_idx == 1:
                return {"status": "error", "message": guard, "attempts": attempts}
            err_msg, error_code = guard, None
        else:
            exec_result = trino.run(
                user_ctx=user_ctx,
                sql=current_sql,
                catalog=catalog,
                schema=schema,
                max_rows=max_rows,
            )
            if exec_result.get("status") == "ok":
                return {
                    "status": "ok",
                    "sql": current_sql,
                    "reasoning": reasoning,
                    "attempts": attempts,
                    "columns": exec_result.get("columns"),
                    "rows": exec_result.get("rows"),
                    "row_count": exec_result.get("row_count"),
                }

            err_msg = str(exec_result.get("message") or "Trino query failed")
            error_code = exec_result.get("error_code")
            attempts.append({"sql": current_sql, "error": err_msg})
            if attempt_idx == 1:
                return {
                    "status": "error",
                    "message": err_msg,
                    "error_code": error_code,
                    "sql": current_sql,
                    "attempts": attempts,
                }

        block = schema_block or build_schema_context(
            question,
            catalog=catalog,
            schema=schema,
            user_ctx=user_ctx,
        )
        current_sql, reasoning = _llm_sql(
            _build_sql_prompt(
                question,
                block,
                catalog,
                schema,
                correction={"sql": current_sql, "error": err_msg},
            ),
        )
        if not current_sql:
            return {
                "status": "error",
                "message": err_msg,
                "error_code": error_code,
                "attempts": attempts,
            }

    return {"status": "error", "message": "SQL execution failed.", "attempts": attempts}


class Text2SQLTool(BaseSolomonTool):
    """Ossie スキーマ文脈から SQL を生成し Trino で実行する (Lakehouse SQL)。"""

    name: str = "text2sql"
    description: str = (
        "Answer analytics questions using Ossie semantic schema context, "
        "generate a read-only Trino SELECT, and execute it (one retry on Trino error)."
    )
    args_schema: type[BaseModel] = Text2SQLArgs

    def run(
        self,
        user_ctx: Optional[UserContext],
        question: str,
        catalog: str | None = None,
        schema: Optional[str] = None,
        fq_table_hint: Optional[str] = None,
        max_rows: int = 100,
        use_search_context: bool = True,
        **_: Any,
    ) -> dict[str, Any]:
        trino_cfg = get_trino_config()
        if trino_cfg is None:
            return err(
                ErrorCode.TRINO_NOT_CONFIGURED,
                "Trino is not configured.",
            )

        catalog = catalog or trino_cfg.catalog
        schema = schema or trino_cfg.schema

        contexts = _gather_rag_context(
            question, fq_table_hint, use_search_context=use_search_context
        )
        schema_block = build_schema_context(
            question,
            catalog=catalog,
            schema=schema,
            user_ctx=user_ctx,
        )

        pipeline = execute_readonly_sql_with_retry(
            user_ctx,
            question=question,
            catalog=catalog,
            schema=schema,
            max_rows=max_rows,
            schema_block=schema_block,
        )

        # 生成失敗時に別の質問（任意テーブルの件数）へ差し替えると、
        # 呼び出し元がそれを答えとして扱ってしまうため、失敗はそのまま返す。
        if pipeline.get("status") != "ok":
            return err(
                pipeline.get("error_code", ErrorCode.TRINO_QUERY_FAILED),
                str(pipeline.get("message", "text2sql failed")),
                sql=pipeline.get("sql"),
                attempts=pipeline.get("attempts"),
            )

        return ok(
            {
                "question": question,
                "sql": pipeline.get("sql"),
                "reasoning": pipeline.get("reasoning"),
                "attempts": pipeline.get("attempts") or [],
                "rag_contexts": [
                    {"fq_name": c.get("fq_name"), "source": c.get("source")}
                    for c in contexts[:5]
                ],
                "columns": pipeline.get("columns"),
                "rows": pipeline.get("rows"),
                "row_count": pipeline.get("row_count"),
            }
        )
