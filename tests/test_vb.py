"""VB 試験帳票パーサーのテスト。"""
from __future__ import annotations

from pathlib import Path

from solomon.tools.vb import is_vb_report_text, parse_vb_bytes

_FIXTURE = Path(__file__).parent / "fixtures" / "vb_sample_cp932.TXT"


def test_is_vb_report_text() -> None:
    text = _FIXTURE.read_bytes().decode("cp932")
    assert is_vb_report_text(text)


def test_parse_vb_bytes_fixture() -> None:
    parsed = parse_vb_bytes(_FIXTURE.read_bytes())
    meta = parsed["meta_kv"]
    assert meta["VB_SERIAL"] == "0000101211"
    assert meta["DATE"] == "2018-11-30 00:00:52"
    assert meta["JUDGE"] == "NG"
    assert meta["MODEL"] == "50"
    assert parsed["row_count"] == 146
    assert parsed["rows"][0]["title"] == "FL(Rev)"
    assert parsed["rows"][0]["mode"] == "R"
    assert parsed["rows"][0]["flow_rate"] == "27.0L"
