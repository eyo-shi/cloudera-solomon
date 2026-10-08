"""ID アドレスマップによる hex ダンプ解釈のテスト。"""
from __future__ import annotations

from pathlib import Path

from solomon.graph.manufacturing.extract import build_payload_from_bytes
from solomon.graph.manufacturing.id_address_map import (
    decode_id_dump_fields,
    group_field_spans,
    load_address_map_entries,
    resolve_address_map_path,
)
from solomon.graph.manufacturing.id_dump import parse_hex_dump_lines

_FIXTURE_MAP = Path(__file__).parent / "fixtures" / "id_address_map_t447_subset.json"
_MAIN_ID = Path(__file__).parent / "fixtures" / "main_id_sample_utf8.txt"
_SHUKKEN = Path(__file__).parent / "fixtures" / "shukken_sample.DAT"


def test_resolve_address_map_path_finds_fixture() -> None:
    path = resolve_address_map_path(str(_FIXTURE_MAP))
    assert path is not None
    assert path.name == "id_address_map_t447_subset.json"


def test_group_field_spans_merges_continuation_rows() -> None:
    entries = load_address_map_entries(_FIXTURE_MAP)
    spans = group_field_spans(entries)
    kiban_span = next(
        (span for span in spans if "A/T機番" in span.info or "ｼﾘｱﾙ" in span.info),
        None,
    )
    assert kiban_span is not None
    assert kiban_span.end >= kiban_span.start


def test_decode_main_id_kiban_from_dump() -> None:
    text = _MAIN_ID.read_text(encoding="utf-8-sig")
    fields = decode_id_dump_fields(
        text,
        data_type="j5_main_id",
        map_path=_FIXTURE_MAP,
        trace_id="26G3V05354",
    )
    by_label = {field.label: field.value for field in fields}
    assert by_label.get("KIBAN") == "26G3V05354"
    assert by_label.get("HINBAN") == "3061042090"


def test_build_payload_includes_dump_fields() -> None:
    payload = build_payload_from_bytes(
        bucket="demo",
        key="file_sample/J5-メインID/20260707235801_26G3V05354.txt",
        body=_MAIN_ID.read_bytes(),
        map_path=str(_FIXTURE_MAP),
    )
    assert payload.data_type == "j5_main_id"
    assert len(payload.dump_fields) > 0


def test_parse_hex_dump_memory() -> None:
    text = _SHUKKEN.read_text(encoding="utf-8")
    memory = parse_hex_dump_lines(text)
    assert memory[0x36] == ord("2")
    assert memory[0x37] == ord("6")
