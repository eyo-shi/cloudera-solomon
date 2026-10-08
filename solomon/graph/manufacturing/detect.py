"""受領データ種別の判定。"""

from __future__ import annotations

import re
from typing import Any

from solomon.graph.manufacturing.models import DataType

_KV_RE = re.compile(r"^[A-Z][A-Z0-9_]*\t")

_VB_HINTS = ("vb", "バルブ", "valve", "v/b", "v_b")
_KANKEN_HINTS = ("完検", "kanken", "rlt.品質", "rlt.")
_SHUKKEN_HINTS = ("出検", "shukken", "shukkenid", "j5-ids", "j5_ids")
_MAIN_ID_HINTS = ("メインid", "mainid", "main_id", "main-id", "j5-メイン", "j5_main")


def detect_data_type(
    *,
    key: str,
    format_hint: str = "",
    meta: dict[str, Any] | None = None,
    text: str = "",
) -> DataType:
    """S3 キー・フォーマット・メタ行から受領データ種別を判定する。"""
    meta = {str(k).upper(): str(v).strip() for k, v in (meta or {}).items()}
    path = key.lower()
    fmt = (format_hint or "").lower()

    if fmt == "vb" or (text and _is_vb_report_text(text)):
        return "vb_test"

    if fmt == "kanken" or _path_has(path, _KANKEN_HINTS):
        return "j5_kanken"
    if _path_has(path, _SHUKKEN_HINTS) or path.endswith(".dat"):
        return "j5_shukken_id"
    if _path_has(path, _MAIN_ID_HINTS):
        return "j5_main_id"
    if _path_has(path, _VB_HINTS):
        return "vb_test"

    if meta.get("KIBAN") and meta.get("JUDGE"):
        return "j5_kanken"
    if _meta_has_shukken(meta):
        return "j5_shukken_id"
    # メインID: KIBAN + HINBAN (+ DATE)。VERSION 行がある旧 tab 形式も許容
    if meta.get("KIBAN") and (meta.get("HINBAN") or meta.get("VERSION")):
        return "j5_main_id"

    if meta.get("VB_SERIAL") or meta.get("V/B機番"):
        return "vb_test"

    return "vb_test"


def _is_vb_report_text(text: str) -> bool:
    from solomon.tools.vb import is_vb_report_text

    return is_vb_report_text(text)


def _path_has(path: str, hints: tuple[str, ...]) -> bool:
    return any(h in path for h in hints)


def _meta_has_shukken(meta: dict[str, str]) -> bool:
    joined = " ".join(f"{k} {v}" for k, v in meta.items())
    for token in ("AT機番", "A/T機番", "顧客品番", "通過日時", "AT_SERIAL", "CUSTOMER"):
        if token.upper() in joined.upper() or token in joined:
            return True
    return bool(meta.get("AT_SERIAL") or meta.get("CUSTOMER_PART"))
