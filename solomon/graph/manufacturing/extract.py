"""受領データファイルからグラフ用メタデータを抽出する。"""

from __future__ import annotations

import re
from typing import Any

from solomon.graph.manufacturing.detect import detect_data_type
from solomon.graph.manufacturing.id_address_map import decode_id_dump_fields
from solomon.graph.manufacturing.models import (
    ManufacturingGraphPayload,
    MeasurementNode,
)
from solomon.tools.kanken import decode_kanken_bytes, parse_kanken_bytes
from solomon.tools.vb import parse_vb_bytes

_META_LINE_RE = re.compile(r"^([A-Za-z_/][A-Za-z0-9_/]*)\s*[:：]\s*(.+)$")
_HEADER_BRACKET_RE = re.compile(
    r"([\w/]+(?:No)?)\s*:\s*\[\s*([^\]]*?)\s*\]|([\w/]+)\[\s*([^\]]*?)\s*\]"
)
_KV_TAB_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\t(.+)$")
_KV_COMMA_RE = re.compile(r"^([^,]+),(.+)$")
_HEX_DUMP_RE = re.compile(r"^[0-9A-Fa-f]{4}\(H\),")
_SHUKKEN_FILENAME_RE = re.compile(r"^([^_]+)_J5-IDS_", re.I)
_AT_SERIAL_RES = (
    re.compile(r"(?:A/?T機番|AT機番|AT_SERIAL|機番)\s*[:：]?\s*(\S+)", re.I),
    re.compile(r"^AT[_-]?([A-Z0-9\-]+)", re.I),
)
_CUSTOMER_PART_RES = (
    re.compile(r"(?:顧客品番|CUSTOMER(?:_PART)?|CUSTOMER_PART_NO)\s*[:：]?\s*(\S+)", re.I),
)


def build_payload_from_bytes(
    *,
    bucket: str,
    key: str,
    body: bytes,
    format_hint: str = "",
    map_path: str | None = None,
) -> ManufacturingGraphPayload:
    """S3 オブジェクト bytes から ManufacturingGraphPayload を組み立てる。"""
    encoding, text = decode_kanken_bytes(body)
    meta = _extract_meta(text)
    data_type = detect_data_type(
        key=key, format_hint=format_hint, meta=meta, text=text
    )

    payload = ManufacturingGraphPayload(
        data_type=data_type,
        bucket=bucket,
        key=key,
        meta=meta,
    )

    if data_type == "j5_kanken":
        parsed = parse_kanken_bytes(body)
        payload.meta = parsed.get("meta_kv") or meta
        payload.kiban = str(payload.meta.get("KIBAN", "")).strip()
        payload.hinban = str(payload.meta.get("HINBAN", "")).strip()
        payload.date = str(payload.meta.get("DATE", "")).strip()
        payload.judge = str(payload.meta.get("JUDGE", "")).strip()
        payload.measurements = [
            MeasurementNode(
                step_name=str(row.get("step_name", "")),
                symbol_name=str(row.get("symbol_name", "")),
                unit=str(row.get("unit", "")),
                spec_lower=str(row.get("spec_lower", "")),
                spec_upper=str(row.get("spec_upper", "")),
                first_value=str(row.get("first_value", "")),
                j_reinspect=str(row.get("j_reinspect", "")),
                j=str(row.get("j", "")),
            )
            for row in parsed.get("rows") or []
            if row.get("symbol_name")
        ]
        payload.row_count = int(parsed.get("row_count") or 0)
        _apply_trace_id(payload)
        return payload

    if data_type == "j5_main_id":
        payload.kiban = str(meta.get("KIBAN", "")).strip()
        payload.hinban = str(meta.get("HINBAN", "")).strip()
        payload.date = str(meta.get("DATE", "")).strip()
        payload.row_count = _count_hex_dump_rows(text)
        _apply_trace_id(payload)
        payload.dump_fields = decode_id_dump_fields(
            text,
            data_type=data_type,
            trace_id=payload.trace_id,
            map_path=map_path,
        )
        return payload

    if data_type == "j5_shukken_id":
        payload.at_serial = _extract_at_serial(text, meta, key=key)
        payload.customer_part_no = _extract_customer_part(text, meta)
        payload.kiban = str(meta.get("KIBAN", "")).strip()
        payload.date = str(
            meta.get("DATE", meta.get("通過日時", meta.get("通过日時", "")))
        ).strip()
        payload.row_count = _count_hex_dump_rows(text)
        _apply_trace_id(payload)
        payload.dump_fields = decode_id_dump_fields(
            text,
            data_type=data_type,
            trace_id=payload.trace_id,
            map_path=map_path,
        )
        return payload

    # vb_test
    parsed = parse_vb_bytes(body)
    payload.meta = parsed.get("meta_kv") or meta
    payload.vb_serial = _extract_vb_serial(key, payload.meta, text)
    payload.date = str(
        payload.meta.get("DATE", payload.meta.get("テスト日時", ""))
    ).strip()
    payload.judge = str(
        payload.meta.get("JUDGE", payload.meta.get("判定", ""))
    ).strip()
    payload.row_count = int(parsed.get("row_count") or 0)
    return payload


def _apply_trace_id(payload: ManufacturingGraphPayload) -> None:
    """出検 A/T機番 と完検 KIBAN を同一 trace ID として正規化する。

    受領データの突合結果:
      * 完検 KIBAN ≡ 出検 A/T機番（一致する ID あり）
      * メインID KIBAN も同一フォーマット（26G3V / 26GYP + 5桁）
    Neo4j では Board / AssemblyUnit を ``unit:{trace_id}`` / ``board:{trace_id}`` で MERGE する。
    """
    trace = (payload.kiban or payload.at_serial or "").strip()
    if not trace:
        return
    payload.kiban = trace
    if payload.data_type == "j5_shukken_id":
        payload.at_serial = payload.at_serial or trace
    # j5_main_id / j5_kanken は kiban が trace_id そのもの


def meta_kv_dict_to_list(meta: dict[str, Any]) -> list[dict[str, str]]:
    """Neo4j / OpenSearch 互換の list[{key,value}] に変換。"""
    return [{"key": str(k), "value": str(v)} for k, v in meta.items() if str(k).strip()]


def _extract_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in text.splitlines()[:40]:
        stripped = line.strip()
        if not stripped:
            if meta:
                break
            continue
        if _HEX_DUMP_RE.match(stripped):
            break
        m = _KV_TAB_RE.match(line)
        if m:
            _store_meta(meta, m.group(1).strip(), m.group(2).strip())
            continue
        m = _KV_COMMA_RE.match(stripped)
        if m:
            _store_meta(meta, m.group(1).strip(), m.group(2).strip())
            continue
        m = _META_LINE_RE.match(stripped)
        if m:
            _store_meta(meta, m.group(1).strip(), m.group(2).strip())
            continue
        if "[" in stripped and _HEADER_BRACKET_RE.search(stripped):
            for match in _HEADER_BRACKET_RE.finditer(stripped):
                if match.group(1):
                    _store_meta(meta, match.group(1).strip(), match.group(2).strip())
                else:
                    _store_meta(meta, match.group(3).strip(), match.group(4).strip())
            continue
        if meta and not re.search(r"\s{2,}", stripped):
            break
    return meta


def _store_meta(meta: dict[str, str], key: str, value: str) -> None:
    cleaned = value.strip()
    meta[key] = cleaned
    upper = key.upper()
    if key in ("A/T機番", "AT機番", "機番") or upper in {"AT_SERIAL", "AT機番"}:
        meta["AT_SERIAL"] = cleaned
        meta["A/T機番"] = cleaned
    elif key == "顧客品番" or upper in {"CUSTOMER_PART", "CUSTOMER_PART_NO"}:
        meta["CUSTOMER_PART_NO"] = cleaned
        meta["顧客品番"] = cleaned
    elif key in ("通過日時", "DATE") or upper == "DATE":
        meta["DATE"] = cleaned
        meta["通過日時"] = cleaned
    elif upper == "KIBAN":
        meta["KIBAN"] = cleaned
    elif upper == "HINBAN":
        meta["HINBAN"] = cleaned
    elif upper == "VERSION":
        meta["VERSION"] = cleaned
    elif key in ("V/B機番", "VB機番") or upper == "VB_SERIAL":
        meta["VB_SERIAL"] = cleaned
        meta["V/B機番"] = cleaned
    elif key in ("テスト日時",) or upper == "TEST_DATE":
        meta["DATE"] = cleaned
        meta["テスト日時"] = cleaned
    elif key in ("判定",) or upper == "JUDGE":
        meta["JUDGE"] = cleaned
        meta["判定"] = cleaned
    elif key in ("機種",) or upper == "MODEL":
        meta["MODEL"] = cleaned
        meta["機種"] = cleaned


def _extract_at_serial(text: str, meta: dict[str, str], key: str = "") -> str:
    for mk in ("AT_SERIAL", "A/T機番", "AT機番", "機番"):
        if meta.get(mk):
            return meta[mk].strip()
    for pattern in _AT_SERIAL_RES:
        m = pattern.search(text[:4000])
        if m:
            return m.group(1).strip()
    if key:
        stem = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        m = _SHUKKEN_FILENAME_RE.match(stem)
        if m:
            return m.group(1).strip()
    return ""


def _count_hex_dump_rows(text: str) -> int:
    return sum(1 for line in text.splitlines() if _HEX_DUMP_RE.match(line.strip()))


def _extract_customer_part(text: str, meta: dict[str, str]) -> str:
    for key in ("CUSTOMER_PART", "CUSTOMER_PART_NO", "顧客品番"):
        if meta.get(key):
            return meta[key].strip()
    for pattern in _CUSTOMER_PART_RES:
        m = pattern.search(text[:4000])
        if m:
            return m.group(1).strip()
    return ""


def _extract_vb_serial(key: str, meta: dict[str, str], text: str) -> str:
    for mk in ("VB_SERIAL", "V/B機番", "VB機番", "SERIAL"):
        if meta.get(mk):
            return meta[mk].strip()
    stem = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = re.search(r"(\d{10,14})", stem)
    if m:
        return m.group(1)
    m = re.search(r"号機\s*[:：]?\s*(\S+)", text[:2000])
    if m:
        return m.group(1).strip()
    return stem[:48]
