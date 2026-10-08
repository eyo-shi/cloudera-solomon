"""完検 (J5 完成検査) テキストファイルの検出・デコード・パース。

公式仕様: AW品質管理 標準データファイルフォーマット (S10200/S10204)。

構成:
  * ヘッダ部: ``KEY\\tVALUE`` または固定長スペース区切り
    必須 KIBAN(or BUHIN) / HINBAN / DATE、任意 TESTERNO / JUDGE(1=OK,2=NG) 等
  * 測定結果部: ``STP`` 見出し行 + 126バイト固定長データ行
    (STP / ステップ名称 / M / シンボル / シンボル名称 / 単位 / 規格 / 初検 / J / 再検…)

受領 J5-完検サンプルは tab メタ + スペース区切り固定幅測定行のバリアント。
国内 CP932 が多い。UTF-8 / BOM 付き UTF-8 も許容する。
"""
from __future__ import annotations

import re
from typing import Any, Optional

_META_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*\t")
_KNOWN_META_KEYS = frozenset(
    {
        "VERSION",
        "KIBAN",
        "HINBAN",
        "DATE",
        "TESTERNO",
        "JUDGE",
        "DRIVE",
        "LIMIT",
        "ARRANGE",
    }
)
_KNOWN_UNITS = frozenset({"℃", "rpm", "Nm", "A", "V", "kW", "Hz", "Pa", "MPa"})
_STEP_HINT_RE = re.compile(r"(回転|作動|計測|停止|NV|確認|ステップ|STEP\d+\))")
_SYMBOL_HINT_RE = re.compile(r"[A-Z]{2,}\d|STEP\d+\)|温度|回転|トルク|電流|判定|MD値")

_DATA_COLUMN_NAMES = (
    "step_name",
    "symbol_name",
    "unit",
    "spec_lower",
    "spec_upper",
    "first_value",
    "j_reinspect",
    "j",
)

_META_COLUMN_NAMES = tuple(k.lower() for k in sorted(_KNOWN_META_KEYS))


def decode_kanken_bytes(raw: bytes) -> tuple[str, str]:
    """完検ファイル bytes を UTF-8 テキストにデコードする。

    Returns:
        (source_encoding, text) — text は論理的に UTF-8 文字列。
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", raw[len(b"\xef\xbb\xbf") :].decode("utf-8")
    try:
        return "utf-8", raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in ("cp932", "shift_jis"):
        try:
            return enc, raw.decode(enc)
        except UnicodeDecodeError:
            continue
    try:
        from charset_normalizer import from_bytes  # type: ignore
    except ImportError as e:
        raise ValueError("charset-normalizer is required for kanken decode") from e
    result = from_bytes(raw).best()
    if result is None:
        raise ValueError("could not detect encoding for kanken file")
    encoding = result.encoding or "utf-8"
    return encoding, str(result)


def is_kanken_text(text: str) -> bool:
    """完検フォーマットかどうかをヒューリスティックに判定する。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False

    meta_keys: list[str] = []
    idx = 0
    while idx < len(lines) and idx < 20:
        line = lines[idx]
        if _META_KEY_RE.match(line):
            key = line.split("\t", 1)[0].strip()
            meta_keys.append(key)
            idx += 1
            continue
        break

    if idx == 0:
        return False
    if not {"VERSION", "KIBAN", "DATE"}.issubset(set(meta_keys)):
        return False
    if idx >= len(lines):
        return False

    # メタ行の次は列ヘッダー、その次から測定行
    header_line = lines[idx]
    if "\t" in header_line and _META_KEY_RE.match(header_line):
        return False
    data_lines = lines[idx + 1 : idx + 6]
    if not data_lines:
        return False
    parsed_any = any(_split_data_parts(ln) for ln in data_lines)
    return parsed_any


def parse_kanken_text(text: str) -> dict[str, Any]:
    """完検テキストをメタデータ + フラット行にパースする。"""
    lines = text.splitlines()
    meta: dict[str, str] = {}
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            idx += 1
            continue
        if _META_KEY_RE.match(line):
            key, value = line.split("\t", 1)
            meta[key.strip()] = value.strip()
            idx += 1
            continue
        break

    header_row = idx
    header_line = lines[idx].strip() if idx < len(lines) else ""
    idx += 1

    rows: list[dict[str, Any]] = []
    last_step: Optional[str] = None
    while idx < len(lines):
        line = lines[idx]
        idx += 1
        if not line.strip():
            continue
        parsed = _parse_measurement_row(line, last_step=last_step)
        if parsed is None:
            continue
        if parsed.get("step_name"):
            last_step = str(parsed["step_name"])
        row = {k.lower(): meta.get(k.upper(), "") for k in _KNOWN_META_KEYS}
        row.update(parsed)
        rows.append(row)

    columns = list(_META_COLUMN_NAMES) + list(_DATA_COLUMN_NAMES)
    return {
        "format": "kanken",
        "encoding": "utf-8",
        "source_encoding": None,
        "header_row": header_row,
        "header_line": header_line,
        "meta_kv": meta,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }


def parse_kanken_bytes(raw: bytes) -> dict[str, Any]:
    """bytes をデコードして完検パース結果を返す。"""
    source_encoding, text = decode_kanken_bytes(raw)
    result = parse_kanken_text(text)
    result["source_encoding"] = source_encoding
    return result


def kanken_rows_to_preview(
    parsed: dict[str, Any], *, max_rows: int = 200
) -> dict[str, Any]:
    """パース結果を DataFramePreviewTool 互換の形に変換する。"""
    rows = parsed.get("rows") or []
    columns = parsed.get("columns") or []
    preview_rows = rows[:max_rows]
    column_samples: list[dict[str, Any]] = []
    for name in columns:
        samples = [row.get(name) for row in preview_rows[:50]]
        column_samples.append({"name": name, "sample_values": samples})
    return {
        "format": "kanken",
        "columns": column_samples,
        "preview_rows": preview_rows,
        "row_count_preview": len(preview_rows),
        "full_row_count_hint": parsed.get("row_count", len(rows)),
        "meta_kv": parsed.get("meta_kv") or {},
        "header_row": parsed.get("header_row"),
        "source_encoding": parsed.get("source_encoding"),
    }


def _split_data_parts(line: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s{2,}", line.strip()) if p.strip()]


def _looks_like_step(name: str) -> bool:
    if _STEP_HINT_RE.search(name):
        return True
    return name.startswith(" ") is False and not _SYMBOL_HINT_RE.search(name[:12])


def _looks_like_unit(token: str) -> bool:
    if token in _KNOWN_UNITS:
        return True
    if len(token) <= 3 and not re.fullmatch(r"-?\d+(?:\.\d+)?", token):
        return True
    return False


def _parse_measurement_row(
    line: str, *, last_step: Optional[str]
) -> Optional[dict[str, Any]]:
    parts = _split_data_parts(line)
    if len(parts) < 5:
        return None

    step_name: Optional[str] = last_step
    idx = 0

    if len(parts) >= 7 and _looks_like_step(parts[0]) and not parts[0].endswith(")"):
        step_name = parts[0]
        idx = 1

    remaining = parts[idx:]
    if len(remaining) == 5:
        symbol, spec_lower, spec_upper, first_value, j_reinspect = remaining
        unit = ""
        j = "0"
    elif len(remaining) == 6:
        if _looks_like_unit(remaining[1]):
            symbol, unit, spec_lower, spec_upper, first_value, j_reinspect = remaining
        else:
            symbol, spec_lower, spec_upper, first_value, j_reinspect, j = (
                remaining[0],
                remaining[1],
                remaining[2],
                remaining[3],
                remaining[4],
                remaining[5],
            )
            unit = ""
            return _build_row(
                step_name, symbol, unit, spec_lower, spec_upper, first_value, j_reinspect, j
            )
        j = "0"
    elif len(remaining) == 7:
        symbol, unit, spec_lower, spec_upper, first_value, j_reinspect, j = remaining
    elif len(remaining) >= 8:
        symbol, unit, spec_lower, spec_upper, first_value, j_reinspect, j = remaining[:7]
    else:
        return None

    return _build_row(
        step_name, symbol, unit, spec_lower, spec_upper, first_value, j_reinspect, j
    )


def _build_row(
    step_name: Optional[str],
    symbol: str,
    unit: str,
    spec_lower: str,
    spec_upper: str,
    first_value: str,
    j_reinspect: str,
    j: str,
) -> dict[str, Any]:
    return {
        "step_name": step_name or "",
        "symbol_name": symbol,
        "unit": unit,
        "spec_lower": spec_lower,
        "spec_upper": spec_upper,
        "first_value": first_value,
        "j_reinspect": j_reinspect,
        "j": j,
    }


__all__ = [
    "decode_kanken_bytes",
    "is_kanken_text",
    "kanken_rows_to_preview",
    "parse_kanken_bytes",
    "parse_kanken_text",
]
