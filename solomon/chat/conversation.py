"""Solomon ChatPane 向けの一般会話 (CHITCHAT) 応答。"""

from __future__ import annotations

import time
from typing import Iterable

from solomon.transport.llm import try_text_completion, try_text_completion_async
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are Solomon, a friendly data-analysis assistant running on Cloudera AI Agent Studio.

Respond naturally in the same language the user uses (Japanese or English).
Keep replies concise (1–3 short paragraphs at most).

You can help with:
- Ingesting files from S3 into Lakehouse / knowledge graph (Neo4j)
- Table summaries and dashboards
- Knowledge search across Neo4j, OpenSearch, and SQL (Agentic RAG)

For casual conversation, greet warmly and answer naturally.
Do NOT dump a full capability list unless the user asks what you can do.
If the user greets you, greet back briefly — do not redirect to a menu of options.
"""


def _build_messages(
    prompt: str,
    history: Iterable[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for user_text, assistant_text in history or ():
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        if user_text:
            messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})
    messages.append({"role": "user", "content": prompt.strip()})
    return messages


def fallback_chitchat_reply(prompt: str) -> str:
    """LLM 未設定時の最小応答 (挨拶・感謝などにだけ軽く返す)。"""
    text = prompt.strip()
    lower = text.lower()
    if any(kw in lower for kw in ("hello", "hi", "hey")):
        return "Hello! I'm Solomon. How can I help you today?"
    if any(kw in text for kw in ("こんにちは", "おはよう", "こんばんは", "やあ", "ども")):
        return "こんにちは。Solomon です。何かお手伝いできることがあれば、気軽にどうぞ。"
    if any(kw in text for kw in ("ありがと", "感謝")):
        return "どういたしまして。ほかにご質問があればお知らせください。"
    if "thank" in lower:
        return "You're welcome. Let me know if you need anything else."
    if any(kw in lower for kw in ("help", "使い方", "何ができ", "できること")):
        return (
            "Solomon では、S3 ファイルの取り込み、ナレッジグラフへの追加、"
            "テーブルサマリー / ダッシュボード、ナレッジ検索 (Neo4j / OpenSearch / SQL) "
            "などができます。やりたいことを自然な言葉で教えてください。"
        )
    return (
        "Solomon です。データの取り込み、分析、ナレッジ検索について"
        "お手伝いできます。ご用件を教えてください。"
    )


def generate_chitchat_reply(
    prompt: str,
    *,
    history: Iterable[tuple[str, str]] | None = None,
) -> str:
    """一般会話の返答を生成する。LLM 不可時は :func:`fallback_chitchat_reply`。"""
    messages = _build_messages(prompt, history)
    reply = try_text_completion(
        messages, max_tokens=512, temperature=0.7, timeout=15.0
    )
    if reply and reply.strip():
        return reply.strip()
    fb = fallback_chitchat_reply(prompt)
    _logger.info("chat.conversation.fallback", prompt_len=len(prompt))
    return fb


async def generate_chitchat_reply_async(
    prompt: str,
    *,
    history: Iterable[tuple[str, str]] | None = None,
) -> str:
    """非同期版。CHITCHAT SSE パスから呼ぶ (スレッドプールを使わない)。"""
    messages = _build_messages(prompt, history)
    started = time.monotonic()
    _logger.info("chat.conversation.llm_start", prompt_len=len(prompt))
    reply = await try_text_completion_async(
        messages, max_tokens=512, temperature=0.7, timeout=15.0
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if reply and reply.strip():
        _logger.info(
            "chat.conversation.llm_done",
            prompt_len=len(prompt),
            reply_len=len(reply.strip()),
            elapsed_ms=elapsed_ms,
        )
        return reply.strip()
    _logger.warning(
        "chat.conversation.fallback",
        prompt_len=len(prompt),
        elapsed_ms=elapsed_ms,
    )
    return fallback_chitchat_reply(prompt)
