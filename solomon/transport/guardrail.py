"""CrewAI guardrail 向けの出力正規化。"""
from __future__ import annotations

import json
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def unwrap_task_output(output: Any) -> Any:
    """CrewAI の TaskOutput / pydantic / dict / JSON 文字列を素の payload に落とす。"""
    if output is None:
        return output

    if (
        type(output).__name__ == "TaskOutput"
        or (
            hasattr(output, "json_dict")
            and hasattr(output, "raw")
            and hasattr(output, "pydantic")
        )
    ):
        pydantic_val = getattr(output, "pydantic", None)
        if pydantic_val is not None:
            return pydantic_val
        json_dict = getattr(output, "json_dict", None)
        if json_dict is not None:
            return json_dict
        raw = getattr(output, "raw", None)
        if raw is not None:
            return raw

    return output


def parse_guardrail_model(output: Any, model: type[T]) -> tuple[Optional[T], Optional[str]]:
    """guardrail 関数向けに output を Pydantic モデルへ変換する。"""
    unwrapped = unwrap_task_output(output)

    if isinstance(unwrapped, model):
        return unwrapped, None

    if isinstance(unwrapped, dict):
        try:
            return model.model_validate(unwrapped), None
        except ValidationError:
            return None, f"guardrail: could not parse output: {unwrapped!r}"

    if isinstance(unwrapped, str):
        try:
            parsed = json.loads(unwrapped)
        except json.JSONDecodeError:
            return None, f"guardrail: could not parse output: {unwrapped!r}"
        if isinstance(parsed, dict):
            try:
                return model.model_validate(parsed), None
            except ValidationError:
                return None, f"guardrail: could not parse output: {parsed!r}"

    return None, f"guardrail: unexpected output type: {type(output).__name__}"


def guardrail_pass_model(result: BaseModel) -> tuple[bool, str]:
    """CrewAI 0.8+ — guardrail 成功時は第2要素に None 不可。正規化済み JSON を返す。"""
    return True, result.model_dump_json()


__all__ = ["unwrap_task_output", "parse_guardrail_model", "guardrail_pass_model"]
