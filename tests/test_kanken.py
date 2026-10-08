"""J5 完検 (kanken) フォーマットの検出・パーステスト。"""
from __future__ import annotations

import base64
from pathlib import Path

from solomon.tools.format import KankenSniffTool, MagicByteTool
from solomon.tools.kanken import (
    decode_kanken_bytes,
    is_kanken_text,
    parse_kanken_bytes,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "kanken_sample_cp932.txt"


def test_decode_shift_jis_fixture() -> None:
    raw = _FIXTURE.read_bytes()
    encoding, text = decode_kanken_bytes(raw)
    assert encoding == "cp932"
    assert "VERSION" in text.splitlines()[0]


def test_is_kanken_text_fixture() -> None:
    raw = _FIXTURE.read_bytes()
    _, text = decode_kanken_bytes(raw)
    assert is_kanken_text(text) is True


def test_parse_kanken_fixture_rows_and_meta() -> None:
    parsed = parse_kanken_bytes(_FIXTURE.read_bytes())
    assert parsed["header_row"] == 9
    assert parsed["meta_kv"]["KIBAN"] == "26GYP05301"
    assert parsed["meta_kv"]["DATE"] == "20260707234643"
    assert parsed["row_count"] == 34
    first = parsed["rows"][0]
    assert first["kiban"] == "26GYP05301"
    assert first["step_name"]
    assert first["symbol_name"]


def test_magic_byte_detects_kanken() -> None:
    raw = _FIXTURE.read_bytes()
    result = MagicByteTool().run(
        user_ctx=None,
        content_b64=base64.b64encode(raw).decode("ascii"),
    )
    assert result["status"] == "ok"
    assert result["format"] == "kanken"


def test_kanken_sniff_tool() -> None:
    raw = _FIXTURE.read_bytes()
    result = KankenSniffTool().run(
        user_ctx=None,
        content_b64=base64.b64encode(raw).decode("ascii"),
    )
    assert result["status"] == "ok"
    assert result["format"] == "kanken"
    assert result["supported"] is True
    assert result["source_encoding"] == "cp932"
    assert result["header_row"] == 9
    assert result["meta_kv"]["HINBAN"] == "9"
