"""製造トレーサビリティグラフのペイロードモデル。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

DataType = Literal["vb_test", "j5_main_id", "j5_kanken", "j5_shukken_id"]

PRODUCT_PROGRAM_ID = "j5_at_eaxle"
PRODUCT_PROGRAM_NAME = "J5 A/T · e-Axle"


@dataclass
class DumpFieldNode:
    """ID hex ダンプ内の 1 解釈フィールド (アドレスマップ由来)。"""

    address_hex: str
    label: str
    value: str
    address_end_hex: str = ""
    raw_hex: str = ""
    value_type: str = ""
    timing: str = ""
    process_name: str = ""
    trace_id: str = ""

    @property
    def id(self) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", self.label)[:48].strip("_") or "field"
        addr = self.address_hex.replace("(H)", "")
        return f"field:{self.trace_id or 'na'}:{addr}:{slug}"


@dataclass
class MeasurementNode:
    symbol_name: str
    step_name: str = ""
    unit: str = ""
    spec_lower: str = ""
    spec_upper: str = ""
    first_value: str = ""
    j_reinspect: str = ""
    j: str = ""

    @property
    def id(self) -> str:
        safe_symbol = self.symbol_name.replace(" ", "_")[:64]
        safe_step = (self.step_name or "na").replace(" ", "_")[:32]
        return f"meas:{safe_step}:{safe_symbol}"


@dataclass
class ManufacturingGraphPayload:
    """1 ファイル取り込みから構築するグラフ断片。"""

    data_type: DataType
    bucket: str
    key: str
    source_id: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    kiban: str = ""
    hinban: str = ""
    date: str = ""
    judge: str = ""
    at_serial: str = ""
    customer_part_no: str = ""
    vb_serial: str = ""
    measurements: list[MeasurementNode] = field(default_factory=list)
    dump_fields: list[DumpFieldNode] = field(default_factory=list)
    row_count: int = 0

    def __post_init__(self) -> None:
        if not self.source_id:
            self.source_id = f"s3://{self.bucket}/{self.key}"
        if not self.kiban:
            self.kiban = self.meta.get("KIBAN", "").strip()
        if not self.hinban:
            self.hinban = self.meta.get("HINBAN", "").strip()
        if not self.date:
            self.date = self.meta.get("DATE", "").strip()
        if not self.judge:
            self.judge = self.meta.get("JUDGE", "").strip()

    @property
    def trace_id(self) -> str:
        """完検 KIBAN と出検 A/T機番 の共通 ID（受領データで同一値として MERGE）。"""
        return (self.kiban or self.at_serial or "").strip()

    @property
    def board_id(self) -> str:
        tid = self.trace_id
        return f"board:{tid}" if tid else ""

    @property
    def assembly_id(self) -> str:
        tid = self.trace_id
        return f"unit:{tid}" if tid else ""

    @property
    def valve_body_id(self) -> str:
        if self.vb_serial:
            return f"vb:{self.vb_serial}"
        stem = self.key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return f"vb:{stem[:48]}"

    @property
    def test_record_id(self) -> str:
        key = self.kiban or self.at_serial or self.vb_serial or self.key.rsplit("/", 1)[-1]
        return f"test:{self.data_type}:{key}:{self.date or 'unknown'}"

    @property
    def memory_dump_id(self) -> str:
        dump_type = "main_id" if self.data_type == "j5_main_id" else "shukken_id"
        key = self.kiban or self.at_serial or "unknown"
        return f"dump:{dump_type}:{key}:{self.date or 'unknown'}"
