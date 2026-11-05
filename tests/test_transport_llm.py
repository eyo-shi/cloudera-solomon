"""``solomon.transport.llm.try_json_completion`` のテスト。

LiteLLM 自体は差し替えて呼ぶ。環境変数・パース失敗・例外の分岐を検証する。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from solomon.transport import llm as llm_mod


# ------------------------------------------------------------------ #
# LiteLLM 未インストール → None
# ------------------------------------------------------------------ #
def test_returns_none_when_litellm_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sys.modules[name] = None`` は import 時に ImportError を発生させる。"""
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")
    monkeypatch.setitem(sys.modules, "litellm", None)  # 明示的にインポート禁止
    result = llm_mod.try_json_completion("hello")
    assert result is None


# ------------------------------------------------------------------ #
# 環境変数不足 → None (LiteLLM を呼ばない)
# ------------------------------------------------------------------ #
def test_returns_none_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAI_INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("CAI_INFERENCE_API_KEY", raising=False)
    # litellm が仮に import できてもここで exit するはず。
    fake = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    result = llm_mod.try_json_completion("hello")
    assert result is None
    fake.completion.assert_not_called()


# ------------------------------------------------------------------ #
# 正常系: LiteLLM が JSON 文字列を返し、dict にパースできる
# ------------------------------------------------------------------ #
def test_parses_json_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")

    fake = mock.MagicMock()
    fake.completion.return_value = {
        "choices": [{"message": {"content": '{"answer": 42, "ok": true}'}}]
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)

    result = llm_mod.try_json_completion("q")
    assert result == {"answer": 42, "ok": True}
    fake.completion.assert_called_once()
    _, kwargs = fake.completion.call_args
    assert kwargs["api_base"] == "https://x"
    assert kwargs["api_key"] == "k"
    assert kwargs["temperature"] == 0.0


# ------------------------------------------------------------------ #
# 応答にコードフェンスが付いていても剥がしてパース
# ------------------------------------------------------------------ #
def test_strips_json_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")

    fake = mock.MagicMock()
    fake.completion.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        "```json\n"
                        '{"name": "alice"}\n'
                        "```"
                    )
                }
            }
        ]
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)

    result = llm_mod.try_json_completion("q")
    assert result == {"name": "alice"}


# ------------------------------------------------------------------ #
# 応答が JSON にならない → None
# ------------------------------------------------------------------ #
def test_returns_none_on_unparseable_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")

    fake = mock.MagicMock()
    fake.completion.return_value = {
        "choices": [{"message": {"content": "not json at all"}}]
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)

    result = llm_mod.try_json_completion("q")
    assert result is None


# ------------------------------------------------------------------ #
# LiteLLM が例外を投げても None (Tool 側のフォールバックを担保)
# ------------------------------------------------------------------ #
def test_returns_none_on_llm_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")

    fake = mock.MagicMock()
    fake.completion.side_effect = RuntimeError("network down")
    monkeypatch.setitem(sys.modules, "litellm", fake)

    result = llm_mod.try_json_completion("q")
    assert result is None


# ------------------------------------------------------------------ #
# JSON が dict 以外 (list など) を返してきたら None
# ------------------------------------------------------------------ #
def test_returns_none_for_non_dict_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")

    fake = mock.MagicMock()
    fake.completion.return_value = {
        "choices": [{"message": {"content": "[1, 2, 3]"}}]
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)

    result = llm_mod.try_json_completion("q")
    assert result is None


# ------------------------------------------------------------------ #
# モデル ID の resolve: 明示 > 環境変数 > デフォルト
# ------------------------------------------------------------------ #
def test_model_resolution_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")
    monkeypatch.setenv("SOLOMON_LLM_ROUTER_MODEL", "env-model")

    fake = mock.MagicMock()
    fake.completion.return_value = {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setitem(sys.modules, "litellm", fake)

    llm_mod.try_json_completion("q", model="explicit-model")
    _, kwargs = fake.completion.call_args
    assert kwargs["model"] == "openai/explicit-model"


def test_model_resolution_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")
    monkeypatch.setenv("SOLOMON_LLM_ROUTER_MODEL", "env-model")

    fake = mock.MagicMock()
    fake.completion.return_value = {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setitem(sys.modules, "litellm", fake)

    llm_mod.try_json_completion("q")
    _, kwargs = fake.completion.call_args
    assert kwargs["model"] == "openai/env-model"


# ------------------------------------------------------------------ #
# 推論モデルの思考・前後の説明文に寛容なパース
# ------------------------------------------------------------------ #
@pytest.mark.parametrize(
    "content",
    [
        '<think>reason {"x": 0}</think>{"sql": "SELECT 1"}',
        'reason without open tag {"x": 0}\n</think>\n\n{"sql": "SELECT 1"}',
        'Here is the query:\n{"sql": "SELECT 1"}\nDone.',
        '</think>```json\n{"sql": "SELECT 1"}\n```',
    ],
)
def test_parses_json_after_reasoning_or_prose(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")
    fake = mock.MagicMock()
    fake.completion.return_value = {"choices": [{"message": {"content": content}}]}
    monkeypatch.setitem(sys.modules, "litellm", fake)

    assert llm_mod.try_json_completion("q") == {"sql": "SELECT 1"}


def test_unparsed_json_is_logged_with_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")
    fake = mock.MagicMock()
    fake.completion.return_value = {
        "choices": [{"message": {"content": "thinking..."}, "finish_reason": "length"}]
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        llm_mod._logger, "warning", lambda event, **kw: seen.append({"event": event, **kw})
    )

    assert llm_mod.try_json_completion("q", agent_key="text2sql") is None
    assert seen and seen[0]["event"] == "llm.json_unparsed"
    assert seen[0]["finish_reason"] == "length"
    assert seen[0]["agent_key"] == "text2sql"


def test_strip_reasoning() -> None:
    assert llm_mod.strip_reasoning("<think>a</think>b") == "b"
    assert llm_mod.strip_reasoning("a</think>b") == "b"
    assert llm_mod.strip_reasoning(" plain ") == "plain"
    assert llm_mod.strip_reasoning(None) == ""


def test_text_completion_strips_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAI_INFERENCE_BASE_URL", "https://x")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "k")
    fake = mock.MagicMock()
    fake.completion.return_value = {
        "choices": [{"message": {"content": "hmm</think>\n## 回答"}}]
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)

    assert llm_mod.try_text_completion([{"role": "user", "content": "q"}]) == "## 回答"
