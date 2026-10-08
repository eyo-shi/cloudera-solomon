"""J5 受領データ向け製造トレーサビリティグラフのテスト。"""
from __future__ import annotations

from pathlib import Path

from solomon.graph.manufacturing.detect import detect_data_type
from solomon.graph.manufacturing.extract import build_payload_from_bytes

_FIXTURE = Path(__file__).parent / "fixtures" / "kanken_sample_cp932.txt"


def test_detect_kanken_from_fixture_key() -> None:
    assert (
        detect_data_type(
            key="file_sample/J5-完検/260707234643.rlt.品質.txt",
            format_hint="kanken",
            meta={"KIBAN": "26GYP05301", "JUDGE": "1"},
        )
        == "j5_kanken"
    )


def test_detect_vb_from_key() -> None:
    assert (
        detect_data_type(key="file_sample/VB/VB_TEST_001.TXT", format_hint="text")
        == "vb_test"
    )


def test_detect_main_id_from_key() -> None:
    assert (
        detect_data_type(
            key="file_sample/J5-メインID/board_dump.txt",
            meta={"KIBAN": "26GYP05301", "VERSION": "1"},
        )
        == "j5_main_id"
    )


def test_detect_shukken_from_dat_extension() -> None:
    assert (
        detect_data_type(key="file_sample/J5-出検ID/AT12345.DAT")
        == "j5_shukken_id"
    )


def test_build_payload_kanken() -> None:
    raw = _FIXTURE.read_bytes()
    payload = build_payload_from_bytes(
        bucket="demo-bucket",
        key="file_sample/J5-完検/260707234643.rlt.品質.txt",
        body=raw,
        format_hint="kanken",
    )
    assert payload.data_type == "j5_kanken"
    assert payload.kiban == "26GYP05301"
    assert payload.judge == "1"
    assert payload.row_count == 34
    assert len(payload.measurements) == 34
    assert payload.board_id == "board:26GYP05301"
    assert payload.assembly_id == "unit:26GYP05301"
    assert payload.trace_id == "26GYP05301"


def test_build_payload_shukken_dat() -> None:
    raw = (
        Path(__file__).parent / "fixtures" / "shukken_sample.DAT"
    ).read_bytes()
    payload = build_payload_from_bytes(
        bucket="demo-bucket",
        key="file_sample/shukken/26G3V05286_J5-IDS_20260708000201.DAT",
        body=raw,
    )
    assert payload.data_type == "j5_shukken_id"
    assert payload.at_serial == "26G3V05286"
    assert payload.customer_part_no == "3061042040"
    assert payload.date == "2026/07/08 00:02:01"
    assert payload.assembly_id == "unit:26G3V05286"
    assert payload.kiban == "26G3V05286"
    assert payload.board_id == "board:26G3V05286"
    assert payload.trace_id == "26G3V05286"
    assert payload.row_count > 400


def test_build_payload_main_id_tab_legacy() -> None:
    body = "KIBAN\t26G3V05354\nHINBAN\t9\nDATE\t20260708000101\nVERSION\t1\n".encode()
    payload = build_payload_from_bytes(
        bucket="b",
        key="file_sample/J5-メインID/26G3V05354_dump.txt",
        body=body,
    )
    assert payload.data_type == "j5_main_id"
    assert payload.trace_id == "26G3V05354"
    assert payload.board_id == "board:26G3V05354"
    assert payload.assembly_id == "unit:26G3V05354"


def test_build_payload_main_id_utf8_comma_fixture() -> None:
    raw = (
        Path(__file__).parent / "fixtures" / "main_id_sample_utf8.txt"
    ).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    payload = build_payload_from_bytes(
        bucket="demo-bucket",
        key="file_sample/J5-メインID/20260707235801_26G3V05354.txt",
        body=raw,
    )
    assert payload.data_type == "j5_main_id"
    assert payload.kiban == "26G3V05354"
    assert payload.hinban == "3061042090"
    assert payload.date == "2026/07/07 23:58:01"
    assert payload.trace_id == "26G3V05354"
    assert payload.row_count > 400


def test_trace_id_links_kanken_and_shukken() -> None:
    """同一 ID (26G3V05304) は完検 KIBAN と出検 A/T機番 で同じ trace_id になる。"""
    shared_id = "26G3V05304"
    kanken = build_payload_from_bytes(
        bucket="b",
        key="file_sample/J5-完検/x.txt",
        body=f"KIBAN\t{shared_id}\nHINBAN\t1\nDATE\t20260707\nJUDGE\t1\n".encode(),
        format_hint="kanken",
    )
    shukken = build_payload_from_bytes(
        bucket="b",
        key=f"file_sample/shukken/{shared_id}_J5-IDS.DAT",
        body=f"A/T機番,{shared_id}\n顧客品番,3061042040\n通過日時,2026/07/08\n".encode(),
    )
    assert kanken.trace_id == shared_id
    assert shukken.trace_id == shared_id
    assert kanken.assembly_id == shukken.assembly_id == f"unit:{shared_id}"
    assert kanken.board_id == shukken.board_id == f"board:{shared_id}"


def test_build_payload_vb_fallback() -> None:
    body = "機種: VB-TEST\n判定: OK\nテスト日時: 20260707\n".encode("cp932")
    payload = build_payload_from_bytes(
        bucket="b",
        key="file_sample/VB/VB_260707234643.TXT",
        body=body,
        format_hint="text",
    )
    assert payload.data_type == "vb_test"
    assert payload.valve_body_id.startswith("vb:")


def test_build_payload_vb_cp932_fixture() -> None:
    raw = (Path(__file__).parent / "fixtures" / "vb_sample_cp932.TXT").read_bytes()
    payload = build_payload_from_bytes(
        bucket="demo-bucket",
        key="file_sample/VB/18113000005200001012113.TXT",
        body=raw,
    )
    assert payload.data_type == "vb_test"
    assert payload.vb_serial == "0000101211"
    assert payload.date == "2018-11-30 00:00:52"
    assert payload.judge == "NG"
    assert payload.valve_body_id == "vb:0000101211"
    assert payload.row_count == 146
