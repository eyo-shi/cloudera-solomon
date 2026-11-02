"""Trino execute / query callbacks for demo loader."""

from __future__ import annotations

from typing import Any, Callable

from solomon.tools._trino_client import trino_connection_for_user
from solomon.transport.user_context import UserContext


def make_trino_callbacks(
    user_ctx: UserContext | None = None,
) -> tuple[Callable[[str], None], Callable[[str], Any]]:
    """Return ``(execute_fn, query_fn)`` for :mod:`demo.loader.iceberg_load`."""
    ctx = user_ctx or UserContext()
    conn_or_err = trino_connection_for_user(ctx)
    if isinstance(conn_or_err, dict):
        raise RuntimeError(conn_or_err.get("message") or "Trino connection failed")

    conn = conn_or_err

    def query_fn(sql: str) -> Any:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall()
        finally:
            cur.close()

    def execute_fn(sql: str) -> None:
        cur = conn.cursor()
        try:
            cur.execute(sql)
        finally:
            cur.close()

    return execute_fn, query_fn


__all__ = ["make_trino_callbacks"]
