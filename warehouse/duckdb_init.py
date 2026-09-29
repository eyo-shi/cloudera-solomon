#!/usr/bin/env python3
"""Standalone DuckDB init for the warehouse-launcher init container (no solomon package)."""

from __future__ import annotations

import sys
from pathlib import Path

_DEMO_SCHEMA = "demo"
_MARKER_TABLE = "orders"


def _is_seeded(con) -> bool:  # noqa: ANN001
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        """,
        [_DEMO_SCHEMA, _MARKER_TABLE],
    ).fetchone()
    return bool(row and row[0] > 0)


def seed_duckdb_database(path: str | Path) -> bool:
    import duckdb

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        if _is_seeded(con):
            return False

        con.execute(f"CREATE SCHEMA IF NOT EXISTS {_DEMO_SCHEMA}")
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_DEMO_SCHEMA}.customers (
                customer_id BIGINT PRIMARY KEY,
                name VARCHAR,
                region VARCHAR
            )
            """
        )
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_DEMO_SCHEMA}.orders (
                order_id BIGINT PRIMARY KEY,
                customer_id BIGINT,
                product VARCHAR,
                amount DOUBLE,
                order_date DATE
            )
            """
        )
        con.execute(
            f"""
            INSERT INTO {_DEMO_SCHEMA}.customers (customer_id, name, region)
            SELECT * FROM (VALUES
                (1, 'Acme Corp', 'US-West'),
                (2, 'Globex', 'EU'),
                (3, 'Initech', 'US-East')
            ) AS v(customer_id, name, region)
            WHERE NOT EXISTS (SELECT 1 FROM {_DEMO_SCHEMA}.customers)
            """
        )
        con.execute(
            f"""
            INSERT INTO {_DEMO_SCHEMA}.orders (order_id, customer_id, product, amount, order_date)
            SELECT * FROM (VALUES
                (1001, 1, 'Widget A', 19.99, DATE '2025-01-10'),
                (1002, 1, 'Widget B', 29.50, DATE '2025-01-12'),
                (1003, 2, 'Gadget X', 149.00, DATE '2025-02-01'),
                (1004, 3, 'Service Plan', 9.99, DATE '2025-02-15')
            ) AS v(order_id, customer_id, product, amount, order_date)
            WHERE NOT EXISTS (SELECT 1 FROM {_DEMO_SCHEMA}.orders)
            """
        )
        return True
    finally:
        con.close()


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: duckdb_init.py <path/to/solomon.duckdb>", file=sys.stderr)
        return 2
    seeded = seed_duckdb_database(sys.argv[1])
    print("DuckDB seed applied." if seeded else "DuckDB already seeded; skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
