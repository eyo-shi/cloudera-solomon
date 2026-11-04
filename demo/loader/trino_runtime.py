"""Trino execute / query callbacks for demo loader."""

from __future__ import annotations

import getpass
import os
from typing import Any, Callable

from solomon.tools._trino_client import trino_connection_for_user
from solomon.transport.user_context import UserContext


def loader_user_context() -> UserContext:
    """CLI 実行用の UserContext。

    認証は ``TRINO_USER`` / ``TRINO_PASSWORD`` (Basic) があればそれを使い、無ければ
    workload の ``/tmp/jwt`` (``SOLOMON_CML_JWT_PATH``) を JWT として使う。
    """
    from solomon.transport.auth import _decode_jwt_payload_unverified, load_workload_jwt_token

    jwt = load_workload_jwt_token()
    user_name = ""
    if jwt:
        claims = _decode_jwt_payload_unverified(jwt)
        for key in ("preferred_username", "sub", "user"):
            value = claims.get(key)
            if isinstance(value, str) and value:
                user_name = value
                break
    if not user_name:
        user_name = (os.environ.get("HADOOP_USER_NAME") or "").strip()
    if not user_name:
        try:
            user_name = getpass.getuser()
        except Exception:  # noqa: BLE001
            user_name = "solomon"
    return UserContext(user_name=user_name, knox_jwt=jwt)


def make_trino_callbacks(
    user_ctx: UserContext | None = None,
) -> tuple[Callable[[str], None], Callable[[str], Any]]:
    """Return ``(execute_fn, query_fn)`` for :mod:`demo.loader.iceberg_load`."""
    ctx = user_ctx or loader_user_context()
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
        # trino の Cursor.execute は最初の応答で戻り、close() は実行中のクエリを
        # cancel する。DDL / INSERT も結果を読み切って完了を待つ
        cur = conn.cursor()
        try:
            cur.execute(sql)
            cur.fetchall()
        finally:
            cur.close()

    return execute_fn, query_fn


__all__ = ["loader_user_context", "make_trino_callbacks"]
