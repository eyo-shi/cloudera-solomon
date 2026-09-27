"""Deploy 後の設定不足 (SetupGuide) 用ペイロード。"""

from __future__ import annotations

from solomon.transport.config import get_llm_config


def llm_not_configured_payload() -> dict[str, str] | None:
    """LLM 未設定なら SetupGuide 用 dict を返す。設定済みなら None。"""
    if get_llm_config() is not None:
        return None
    return {
        "error_code": "LLM_NOT_CONFIGURED",
        "message": "LLM プロバイダが設定されていません。",
        "instruction": (
            "Project → Settings → Advanced → Environment Variables に "
            "SOLOMON_LLM_PROVIDER (cai / anthropic / openai / bedrock) と、"
            "選択したプロバイダに必要な API キー / エンドポイントを設定し、"
            "Application を再起動してください。"
        ),
    }
