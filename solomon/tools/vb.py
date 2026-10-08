"""VB試験 (バルブボディ油圧単体試験) 帳票テキストの検出・デコード・パース。

公式仕様: V/Bフォーマット (S10300) — 固定長テキスト、国内 CP932 / 海外 UTF-8。

構成ブロック:
  1. ヘッダ部 — タイトル + ``キー:[ 値 ]`` メタ行
  2. 静圧データ — 列ヘッダー + ステップごと 3 行 (本行 / 流量 / 特殊)
  3. 過渡・特殊 (任意) — ステップ後に 4 行 (過渡ヘッダ + 圧種 T1/T2 ×3)
  4. 調圧データ (任意) — ファイル末尾の [ PL ] / [ PL-T ] テーブル

受領サンプル (21件) は CP932・CRLF・BOM なし。Graph 取込はヘッダメタ + 静圧ステップを対象とする。
"""
from __future__ import annotations

import re
from typing import Any

from solomon.tools.kanken import decode_kanken_bytes

_VB_TITLE_MARKERS = (
    "Ｖ／Ｂ機能テスター",
    "V/B機能テスター",
    "VB機能テスター",
    "V/B Functional-Tester",
    "Functional-Tester Examination",
)
_HEADER_BRACKET_RE = re.compile(
    r"([\w/]+(?:No)?)\s*:\s*\[\s*([^\]]*?)\s*\]|([\w/]+)\[\s*([^\]]*?)\s*\]"
)
_STEP_MAIN_RE = re.compile(r"^\s*(\d+)\s+(.+)$")
_FLOW_SUBROW_RE = re.compile(r"^\s+(流量|FLUX)\s", re.I)
_SPECIAL_SUBROW_RE = re.compile(r"^\s+(特殊|Spec)\s", re.I)
_TABLE_HEADER_RE = re.compile(r"^No\.\s")


def decode_vb_bytes(raw: bytes) -> tuple[str, str]:
    """VB 帳票 bytes を UTF-8 文字列にデコードする。"""
    return decode_kanken_bytes(raw)


def is_vb_report_text(text: str) -> bool:
    """VB 試験帳票テキストかどうかをヒューリスティックに判定する。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    if any(marker in lines[0] for marker in _VB_TITLE_MARKERS):
        return True
    header = lines[1]
    if "V/B" in header and ("判定" in header or "Judge" in header) and "[" in header:
        return True
    return "Model:" in header and "Judge:" in header


def parse_vb_header_line(line: str) -> dict[str, str]:
    """2行目の ``キー:[ 値 ]`` 形式ヘッダーをパースする。"""
    meta: dict[str, str] = {}
    for match in _HEADER_BRACKET_RE.finditer(line):
        if match.group(1):
            key, value = match.group(1), match.group(2)
        else:
            key, value = match.group(3), match.group(4)
        meta[key.strip()] = value.strip()
    return meta


def normalize_vb_meta(meta: dict[str, str]) -> dict[str, str]:
    """Neo4j / Graph 用に VB メタキーを正規化する。"""
    out = dict(meta)
    serial = (
        meta.get("V/B機番")
        or meta.get("VB機番")
        or meta.get("VB_SERIAL")
        or ""
    ).strip()
    if serial:
        out["VB_SERIAL"] = serial
        out["V/B機番"] = serial
    test_date = (meta.get("テスト日時") or meta.get("TEST_DATE") or "").strip()
    if test_date:
        out["DATE"] = test_date
        out["テスト日時"] = test_date
    judge = (meta.get("判定") or meta.get("JUDGE") or "").strip()
    if judge:
        out["JUDGE"] = judge
        out["判定"] = judge
    model = (meta.get("機種") or meta.get("MODEL") or "").strip()
    if model:
        out["MODEL"] = model
        out["機種"] = model
    for src, dst in (
        ("ﾃｽﾄNo", "TEST_NO"),
        ("テストNo", "TEST_NO"),
        ("TestNo", "TEST_NO"),
        ("ﾜｰｸNo", "WORK_NO"),
        ("ワークNo", "WORK_NO"),
        ("号機", "STATION_NO"),
        ("MachineNo", "STATION_NO"),
        ("ｼﾘｱﾙ No", "SERIAL_NO"),
        ("SerialNo", "SERIAL_NO"),
        ("ﾊﾟﾚｯﾄNo", "PALLET_NO"),
        ("V/BNo", "VB_SERIAL"),
        ("Model", "MODEL"),
    ):
        if meta.get(src):
            out[dst] = meta[src].strip()
            out[src] = meta[src].strip()
    return out


def _extract_flow_rate(flow_line: str) -> str:
    for pattern in (r"流量\s*([\d.]+L?)", r"FLUX\s*([\d.]+L?)"):
        match = re.search(pattern, flow_line, re.I)
        if match:
            return match.group(1)
    return ""


def _is_step_triplet(lines: list[str], index: int) -> bool:
    """静圧ステップの 3 行 (本行 / 流量|FLUX / 特殊|Spec) か判定する。"""
    if index + 2 >= len(lines):
        return False
    if not _STEP_MAIN_RE.match(lines[index]):
        return False
    return bool(_FLOW_SUBROW_RE.match(lines[index + 1])) and bool(
        _SPECIAL_SUBROW_RE.match(lines[index + 2])
    )


def _skip_transition_block(lines: list[str], index: int) -> int:
    """過渡・特殊ブロック (任意) をスキップして次の行 index を返す。"""
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if re.match(r"^\s*過渡\s*$", lines[index]) or stripped.startswith("Tran Spec"):
            index += 1
            continue
        if stripped.startswith("圧種") or stripped.startswith("K.Pr"):
            index += 1
            continue
        if _is_step_triplet(lines, index):
            return index
        if stripped.startswith("調圧データ"):
            return index
        index += 1
    return index


def parse_vb_bytes(raw: bytes) -> dict[str, Any]:
    """VB 帳票 bytes をメタデータ + ステップ行にパースする。"""
    encoding, text = decode_vb_bytes(raw)
    lines = text.splitlines()
    meta: dict[str, str] = {}
    if lines:
        meta["TITLE"] = lines[0].strip()
    if len(lines) >= 2:
        meta.update(parse_vb_header_line(lines[1]))
    meta_kv = normalize_vb_meta(meta)

    header_row: int | None = None
    data_start = 4
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _TABLE_HEADER_RE.match(stripped) or (
            stripped.startswith("No.") and "SOL" in stripped
        ):
            header_row = index
            data_start = index + 1
            break

    rows: list[dict[str, Any]] = []
    index = data_start
    while index < len(lines):
        if not _is_step_triplet(lines, index):
            if lines[index].strip().startswith("調圧データ"):
                break
            index += 1
            continue
        match = _STEP_MAIN_RE.match(lines[index])
        assert match is not None
        step_no = int(match.group(1))
        main_body = match.group(2).strip()
        parts = main_body.split()
        title = parts[0] if parts else ""
        mode = parts[1] if len(parts) > 1 else ""
        flow_line = lines[index + 1].strip()
        special_line = lines[index + 2].strip()
        rows.append(
            {
                "step_no": step_no,
                "title": title,
                "mode": mode,
                "flow_rate": _extract_flow_rate(flow_line),
                "raw_main": main_body,
                "raw_flow": flow_line,
                "raw_special": special_line,
            }
        )
        index += 3
        index = _skip_transition_block(lines, index)

    pressure_regulation = _parse_pressure_regulation(lines)
    return {
        "format": "vb",
        "encoding": encoding,
        "meta_kv": meta_kv,
        "header_row": header_row,
        "rows": rows,
        "row_count": len(rows),
        "has_pressure_regulation": bool(pressure_regulation),
        "pressure_regulation_rows": len(pressure_regulation),
        "columns": ["step_no", "title", "mode", "flow_rate", "raw_main"],
    }


def _parse_pressure_regulation(lines: list[str]) -> list[str]:
    """末尾の ``調圧データ`` ブロック行を返す (存在しなければ空)。"""
    start: int | None = None
    for index, line in enumerate(lines):
        if "調圧データ" in line.strip():
            start = index
            break
    if start is None:
        return []
    return [ln.strip() for ln in lines[start:] if ln.strip()]


def vb_rows_to_preview(parsed: dict[str, Any], *, max_rows: int = 200) -> dict[str, Any]:
    """DataFramePreviewTool 互換のプレビュー dict を返す。"""
    rows = parsed.get("rows") or []
    sample = rows[:max_rows]
    columns: list[dict[str, Any]] = []
    for name in parsed.get("columns") or []:
        columns.append(
            {
                "name": name,
                "sample_values": [row.get(name) for row in sample[:20]],
            }
        )
    return {
        "columns": columns,
        "row_count_preview": len(sample),
        "full_row_count_hint": parsed.get("row_count", len(rows)),
        "preview_rows": sample,
        "meta_kv": parsed.get("meta_kv") or {},
    }
