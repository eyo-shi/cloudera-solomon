"""Casual chat (CHITCHAT) reply tests."""

from __future__ import annotations

from solomon.chat.conversation import fallback_chitchat_reply, generate_chitchat_reply


def test_fallback_chitchat_greeting_english() -> None:
    reply = fallback_chitchat_reply("Hello")
    assert "Hello" in reply or "Solomon" in reply
    assert "S3 パスを取り込む" not in reply


def test_fallback_chitchat_greeting_japanese() -> None:
    reply = fallback_chitchat_reply("こんにちは")
    assert "こんにちは" in reply
    assert "Solomon" in reply


def test_generate_chitchat_without_llm_uses_fallback() -> None:
    reply = generate_chitchat_reply("Hello there")
    assert reply.strip()
