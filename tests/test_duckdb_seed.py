"""DuckDB demo seed for internal warehouse."""

from __future__ import annotations

import duckdb

from solomon.trino.duckdb_seed import seed_duckdb_database


def test_seed_creates_demo_tables(tmp_path) -> None:
    db_path = tmp_path / "solomon.duckdb"
    assert seed_duckdb_database(db_path) is True
    con = duckdb.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'demo' ORDER BY table_name"
        ).fetchall()
        assert [r[0] for r in rows] == ["customers", "orders"]
        count = con.execute("SELECT COUNT(*) FROM demo.orders").fetchone()
        assert count is not None and count[0] == 4
    finally:
        con.close()


def test_seed_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "solomon.duckdb"
    assert seed_duckdb_database(db_path) is True
    assert seed_duckdb_database(db_path) is False
