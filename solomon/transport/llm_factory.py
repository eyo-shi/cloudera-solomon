"""Crew.ai / LiteLLM 用の LLM オブジェクト構築ファクトリ。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from solomon.transport import config as llm_config
from solomon.transport.config import LLMRoleConfig
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

LLMRole = Literal["light", "strong"]


def _apply_prefix(provider: str, model: str) -> str:
    """LiteLLM が要求する provider prefix を付ける。既に付いていればそのまま。"""
    if "/" in model:
        return model
    if provider == "cai":
        return f"openai/{model}"
    if provider == "anthropic":
        return f"anthropic/{model}"
    if provider == "openai":
        return f"openai/{model}"
    if provider == "bedrock":
        return f"bedrock/{model}"
    return model


def _build_crewai_llm(cfg: LLMRoleConfig) -> Optional[Any]:
    try:
        from crewai import LLM  # type: ignore
    except ImportError:
        _logger.debug("llm_factory.crewai_not_installed", role=cfg.role)
        return None

    prefixed = _apply_prefix(cfg.provider, cfg.model)
    kwargs: dict[str, Any] = {"model": prefixed}
    if cfg.api_base:
        kwargs["base_url"] = cfg.api_base
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    if cfg.provider == "bedrock" and cfg.aws_region:
        kwargs["aws_region_name"] = cfg.aws_region

    try:
        return LLM(**kwargs)
    except Exception as e:  # noqa: BLE001
        _logger.warning(
            "llm_factory.build_failed",
            provider=cfg.provider,
            role=cfg.role,
            error=str(e),
        )
        return None


def build_llm(role: LLMRole = "light") -> Optional[Any]:
    """Role (light / strong) に応じた Crew.ai LLM を組み立てる。"""
    cfg = llm_config.get_llm_role_config(role)
    if cfg is None:
        _logger.debug("llm_factory.no_config", role=role)
        return None
    return _build_crewai_llm(cfg)


def build_llm_for_agent(agent_key: str) -> Optional[Any]:
    """Agent キーに紐づく provider + model で Crew.ai LLM を組み立てる。"""
    cfg = llm_config.get_llm_agent_config(agent_key)
    if cfg is None:
        _logger.debug("llm_factory.no_agent_config", agent=agent_key)
        return None
    return _build_crewai_llm(cfg)


def build_llm_pair() -> tuple[Optional[Any], Optional[Any]]:
    """(light, strong) — Agent 別設定が無い場合の shortcut。"""
    return build_llm("light"), build_llm("strong")


__all__ = [
    "build_llm",
    "build_llm_for_agent",
    "build_llm_pair",
    "LLMRole",
    "_apply_prefix",
]
