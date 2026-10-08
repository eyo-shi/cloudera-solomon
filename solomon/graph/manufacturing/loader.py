"""製造トレーサビリティグラフを Neo4j に MERGE する。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from neo4j import GraphDatabase

from solomon.graph.manufacturing.models import (
    PRODUCT_PROGRAM_ID,
    PRODUCT_PROGRAM_NAME,
    ManufacturingGraphPayload,
)
from solomon.graph.neo4j_connect import format_neo4j_connection_help, iter_neo4j_connection_uris

BATCH_SIZE = 100


class ManufacturingGraphLoader:
    """J5 受領データ 4 種向け Neo4j ローダ。"""

    def __init__(self, uri: str, username: str, password: str) -> None:
        self._configured_uri = uri
        self._uri = uri
        self._username = username
        self._password = password
        self._driver = None

    def _connect(self, uri: str):
        return GraphDatabase.driver(uri, auth=(self._username, self._password))

    def verify_connectivity(self) -> None:
        errors: list[str] = []
        candidates = iter_neo4j_connection_uris(self._configured_uri)
        if not candidates:
            raise ValueError(format_neo4j_connection_help(self._configured_uri, errors))
        for candidate in candidates:
            driver = self._connect(candidate)
            try:
                driver.verify_connectivity()
            except Exception as exc:
                driver.close()
                errors.append(f"  {candidate}: {exc}")
                continue
            if self._driver is not None:
                self._driver.close()
            self._uri = candidate
            self._driver = driver
            return
        raise ValueError(format_neo4j_connection_help(self._configured_uri, errors))

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

    def ingest(self, payload: ManufacturingGraphPayload) -> dict[str, int]:
        self.verify_connectivity()
        assert self._driver is not None
        ingested_at = datetime.now(timezone.utc).isoformat()
        with self._driver.session() as session:
            session.execute_write(self._ensure_constraints)
            session.execute_write(self._merge_common, payload, ingested_at)
            if payload.data_type == "vb_test":
                counts = session.execute_write(self._merge_vb_test, payload, ingested_at)
            elif payload.data_type == "j5_main_id":
                counts = session.execute_write(self._merge_main_id, payload, ingested_at)
            elif payload.data_type == "j5_kanken":
                counts = session.execute_write(self._merge_kanken, payload, ingested_at)
            else:
                counts = session.execute_write(self._merge_shukken_id, payload, ingested_at)
        return counts

    @staticmethod
    def _ensure_constraints(tx) -> None:
        specs = (
            ("ProductProgram", "id"),
            ("ValveBody", "id"),
            ("Board", "id"),
            ("AssemblyUnit", "id"),
            ("TestRecord", "id"),
            ("MemoryDump", "id"),
            ("DecodedField", "id"),
            ("Measurement", "id"),
            ("SourceFile", "id"),
        )
        for label, prop in specs:
            tx.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )

    @staticmethod
    def _merge_common(tx, payload: ManufacturingGraphPayload, ingested_at: str) -> None:
        tx.run(
            """
            MERGE (p:ProductProgram {id: $program_id})
            SET p.name = $program_name,
                p.updated_at = $ingested_at
            """,
            program_id=PRODUCT_PROGRAM_ID,
            program_name=PRODUCT_PROGRAM_NAME,
            ingested_at=ingested_at,
        )
        tx.run(
            """
            MERGE (f:SourceFile {id: $source_id})
            SET f.bucket = $bucket,
                f.key = $key,
                f.data_type = $data_type,
                f.ingested_at = $ingested_at
            """,
            source_id=payload.source_id,
            bucket=payload.bucket,
            key=payload.key,
            data_type=payload.data_type,
            ingested_at=ingested_at,
        )

    @staticmethod
    def _merge_vb_test(tx, payload: ManufacturingGraphPayload, ingested_at: str) -> dict[str, int]:
        vb_id = payload.valve_body_id
        tx.run(
            """
            MERGE (vb:ValveBody {id: $vb_id})
            SET vb.serial = $serial,
                vb.source_key = $key,
                vb.updated_at = $ingested_at
            WITH vb
            MATCH (p:ProductProgram {id: $program_id})
            MERGE (p)-[:COVERS]->(vb)
            """,
            vb_id=vb_id,
            serial=payload.vb_serial,
            key=payload.key,
            ingested_at=ingested_at,
            program_id=PRODUCT_PROGRAM_ID,
        )
        tx.run(
            """
            MERGE (t:TestRecord {id: $test_id})
            SET t.data_type = 'vb_test',
                t.date = $date,
                t.judge = $judge,
                t.updated_at = $ingested_at
            WITH t
            MATCH (vb:ValveBody {id: $vb_id})
            MERGE (vb)-[:TESTED_BY]->(t)
            WITH t
            MATCH (f:SourceFile {id: $source_id})
            MERGE (t)-[:SOURCED_FROM]->(f)
            """,
            test_id=payload.test_record_id,
            date=payload.date,
            judge=payload.judge,
            ingested_at=ingested_at,
            vb_id=vb_id,
            source_id=payload.source_id,
        )
        if payload.assembly_id:
            tx.run(
                """
                MERGE (u:AssemblyUnit {id: $unit_id})
                SET u.updated_at = $ingested_at
                WITH u
                MATCH (vb:ValveBody {id: $vb_id})
                MERGE (vb)-[:USED_IN]->(u)
                WITH u
                MATCH (p:ProductProgram {id: $program_id})
                MERGE (p)-[:COVERS]->(u)
                """,
                unit_id=payload.assembly_id,
                vb_id=vb_id,
                ingested_at=ingested_at,
                program_id=PRODUCT_PROGRAM_ID,
            )
        return {
            "product_program_nodes": 1,
            "valve_body_nodes": 1,
            "test_record_nodes": 1,
            "source_file_nodes": 1,
            "relationships": 4,
        }

    @staticmethod
    def _merge_main_id(tx, payload: ManufacturingGraphPayload, ingested_at: str) -> dict[str, int]:
        if not payload.kiban:
            raise ValueError("j5_main_id requires KIBAN in file header")
        board_id = payload.board_id
        unit_id = payload.assembly_id
        tx.run(
            """
            MERGE (b:Board {id: $board_id})
            SET b.kiban = $kiban,
                b.trace_id = $trace_id,
                b.hinban = $hinban,
                b.updated_at = $ingested_at
            WITH b
            MATCH (p:ProductProgram {id: $program_id})
            MERGE (p)-[:COVERS]->(b)
            """,
            board_id=board_id,
            kiban=payload.kiban,
            trace_id=payload.trace_id,
            hinban=payload.hinban,
            ingested_at=ingested_at,
            program_id=PRODUCT_PROGRAM_ID,
        )
        if unit_id:
            tx.run(
                """
                MERGE (u:AssemblyUnit {id: $unit_id})
                ON CREATE SET u.kiban = $kiban, u.trace_id = $trace_id
                SET u.updated_at = $ingested_at
                WITH u
                MATCH (b:Board {id: $board_id})
                MERGE (b)-[:INSTALLED_IN]->(u)
                MERGE (b)-[:SAME_TRACE_ID]->(u)
                WITH u
                MATCH (p:ProductProgram {id: $program_id})
                MERGE (p)-[:COVERS]->(u)
                """,
                unit_id=unit_id,
                board_id=board_id,
                kiban=payload.kiban,
                trace_id=payload.trace_id,
                ingested_at=ingested_at,
                program_id=PRODUCT_PROGRAM_ID,
            )
        tx.run(
            """
            MERGE (d:MemoryDump {id: $dump_id})
            SET d.dump_type = 'main_id',
                d.kiban = $kiban,
                d.trace_id = $trace_id,
                d.date = $date,
                d.field_count = $field_count,
                d.updated_at = $ingested_at
            WITH d
            MATCH (b:Board {id: $board_id})
            MERGE (b)-[:HAS_DUMP]->(d)
            WITH d
            MATCH (f:SourceFile {id: $source_id})
            MERGE (d)-[:SOURCED_FROM]->(f)
            """,
            dump_id=payload.memory_dump_id,
            kiban=payload.kiban,
            trace_id=payload.trace_id,
            date=payload.date,
            field_count=len(payload.dump_fields),
            board_id=board_id,
            source_id=payload.source_id,
            ingested_at=ingested_at,
        )
        field_counts = ManufacturingGraphLoader._merge_dump_fields(
            tx, payload, ingested_at
        )
        rel_count = 4 + (3 if unit_id else 0) + field_counts["relationships"]
        return {
            "board_nodes": 1,
            "assembly_unit_nodes": 1 if unit_id else 0,
            "memory_dump_nodes": 1,
            "decoded_field_nodes": field_counts["decoded_field_nodes"],
            "source_file_nodes": 1,
            "relationships": rel_count,
        }

    @staticmethod
    def _merge_dump_fields(
        tx, payload: ManufacturingGraphPayload, ingested_at: str
    ) -> dict[str, int]:
        if not payload.dump_fields:
            return {"decoded_field_nodes": 0, "relationships": 0}

        rows = [
            {
                "id": field.id,
                "address_hex": field.address_hex,
                "address_end_hex": field.address_end_hex,
                "label": field.label,
                "raw_hex": field.raw_hex,
                "value": field.value,
                "value_type": field.value_type,
                "timing": field.timing,
                "process_name": field.process_name,
                "trace_id": payload.trace_id,
            }
            for field in payload.dump_fields
        ]
        for index in range(0, len(rows), BATCH_SIZE):
            chunk = rows[index : index + BATCH_SIZE]
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (f:DecodedField {id: row.id})
                SET f.address_hex = row.address_hex,
                    f.address_end_hex = row.address_end_hex,
                    f.label = row.label,
                    f.raw_hex = row.raw_hex,
                    f.value = row.value,
                    f.value_type = row.value_type,
                    f.timing = row.timing,
                    f.process_name = row.process_name,
                    f.trace_id = row.trace_id,
                    f.updated_at = $ingested_at
                WITH f, row
                MATCH (d:MemoryDump {id: $dump_id})
                MERGE (d)-[:HAS_FIELD]->(f)
                """,
                rows=chunk,
                dump_id=payload.memory_dump_id,
                ingested_at=ingested_at,
            )
        return {
            "decoded_field_nodes": len(rows),
            "relationships": len(rows),
        }

    @staticmethod
    def _merge_kanken(tx, payload: ManufacturingGraphPayload, ingested_at: str) -> dict[str, int]:
        if not payload.kiban:
            raise ValueError("j5_kanken requires KIBAN in file header")
        board_id = payload.board_id
        unit_id = payload.assembly_id
        tx.run(
            """
            MERGE (b:Board {id: $board_id})
            SET b.kiban = $kiban,
                b.hinban = $hinban,
                b.updated_at = $ingested_at
            WITH b
            MATCH (p:ProductProgram {id: $program_id})
            MERGE (p)-[:COVERS]->(b)
            """,
            board_id=board_id,
            kiban=payload.kiban,
            hinban=payload.hinban,
            ingested_at=ingested_at,
            program_id=PRODUCT_PROGRAM_ID,
        )
        tx.run(
            """
            MERGE (u:AssemblyUnit {id: $unit_id})
            SET u.trace_id = $trace_id,
                u.kiban = $kiban,
                u.at_serial = $kiban,
                u.hinban = $hinban,
                u.updated_at = $ingested_at
            WITH u
            MATCH (p:ProductProgram {id: $program_id})
            MERGE (p)-[:COVERS]->(u)
            WITH u
            MATCH (b:Board {id: $board_id})
            MERGE (b)-[:INSTALLED_IN]->(u)
            MERGE (b)-[:SAME_TRACE_ID]->(u)
            """,
            unit_id=unit_id,
            trace_id=payload.trace_id,
            kiban=payload.kiban,
            hinban=payload.hinban,
            board_id=board_id,
            ingested_at=ingested_at,
            program_id=PRODUCT_PROGRAM_ID,
        )
        tx.run(
            """
            MERGE (t:TestRecord {id: $test_id})
            SET t.data_type = 'j5_kanken',
                t.kiban = $kiban,
                t.date = $date,
                t.judge = $judge,
                t.row_count = $row_count,
                t.updated_at = $ingested_at
            WITH t
            MATCH (b:Board {id: $board_id})
            MERGE (b)-[:INSPECTED_BY]->(t)
            WITH t
            MATCH (u:AssemblyUnit {id: $unit_id})
            MERGE (u)-[:PERFORMED]->(t)
            WITH t
            MATCH (f:SourceFile {id: $source_id})
            MERGE (t)-[:SOURCED_FROM]->(f)
            """,
            test_id=payload.test_record_id,
            kiban=payload.kiban,
            date=payload.date,
            judge=payload.judge,
            row_count=payload.row_count,
            board_id=board_id,
            unit_id=unit_id,
            source_id=payload.source_id,
            ingested_at=ingested_at,
        )
        meas_rows = [
            {
                "id": f"{payload.test_record_id}:{m.id}",
                "symbol_name": m.symbol_name,
                "step_name": m.step_name,
                "unit": m.unit,
                "spec_lower": m.spec_lower,
                "spec_upper": m.spec_upper,
                "first_value": m.first_value,
                "j_reinspect": m.j_reinspect,
                "j": m.j,
            }
            for m in payload.measurements
        ]
        for index in range(0, len(meas_rows), BATCH_SIZE):
            chunk = meas_rows[index : index + BATCH_SIZE]
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (m:Measurement {id: row.id})
                SET m.symbol_name = row.symbol_name,
                    m.step_name = row.step_name,
                    m.unit = row.unit,
                    m.spec_lower = row.spec_lower,
                    m.spec_upper = row.spec_upper,
                    m.first_value = row.first_value,
                    m.j_reinspect = row.j_reinspect,
                    m.j = row.j,
                    m.kiban = $kiban
                WITH m, row
                MATCH (t:TestRecord {id: $test_id})
                MERGE (m)-[:PART_OF]->(t)
                """,
                rows=chunk,
                kiban=payload.kiban,
                test_id=payload.test_record_id,
            )
        rel_count = 6 + len(payload.measurements)
        return {
            "board_nodes": 1,
            "assembly_unit_nodes": 1,
            "test_record_nodes": 1,
            "measurement_nodes": len(payload.measurements),
            "source_file_nodes": 1,
            "relationships": rel_count,
        }

    @staticmethod
    def _merge_shukken_id(tx, payload: ManufacturingGraphPayload, ingested_at: str) -> dict[str, int]:
        if not payload.at_serial and not payload.kiban:
            raise ValueError("j5_shukken_id requires AT serial or KIBAN")
        unit_id = payload.assembly_id
        board_id = payload.board_id
        tx.run(
            """
            MERGE (u:AssemblyUnit {id: $unit_id})
            SET u.trace_id = $trace_id,
                u.at_serial = $at_serial,
                u.customer_part_no = $customer_part_no,
                u.kiban = $kiban,
                u.updated_at = $ingested_at
            WITH u
            MATCH (p:ProductProgram {id: $program_id})
            MERGE (p)-[:COVERS]->(u)
            """,
            unit_id=unit_id,
            trace_id=payload.trace_id,
            at_serial=payload.at_serial,
            customer_part_no=payload.customer_part_no,
            kiban=payload.kiban,
            ingested_at=ingested_at,
            program_id=PRODUCT_PROGRAM_ID,
        )
        if payload.trace_id:
            tx.run(
                """
                MERGE (b:Board {id: $board_id})
                SET b.kiban = $kiban,
                    b.trace_id = $trace_id,
                    b.updated_at = $ingested_at
                WITH b
                MATCH (u:AssemblyUnit {id: $unit_id})
                MERGE (b)-[:INSTALLED_IN]->(u)
                MERGE (b)-[:SAME_TRACE_ID]->(u)
                WITH b
                MATCH (p:ProductProgram {id: $program_id})
                MERGE (p)-[:COVERS]->(b)
                """,
                board_id=board_id,
                kiban=payload.kiban,
                trace_id=payload.trace_id,
                unit_id=unit_id,
                ingested_at=ingested_at,
                program_id=PRODUCT_PROGRAM_ID,
            )
        tx.run(
            """
            MERGE (d:MemoryDump {id: $dump_id})
            SET d.dump_type = 'shukken_id',
                d.at_serial = $at_serial,
                d.customer_part_no = $customer_part_no,
                d.kiban = $kiban,
                d.date = $date,
                d.field_count = $field_count,
                d.updated_at = $ingested_at
            WITH d
            MATCH (u:AssemblyUnit {id: $unit_id})
            MERGE (u)-[:HAS_DUMP]->(d)
            WITH d
            MATCH (f:SourceFile {id: $source_id})
            MERGE (d)-[:SOURCED_FROM]->(f)
            """,
            dump_id=payload.memory_dump_id,
            at_serial=payload.at_serial,
            customer_part_no=payload.customer_part_no,
            kiban=payload.kiban,
            date=payload.date,
            field_count=len(payload.dump_fields),
            unit_id=unit_id,
            source_id=payload.source_id,
            ingested_at=ingested_at,
        )
        field_counts = ManufacturingGraphLoader._merge_dump_fields(
            tx, payload, ingested_at
        )
        rel_count = 4 + (4 if payload.trace_id else 0) + field_counts["relationships"]
        return {
            "assembly_unit_nodes": 1,
            "memory_dump_nodes": 1,
            "decoded_field_nodes": field_counts["decoded_field_nodes"],
            "board_nodes": 1 if payload.trace_id else 0,
            "source_file_nodes": 1,
            "relationships": rel_count,
        }
