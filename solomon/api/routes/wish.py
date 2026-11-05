"""Wish (自然言語プロンプト) SSE エンドポイント (`POST /api/wish`)。

ChatPane からのプロンプトを :func:`kickoff_router` に渡し、判定された intent
に応じて子 Crew (Analytics / Knowledge RAG) を Python 側から起動する。
実行進捗は Server-Sent Events で逐次返す。

Router は :func:`kickoff_router` の ``mode='auto'`` (Router Crew / LLM) を使う。
LLM 構築失敗時は heuristic にフォールバックする。

**注意**:
* Knox JWT は :class:`UserContext` に載せて ContextVar にセットしてから
  Crew を kickoff する (Task の inputs に載せない)
* Crew.kickoff は同期呼び出しなので :func:`asyncio.to_thread` で退避
* クライアント切断は ``request.is_disconnected`` で検出し、次イベントで抜ける
"""
from __future__ import annotations

import asyncio
import queue
import uuid
from typing import Annotated, Any, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from solomon.analytics.crew import (
    kickoff_analytics_dashboard,
    kickoff_analytics_summary,
)
from solomon.api.auth import get_user_context
from solomon.chat.conversation import (
    fallback_chitchat_reply,
    generate_chitchat_reply_async,
)
from solomon.api.sse import (
    sse_artifact,
    sse_done,
    sse_error,
    sse_narrative,
    sse_step,
    sse_token,
)
from solomon.api.state import SessionTurn, get_store
from solomon.rag.crew import kickoff_knowledge_rag
from solomon.router import DispatchPlan, RouterResult, kickoff_router
from solomon.router.crew import build_chitchat_plan
from solomon.transport.errors import ErrorCode
from solomon.api.setup_checks import llm_not_configured_payload
from solomon.transport.logging import get_logger
from solomon.transport.user_context import (
    UserContext,
    reset_user_context,
    set_user_context,
)

router = APIRouter(prefix="/api", tags=["wish"])
_logger = get_logger(__name__)


RagSourceName = Literal["table", "graph", "search"]


class WishRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8192)
    session_id: Optional[str] = None
    target_schema: Optional[str] = Field(
        None,
        max_length=128,
        description="互換用 (取り込みは別プロジェクト)。現行 Router では未使用。",
    )
    sources: Optional[list[RagSourceName]] = Field(
        None,
        description="Knowledge RAG の有効ソース。省略時は SOLOMON_RAG_SOURCES 既定。",
    )

    @field_validator("sources")
    @classmethod
    def sources_non_empty(
        cls, value: Optional[list[RagSourceName]]
    ) -> Optional[list[RagSourceName]]:
        if value is not None and len(value) == 0:
            raise ValueError("sources must not be empty")
        return value


@router.post("/wish")
async def post_wish(
    body: WishRequest,
    request: Request,
    user_ctx: Annotated[UserContext, Depends(get_user_context)],
) -> Any:
    """SSE で Router + 子 Crew の実行を逐次配信する。

    LLM が未設定なら SSE を開かず HTTP 503 + guided JSON を返す。UI
    (:mod:`solomon_ui.src.api.client`) は 503 レスポンスから
    :class:`SetupGuideError` を投げ、ChatPane が SetupGuide カードを出す。
    """
    # LLM 未設定なら SSE を開かず 503 で早期リターン (UI が SetupGuide 表示)。
    # env 変更 → Application 再起動で解消する運用。
    llm_setup = llm_not_configured_payload()
    if llm_setup is not None:
        return JSONResponse(status_code=503, content=llm_setup)

    store = get_store()
    sid = body.session_id or user_ctx.session_id
    session = store.get_or_create_session(sid, user_ctx.user_name)
    turn_id = f"turn_{uuid.uuid4().hex[:10]}"

    # LLM は毎リクエストで env 経由に再解決する (env 変更 → Application 再起動で反映)。
    # 未設定は上の 503 で弾いているのでここで None にはならない想定だが、
    # crewai / litellm のインストール失敗等でファクトリが None を返す可能性は残る。
    async def stream() -> AsyncIterator[dict]:
        artifacts_created: list[str] = []
        response_md_parts: list[str] = []
        error_holder: list[Optional[str]] = [None]

        try:
            # 1) Router — heuristic モードは同期でも十分速い
            yield sse_narrative("ご依頼の内容を読み取り、実行プランを決めます。")
            yield sse_step(
                "RouterCrew",
                "running",
                "意図を分類しています...",
                activity="Classifying intent",
            )
            router_result = await asyncio.to_thread(
                _run_router,
                user_ctx=user_ctx,
                prompt=body.prompt,
                session_id=session.session_id,
                entity_memory=dict(session.entity_memory),
                target_schema_override=body.target_schema,
                llm_light=None,
            )
            intent = router_result.classification.intent
            yield sse_step("RouterCrew", "done", f"intent={intent}")
            yield sse_narrative("ルーティングが完了しました。次の処理に進みます。")

            plan = router_result.plan
            if router_result.classification.intent == "CHITCHAT" and (
                plan.skip_child or plan.child_crew != "chitchat"
            ):
                plan = build_chitchat_plan(prompt=body.prompt)

            # 2) skip_child (clarify / UNKNOWN) は response_markdown を流す
            if plan.skip_child:
                md = router_result.response_markdown or plan.response_markdown or ""
                if md:
                    response_md_parts.append(md)
                    yield sse_token(md)
                return

            # 3) 子 Crew ディスパッチ
            if plan.child_crew == "analytics_summary":
                async for chunk in _handle_summary(
                    request=request,
                    user_ctx=user_ctx,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    fq_table_name=str(plan.inputs.get("fq_table_name", "")),
                    question=str(plan.inputs.get("question") or body.prompt),
                    llm_light=None,
                    llm_strong=None,
                    artifacts_created=artifacts_created,
                    response_md_parts=response_md_parts,
                    error_holder=error_holder,
                ):
                    yield chunk
            elif plan.child_crew == "analytics_dashboard":
                async for chunk in _handle_dashboard(
                    request=request,
                    user_ctx=user_ctx,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    fq_table_name=str(plan.inputs.get("fq_table_name", "")),
                    question=str(plan.inputs.get("question") or body.prompt),
                    llm_light=None,
                    llm_strong=None,
                    artifacts_created=artifacts_created,
                    response_md_parts=response_md_parts,
                    error_holder=error_holder,
                ):
                    yield chunk
            elif plan.child_crew == "knowledge_rag":
                async for chunk in _handle_knowledge_rag(
                    request=request,
                    user_ctx=user_ctx,
                    session_id=session.session_id,
                    question=str(plan.inputs.get("question") or body.prompt),
                    sources=body.sources,
                    artifacts_created=artifacts_created,
                    response_md_parts=response_md_parts,
                    error_holder=error_holder,
                ):
                    yield chunk
            elif plan.child_crew == "chitchat":
                async for chunk in _handle_chitchat(
                    request=request,
                    session_id=session.session_id,
                    prompt=str(plan.inputs.get("prompt") or body.prompt),
                    response_md_parts=response_md_parts,
                    error_holder=error_holder,
                ):
                    yield chunk
            else:
                # child_crew='none' で skip_child=false は理論上ありえない
                error_holder[0] = "INTERNAL_ERROR"
                yield sse_error(
                    "INTERNAL_ERROR",
                    f"Unexpected dispatch plan: child_crew={plan.child_crew}",
                )

        except asyncio.CancelledError:
            _logger.info(
                "wish.cancelled",
                session_id=session.session_id,
                turn_id=turn_id,
            )
            raise
        except Exception as e:  # noqa: BLE001
            _logger.error(
                "wish.unexpected",
                session_id=session.session_id,
                turn_id=turn_id,
                error=str(e),
            )
            error_holder[0] = "INTERNAL_ERROR"
            yield sse_error(
                "INTERNAL_ERROR",
                f"Unexpected error: {type(e).__name__}: {e}",
            )
        finally:
            # 会話履歴に turn を追記
            store.append_turn(
                session.session_id,
                SessionTurn(
                    turn_id=turn_id,
                    prompt=body.prompt,
                    response_markdown="".join(response_md_parts),
                    artifact_ids=artifacts_created,
                    error_code=error_holder[0],
                ),
            )
            yield sse_done(
                turn_id=turn_id,
                session_id=session.session_id,
                artifacts=artifacts_created,
                ok=(error_holder[0] is None),
            )

    # sep="\n": sse-starlette の既定 CRLF は UI の SSE 手動パーサ (\n\n 分割) と
    # 合わない。Knox / リバースプロキシ越しでも LF 区切りに統一する。
    return EventSourceResponse(
        stream(),
        ping=15,
        sep="\n",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------ #
# Router 実行 (asyncio.to_thread で退避)
# ------------------------------------------------------------------ #
def _run_router(
    *,
    user_ctx: UserContext,
    prompt: str,
    session_id: str,
    entity_memory: dict,
    target_schema_override: Optional[str],
    llm_light: Optional[Any] = None,
) -> RouterResult:
    """Router を実行し、target_schema の明示指定を plan に反映する。"""
    token = set_user_context(user_ctx)
    try:
        result = kickoff_router(
            user_ctx=user_ctx,
            prompt=prompt,
            session_id=session_id,
            entity_memory=entity_memory,
            llm_light=llm_light,
            mode="auto",
        )
    finally:
        reset_user_context(token)

    _ = target_schema_override
    return result


# ------------------------------------------------------------------ #
# Chitchat path
# ------------------------------------------------------------------ #
_CHITCHAT_LLM_TIMEOUT_SEC = 20.0


def _conversation_history(session_id: str, *, limit: int = 6) -> list[tuple[str, str]]:
    """直近ターンを (user, assistant) のペアで返す (現在ターンは未含む)。"""
    sess = get_store().get_session(session_id)
    if sess is None:
        return []
    pairs: list[tuple[str, str]] = []
    for turn in sess.turns[-limit:]:
        user_text = (turn.prompt or "").strip()
        assistant_text = (turn.response_markdown or "").strip()
        if user_text and assistant_text:
            pairs.append((user_text, assistant_text))
    return pairs


async def _handle_chitchat(
    *,
    request: Request,
    session_id: str,
    prompt: str,
    response_md_parts: list[str],
    error_holder: list[Optional[str]],
) -> AsyncIterator[dict]:
    """一般会話 (CHITCHAT) — LLM で自然な返答を生成する。"""
    yield sse_step("Chat", "running", "返答を生成しています...")

    history = _conversation_history(session_id)
    try:
        reply = await asyncio.wait_for(
            generate_chitchat_reply_async(prompt, history=history),
            timeout=_CHITCHAT_LLM_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        _logger.warning("wish.chitchat_timeout", session_id=session_id)
        reply = fallback_chitchat_reply(prompt)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        _logger.error("wish.chitchat_failed", session_id=session_id, error=str(e))
        reply = fallback_chitchat_reply(prompt)

    if await request.is_disconnected():
        return

    response_md_parts.append(reply)
    _logger.info(
        "wish.chitchat_token",
        session_id=session_id,
        reply_len=len(reply),
    )
    yield sse_token(reply)
    yield sse_step("Chat", "done", "返答しました。")


# ------------------------------------------------------------------ #
# Analytics Summary path
# ------------------------------------------------------------------ #
async def _handle_summary(
    *,
    request: Request,
    user_ctx: UserContext,
    session_id: str,
    turn_id: str,
    fq_table_name: str,
    question: str,
    llm_light: Optional[Any],
    llm_strong: Optional[Any],
    artifacts_created: list[str],
    response_md_parts: list[str],
    error_holder: list[Optional[str]],
) -> AsyncIterator[dict]:
    """AnalyticsCrew (Summary) を走らせて SSE イベントを yield する。"""
    if not fq_table_name or fq_table_name.count(".") != 2:
        error_holder[0] = "ANALYTICS_MISSING_ARGS"
        yield sse_error(
            "ANALYTICS_MISSING_ARGS",
            "サマリー対象のテーブル (catalog.schema.table) が特定できませんでした。",
        )
        return

    yield sse_step(
        "AnalyticsSummaryCrew",
        "running",
        f"{fq_table_name} を調査し、サマリーを作成します...",
    )

    # UserContext を持ち込む session_id つきの派生を用意
    scoped_ctx = UserContext(
        user_name=user_ctx.user_name,
        groups=user_ctx.groups,
        knox_jwt=user_ctx.knox_jwt,
        aws_credentials=user_ctx.aws_credentials,
        session_id=session_id,
    )

    # crew.kickoff は同期 & LLM 呼び出し込みで長い → to_thread で退避
    def _run() -> dict:
        token = set_user_context(scoped_ctx)
        try:
            return kickoff_analytics_summary(
                user_ctx=scoped_ctx,
                fq_table_name=fq_table_name,
                question=question,
                llm_light=llm_light,
                llm_strong=llm_strong,
            )
        finally:
            reset_user_context(token)

    task = asyncio.create_task(asyncio.to_thread(_run))

    # 実行中は 5 秒に 1 回進捗イベントを出しつつクライアント切断も監視する
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except asyncio.TimeoutError:
            if await request.is_disconnected():
                task.cancel()
                return
            yield sse_step("AnalyticsSummaryCrew", "running", "Crew 実行中...")

    result = await task
    if result.get("status") != "ok":
        code = result.get("error_code", "ANALYTICS_SUMMARY_FAILED")
        msg = result.get("message", "AnalyticsSummary failed")
        error_holder[0] = code
        yield sse_error(code, msg)
        return

    report = (result.get("payload") or {}).get("report") or {}
    md = _format_summary_markdown(report, fq_table_name)

    # summary artifact を artifact ストアに登録 (ResultPane タブから開ける)
    store = get_store()
    art = store.register_artifact(
        "summary",
        ref={
            "fq": fq_table_name,
            "markdown": md,
            "observations": report.get("observations") or [],
            "warnings": report.get("warnings") or [],
            "sample_queries": report.get("sample_queries") or [],
        },
        session_id=session_id,
    )
    artifacts_created.append(art.artifact_id)

    # entity_memory を更新して次ターンの「そのサマリー」参照に備える
    store.update_entity_memory(
        session_id,
        {
            "last_table": fq_table_name,
            "last_summary_artifact_id": art.artifact_id,
        },
    )

    yield sse_artifact(art.artifact_id, "summary", ref={"fq": fq_table_name})
    response_md_parts.append(md)
    yield sse_token(md)
    yield sse_step("AnalyticsSummaryCrew", "done", "サマリーを作成しました。")


# ------------------------------------------------------------------ #
# Analytics Dashboard path
# ------------------------------------------------------------------ #
def _sse_activity_for_tool(name: str) -> str:
    return {
        "sql_query": "Querying lakehouse",
        "graph_query": "Querying graph",
        "doc_search": "Searching documents",
    }.get(name, "Running tool")


def _doc_search_expansion_narrative(
    original: str,
    expanded: list[str],
) -> str | None:
    if not expanded:
        return None
    parts = [str(x).strip() for x in expanded if str(x).strip()][:4]
    if not parts:
        return None
    joined = "」「".join(parts)
    orig = (original or "").strip()[:80]
    return f"「{orig}」を「{joined}」でも検索しました"


def _format_tool_start_message(name: str, args: dict[str, Any]) -> str:
    if name == "graph_query" and args.get("cypher"):
        cypher = str(args["cypher"]).strip().replace("\n", " ")
        if len(cypher) > 120:
            cypher = cypher[:117] + "..."
        return f"graph_query: {cypher}"
    if name == "sql_query":
        if args.get("sql"):
            sql = str(args["sql"]).strip().replace("\n", " ")
            if len(sql) > 120:
                sql = sql[:117] + "..."
            return f"sql_query: {sql}"
        q = str(args.get("question") or "")[:100]
        return f"sql_query: {q}"
    if name == "doc_search":
        return f"doc_search: {str(args.get('query') or '')[:100]}"
    return name


async def _handle_knowledge_rag(
    *,
    request: Request,
    user_ctx: UserContext,
    session_id: str,
    question: str,
    sources: Optional[list[RagSourceName]] = None,
    artifacts_created: list[str],
    response_md_parts: list[str],
    error_holder: list[Optional[str]],
) -> AsyncIterator[dict]:
    """Agentic RAG (heuristic または Knowledge ツールエージェント) を実行する。"""
    from solomon.rag.sources import format_sources_status_message, resolve_rag_sources
    from solomon.transport.config import get_rag_default_sources

    enabled, _disabled = resolve_rag_sources(
        sources, default=get_rag_default_sources()
    )
    sources_msg = format_sources_status_message(enabled)

    yield sse_step(
        "KnowledgeAgent",
        "running",
        sources_msg,
    )

    scoped_ctx = UserContext(
        user_name=user_ctx.user_name,
        groups=user_ctx.groups,
        knox_jwt=user_ctx.knox_jwt,
        aws_credentials=user_ctx.aws_credentials,
        session_id=session_id,
    )

    events: queue.Queue[dict[str, Any]] = queue.Queue()

    def _on_event(ev: dict[str, Any]) -> None:
        events.put(ev)

    # 指示語つきの続き質問（「その〜」）を解決できるよう直近ターンを渡す
    history = _conversation_history(session_id, limit=3)

    def _run() -> dict:
        return kickoff_knowledge_rag(
            user_ctx=scoped_ctx,
            prompt=question,
            on_event=_on_event,
            sources=list(sources) if sources is not None else None,
            history=history,
        )

    task = asyncio.create_task(asyncio.to_thread(_run))

    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
        except asyncio.TimeoutError:
            if await request.is_disconnected():
                task.cancel()
                return
            while True:
                try:
                    ev = events.get_nowait()
                except queue.Empty:
                    break
                if ev.get("type") == "thought" and ev.get("text"):
                    yield sse_narrative(str(ev["text"])[:300])
                elif ev.get("type") == "tool_start":
                    name = str(ev.get("name") or "tool")
                    args = ev.get("args") if isinstance(ev.get("args"), dict) else {}
                    yield sse_step(
                        "KnowledgeAgent",
                        "running",
                        _format_tool_start_message(name, args),
                        activity=_sse_activity_for_tool(name),
                    )
                elif ev.get("type") == "tool_end":
                    name = str(ev.get("name") or "tool")
                    if name == "doc_search":
                        exp = ev.get("expanded_queries")
                        if isinstance(exp, list) and exp:
                            narr = _doc_search_expansion_narrative(
                                str(ev.get("query") or ""),
                                exp,
                            )
                            if narr:
                                yield sse_narrative(narr)
                    if ev.get("cached"):
                        yield sse_step(
                            "KnowledgeAgent",
                            "done",
                            f"{name}: cached",
                            activity=_sse_activity_for_tool(name),
                        )
                    else:
                        cnt = ev.get("count", 0)
                        ms = ev.get("duration_ms", 0)
                        st = "done" if ev.get("ok") else "error"
                        yield sse_step(
                            "KnowledgeAgent",
                            st,
                            f"{name}: {cnt} hits, {ms}ms",
                            activity=_sse_activity_for_tool(name),
                        )

    while True:
        try:
            ev = events.get_nowait()
        except queue.Empty:
            break
        if ev.get("type") == "thought" and ev.get("text"):
            yield sse_narrative(str(ev["text"])[:300])
        elif ev.get("type") == "tool_end" and not ev.get("cached"):
            name = str(ev.get("name") or "tool")
            if name == "doc_search":
                exp = ev.get("expanded_queries")
                if isinstance(exp, list) and exp:
                    narr = _doc_search_expansion_narrative(
                        str(ev.get("query") or ""),
                        exp,
                    )
                    if narr:
                        yield sse_narrative(narr)
            cnt = ev.get("count", 0)
            ms = ev.get("duration_ms", 0)
            st = "done" if ev.get("ok") else "error"
            yield sse_step(
                "KnowledgeAgent",
                st,
                f"{name}: {cnt} hits, {ms}ms",
                activity=_sse_activity_for_tool(name),
            )

    result = await task
    if result.get("status") != "ok":
        code = result.get("error_code", "KNOWLEDGE_RAG_FAILED")
        msg = result.get("message", "Knowledge RAG failed")
        error_holder[0] = code
        yield sse_error(code, msg)
        return

    engine = result.get("engine", "heuristic")
    steps = result.get("steps", 0)
    hit_count = result.get("hit_count", 0)
    yield sse_step(
        "KnowledgeAgent",
        "done",
        f"engine={engine}, steps={steps}, hits={hit_count}",
    )

    md = result.get("answer_markdown") or ""
    if md:
        response_md_parts.append(md)
        yield sse_token(md)

    if "graph" not in enabled:
        return

    hits = result.get("hits") or []
    strategy = result.get("strategy", "")

    if engine == "agent":
        last_cypher = _last_successful_graph_cypher(result.get("tool_calls") or [])
        if last_cypher:
            store = get_store()
            title = "Graph query"
            art = store.register_artifact(
                "graph",
                ref={
                    "query_type": "cypher",
                    "cypher": last_cypher["cypher"],
                    "params": last_cypher.get("params") or {},
                    "title": title,
                },
                session_id=session_id,
            )
            artifacts_created.append(art.artifact_id)
            yield sse_artifact(
                art.artifact_id,
                "graph",
                ref={
                    "query_type": "cypher",
                    "cypher": last_cypher["cypher"],
                    "params": last_cypher.get("params") or {},
                    "title": title,
                },
            )
        return

    graph_hits = [h for h in hits if h.get("source") == "graph"]
    if graph_hits or strategy in ("GRAPH_QUERY", "COMPOSITE"):
        entity_hint = _graph_entity_hint_from_rag(result, question)
        if entity_hint is not None:
            try:
                from solomon.graph.browse import visualize_entity_hint

                viz = visualize_entity_hint(entity_hint, limit=100)
                if viz.graph.nodes:
                    store = get_store()
                    title = f"Graph: {entity_hint or 'overview'}"
                    art = store.register_artifact(
                        "graph",
                        ref={
                            "query_type": "entity",
                            "entity_hint": entity_hint,
                            "title": title,
                        },
                        session_id=session_id,
                    )
                    artifacts_created.append(art.artifact_id)
                    yield sse_artifact(
                        art.artifact_id,
                        "graph",
                        ref={
                            "query_type": "entity",
                            "entity_hint": entity_hint,
                            "title": title,
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                _logger.debug("knowledge_rag.graph_artifact_skipped", error=str(exc))


def _last_successful_graph_cypher(
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Agent セッション内の最後の成功 graph_query（Cypher + params）。"""
    last: dict[str, Any] | None = None
    for tc in tool_calls:
        if tc.get("name") != "graph_query" or not tc.get("ok"):
            continue
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        cypher = str(args.get("cypher") or "").strip()
        if not cypher:
            continue
        params = args.get("params")
        last = {
            "cypher": cypher,
            "params": params if isinstance(params, dict) else {},
        }
    return last


def _graph_entity_hint_from_rag(result: dict, question: str) -> str | None:
    """RAG 結果から Graph 可視化用 entity_hint を推定する。"""
    for hit in result.get("hits") or []:
        if hit.get("source") != "graph":
            continue
        payload = hit.get("payload") or {}
        for record in payload.get("records") or []:
            for key in ("system_name", "fq_name", "name"):
                val = record.get(key)
                if val:
                    return str(val)
    strategy = result.get("strategy", "")
    if strategy in ("GRAPH_QUERY", "COMPOSITE"):
        return question.strip() or None
    return None


# ------------------------------------------------------------------ #
async def _handle_dashboard(
    *,
    request: Request,
    user_ctx: UserContext,
    session_id: str,
    turn_id: str,
    fq_table_name: str,
    question: str,
    llm_light: Optional[Any],
    llm_strong: Optional[Any],
    artifacts_created: list[str],
    response_md_parts: list[str],
    error_holder: list[Optional[str]],
) -> AsyncIterator[dict]:
    """AnalyticsCrew (Dashboard) を走らせて SSE イベントを yield する。"""
    if not fq_table_name or fq_table_name.count(".") != 2:
        error_holder[0] = "ANALYTICS_MISSING_ARGS"
        yield sse_error(
            "ANALYTICS_MISSING_ARGS",
            "ダッシュボード対象のテーブル (catalog.schema.table) が特定できませんでした。",
        )
        return

    yield sse_step(
        "AnalyticsDashboardCrew",
        "running",
        f"{fq_table_name} からダッシュボードを構築します...",
    )

    # UserContext を持ち込む session_id つきの派生を用意
    scoped_ctx = UserContext(
        user_name=user_ctx.user_name,
        groups=user_ctx.groups,
        knox_jwt=user_ctx.knox_jwt,
        aws_credentials=user_ctx.aws_credentials,
        session_id=session_id,
    )

    # crew.kickoff は同期 & LLM 呼び出し + CDV への複数 API 呼び出しで長い
    # → to_thread で退避
    def _run() -> dict:
        token = set_user_context(scoped_ctx)
        try:
            return kickoff_analytics_dashboard(
                user_ctx=scoped_ctx,
                fq_table_name=fq_table_name,
                question=question,
                llm_light=llm_light,
                llm_strong=llm_strong,
            )
        finally:
            reset_user_context(token)

    task = asyncio.create_task(asyncio.to_thread(_run))

    # 実行中は 5 秒に 1 回進捗イベントを出しつつクライアント切断も監視する
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except asyncio.TimeoutError:
            if await request.is_disconnected():
                task.cancel()
                return
            yield sse_step("AnalyticsDashboardCrew", "running", "Crew 実行中...")

    result = await task
    if result.get("status") != "ok":
        code = result.get("error_code", "ANALYTICS_DASHBOARD_FAILED")
        msg = result.get("message", "AnalyticsDashboard failed")
        error_holder[0] = code
        yield sse_error(code, msg)
        return

    dashboard = (result.get("payload") or {}).get("dashboard") or {}
    if not dashboard or not dashboard.get("dashboard_url"):
        # LLM が最終 JSON を組めなかった / CDV 応答が不完全だった
        error_holder[0] = "ANALYTICS_DASHBOARD_FAILED"
        yield sse_error(
            "ANALYTICS_DASHBOARD_FAILED",
            "ダッシュボードは作成されませんでした (最終 JSON が不完全)。",
        )
        return

    md = _format_dashboard_markdown(dashboard, fq_table_name)

    # dashboard artifact を artifact ストアに登録 (ResultPane が iframe で開く)
    store = get_store()
    art = store.register_artifact(
        "dashboard",
        ref={
            "fq": fq_table_name,
            "dashboard_id": dashboard.get("dashboard_id"),
            "dashboard_url": dashboard.get("dashboard_url"),
            "title": dashboard.get("title"),
            "visual_ids": dashboard.get("visual_ids") or [],
            "dataset_id": dashboard.get("dataset_id"),
            "notes": dashboard.get("notes"),
        },
        session_id=session_id,
    )
    artifacts_created.append(art.artifact_id)

    # entity_memory を更新して次ターンの「そのダッシュボード」参照に備える
    store.update_entity_memory(
        session_id,
        {
            "last_table": fq_table_name,
            "last_dashboard_id": dashboard.get("dashboard_id"),
            "last_dashboard_url": dashboard.get("dashboard_url"),
        },
    )

    yield sse_artifact(
        art.artifact_id,
        "dashboard",
        ref={
            "fq": fq_table_name,
            "dashboard_url": dashboard.get("dashboard_url"),
        },
    )
    response_md_parts.append(md)
    yield sse_token(md)
    yield sse_step(
        "AnalyticsDashboardCrew", "done", "ダッシュボードを作成しました。"
    )


def _format_dashboard_markdown(dashboard: dict, fq_table_name: str) -> str:
    """BuildDashboardResult を ChatPane に流す Markdown にする。"""
    title = dashboard.get("title") or f"{fq_table_name} のダッシュボード"
    url = dashboard.get("dashboard_url") or ""
    visual_count = len(dashboard.get("visual_ids") or [])
    reused = dashboard.get("dataset_reused")

    lines = [
        f"**ダッシュボードを作成しました**: [{title}]({url})",
        f"- 元テーブル: `{fq_table_name}`",
        f"- Visual 数: {visual_count}",
    ]
    if reused is True:
        lines.append("- Dataset: 既存を再利用")
    elif reused is False:
        lines.append("- Dataset: 新規作成")
    notes = dashboard.get("notes")
    if notes:
        lines.append("")
        lines.append(f"_notes_: {notes}")
    return "\n".join(lines) + "\n"


def _format_summary_markdown(report: dict, fq_table_name: str) -> str:
    """SummaryReport を ChatPane に流す Markdown にする。

    ``summary_markdown`` は LLM が書き切っている前提だが、空だった場合の
    最低限フォールバックとして観察点だけでも並べる。
    """
    if not report:
        return f"`{fq_table_name}` のサマリー生成を試みましたが、結果が取得できませんでした。\n"

    md = str(report.get("summary_markdown") or "").strip()
    if md:
        # 先頭に見出しが無ければ付ける
        if not md.startswith("#"):
            md = f"## `{fq_table_name}` のサマリー\n\n{md}"
        parts = [md]
    else:
        parts = [f"## `{fq_table_name}` のサマリー", ""]
        for obs in report.get("observations") or []:
            headline = obs.get("headline") or ""
            if headline:
                parts.append(f"- {headline}")

    warnings = report.get("warnings") or []
    if warnings:
        parts.append("")
        parts.append("**注意点**:")
        for w in warnings:
            parts.append(f"- {w}")

    samples = report.get("sample_queries") or []
    if samples:
        parts.append("")
        parts.append("**次に見ると良さそうな SQL**:")
        for s in samples[:3]:
            q = s.get("question") or ""
            sql = s.get("sql") or ""
            if q and sql:
                parts.append(f"- {q}")
                parts.append(f"  ```sql\n  {sql}\n  ```")

    return "\n".join(parts).rstrip() + "\n"
