"""LLM 呼び出しの薄いラッパ (LiteLLM 経由)。

provider (cai / anthropic / openai / bedrock) は :func:`get_llm_config` で
解決する。ここは低レイヤなので、config が None なら黙って ``None`` を返す
(Tool 側でその変換をする責務)。

**方針**:

* LiteLLM が未インストール、または :func:`get_llm_config` が None (env 不足)
  なら ``None`` を返す。呼び出し元 (Tool / Task) は「LLM が使えない環境なので
  heuristic を採用する」fallback を取る。
* 例外は投げず、::class:`ToolErrorResult` 相当の error dict は返さない。
* 常に JSON 応答を期待する ``try_json_completion`` のみ提供する。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from solomon.transport.config import LLMRoleConfig, get_llm_agent_config, get_llm_role_config
from solomon.transport.llm_factory import _apply_prefix
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

# 応答本文から ```json ... ``` フェンスを剥がす
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
# 推論モデル（Qwen3 等）が content に書く思考ブロック
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_CLOSE = "</think>"


def strip_reasoning(text: Any) -> str:
    """``<think>…</think>`` を除去する。開始タグ欠落時は最後の ``</think>`` までを捨てる。"""
    if not isinstance(text, str):
        return ""
    out = _THINK_BLOCK_RE.sub("", text)
    idx = out.lower().rfind(_THINK_CLOSE)
    if idx >= 0:
        out = out[idx + len(_THINK_CLOSE) :]
    return out.strip()


def _completion_config(
    *,
    role: str = "light",
    agent_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[LLMRoleConfig]:
    if agent_key:
        cfg = get_llm_agent_config(agent_key)
    else:
        cfg = get_llm_role_config(role)
    if cfg is None:
        return None
    if model:
        return LLMRoleConfig(
            role=cfg.role,
            provider=cfg.provider,
            model=model,
            api_base=cfg.api_base,
            api_key=cfg.api_key,
            aws_region=cfg.aws_region,
        )
    return cfg


def try_json_completion(
    prompt: str,
    *,
    model: Optional[str] = None,
    role: str = "light",
    agent_key: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout: float = 30.0,
) -> Optional[dict[str, Any]]:
    """LLM に JSON 応答を要求し、パースして dict を返す。

    LiteLLM の :func:`completion` を使う。以下のいずれかの理由で **None** を返す:

    * ``litellm`` が未インストール
    * :func:`get_llm_config` が ``None`` (provider 未設定 or env 不足)
    * LLM 応答が JSON にパースできない
    * ネットワーク例外 / タイムアウト

    :param model: 明示的なモデル ID (省略時は provider の light モデル)
    """
    try:
        import litellm  # type: ignore
    except ImportError:
        _logger.debug("llm.litellm_not_installed")
        return None

    cfg = _completion_config(role=role, agent_key=agent_key, model=model)
    if cfg is None:
        _logger.debug("llm.config_missing")
        return None

    prefixed = _apply_prefix(cfg.provider, cfg.model)

    kwargs: dict[str, Any] = {
        "model": prefixed,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict JSON responder. Reply with ONLY a JSON "
                    "object (no prose, no code fences)."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    if cfg.provider == "bedrock" and cfg.aws_region:
        kwargs["aws_region_name"] = cfg.aws_region

    try:
        resp = litellm.completion(**kwargs)  # type: ignore[attr-defined]
        # OpenAI 互換の choices[0].message.content
        choice = resp["choices"][0]  # type: ignore[index]
        content = choice["message"]["content"]
    except Exception as e:  # noqa: BLE001
        _logger.warning(
            "llm.completion_failed", provider=cfg.provider, error=str(e)
        )
        return None

    parsed = _parse_json_lenient(content)
    if parsed is None:
        # 呼び出し元は黙ってフォールバックするので、原因（思考で max_tokens 切れ等）をここで残す
        finish_reason = None
        try:
            finish_reason = choice.get("finish_reason")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        _logger.warning(
            "llm.json_unparsed",
            agent_key=agent_key,
            finish_reason=finish_reason,
            content_chars=len(content) if isinstance(content, str) else 0,
            text_prefix=strip_reasoning(content)[:120],
        )
    return parsed


def _first_json_object(text: str) -> Any:
    """前後に説明文が付いた応答から、最初に読める JSON オブジェクトを取り出す。"""
    decoder = json.JSONDecoder()
    pos = text.find("{")
    while pos >= 0:
        try:
            value, _end = decoder.raw_decode(text, pos)
            return value
        except json.JSONDecodeError:
            pos = text.find("{", pos + 1)
    return None


def _parse_json_lenient(text: Any) -> Optional[dict[str, Any]]:
    """LLM 応答本文 (文字列想定) を JSON dict に落とす。

    思考ブロック・コードフェンス・前後の説明文には寛容にする。
    """
    stripped = strip_reasoning(text)
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        m = _JSON_FENCE_RE.search(stripped)
        value = None
        if m:
            try:
                value = json.loads(m.group(1))
            except json.JSONDecodeError:
                value = None
        if value is None:
            value = _first_json_object(stripped)
        if value is None:
            _logger.debug("llm.json_parse_failed", text_prefix=stripped[:80])
            return None
    return value if isinstance(value, dict) else None


def _text_completion_kwargs(
    messages: list[dict[str, str]],
    *,
    model: Optional[str] = None,
    role: str = "light",
    agent_key: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
    timeout: float = 30.0,
    num_retries: int = 0,
) -> tuple[dict[str, Any], str] | None:
    """LiteLLM completion / acompletion 共通 kwargs。未設定時は ``None``。"""
    cfg = _completion_config(role=role, agent_key=agent_key, model=model)
    if cfg is None:
        _logger.debug("llm.config_missing")
        return None

    prefixed = _apply_prefix(cfg.provider, cfg.model)

    kwargs: dict[str, Any] = {
        "model": prefixed,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
        "stream": False,
        "num_retries": num_retries,
    }
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    if cfg.provider == "bedrock" and cfg.aws_region:
        kwargs["aws_region_name"] = cfg.aws_region
    return kwargs, cfg.provider


def _extract_text_content(resp: Any) -> Optional[str]:
    try:
        content = resp["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str):
        return None
    stripped = strip_reasoning(content)
    return stripped or None


def try_text_completion(
    messages: list[dict[str, str]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
    timeout: float = 30.0,
) -> Optional[str]:
    """LiteLLM でテキスト応答を返す。失敗時は ``None``。"""
    try:
        import litellm  # type: ignore
    except ImportError:
        _logger.debug("llm.litellm_not_installed")
        return None

    built = _text_completion_kwargs(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if built is None:
        return None
    kwargs, provider = built

    try:
        resp = litellm.completion(**kwargs)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        _logger.warning(
            "llm.text_completion_failed", provider=provider, error=str(e)
        )
        return None

    return _extract_text_content(resp)


async def try_text_completion_async(
    messages: list[dict[str, str]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
    timeout: float = 30.0,
) -> Optional[str]:
    """LiteLLM ``acompletion`` でテキスト応答を返す。失敗時は ``None``。"""
    try:
        import litellm  # type: ignore
    except ImportError:
        _logger.debug("llm.litellm_not_installed")
        return None

    built = _text_completion_kwargs(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if built is None:
        return None
    kwargs, provider = built

    try:
        resp = await litellm.acompletion(**kwargs)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        _logger.warning(
            "llm.text_completion_async_failed", provider=provider, error=str(e)
        )
        return None

    return _extract_text_content(resp)


__all__ = [
    "strip_reasoning",
    "try_json_completion",
    "try_text_completion",
    "try_text_completion_async",
]
