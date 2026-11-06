"""trino Python client を UserContext から組み立てるヘルパ。

どの方式でも、Ranger がログインユーザーの権限で判定するようにする。

* JWT: エンドユーザーの Knox JWT を Bearer として渡す。Trino は JWT の ``sub`` で
  ユーザーを識別する。
* Basic + 成り代わり (CML Application の既定): ``TRINO_USER`` で認証し、
  ``X-Trino-User`` にログインユーザー (CML の ``Remote-User``) を載せる。Ranger の
  cm_trino で ``TRINO_USER`` に Trino User リソースの ``impersonate`` が必要。
* Basic のみ (``TRINO_IMPERSONATION=off``): 全員 ``TRINO_USER`` の権限になる。

接続先ホスト / port / SSL 検証は :mod:`solomon.transport.config` の
:func:`get_trino_config`（external 時は ``TRINO_URL`` / ``TRINO_HOST`` 等の env）から取得する。
"""
from __future__ import annotations

from typing import Any, Union

from solomon.transport.config import get_trino_config
from solomon.transport.errors import ErrorCode, err
from solomon.transport.user_context import UserContext

try:  # trino は本番依存
    import trino  # type: ignore
    from trino.auth import BasicAuthentication, JWTAuthentication  # type: ignore
    from trino.exceptions import TrinoQueryError, TrinoUserError  # type: ignore
except ImportError:  # pragma: no cover
    trino = None  # type: ignore[assignment]

    class TrinoQueryError(Exception):  # type: ignore[no-redef]
        pass

    class TrinoUserError(TrinoQueryError):  # type: ignore[no-redef]
        pass


def _use_trino_basic_auth(cfg: Any) -> bool:
    mode = (cfg.auth_mode or "auto").strip().lower()
    if mode == "basic":
        return True
    if mode == "jwt":
        return False
    return bool(cfg.password)


def _use_trino_impersonation(cfg: Any) -> bool:
    """Basic 認証のサービスアカウントで、ログインユーザーに成り代わるか。"""
    mode = (getattr(cfg, "impersonation", None) or "auto").strip().lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    from solomon.transport.auth import _is_cml_application_mode

    return _is_cml_application_mode()


def _end_user_name(user_ctx: Any) -> str | None:
    name = (getattr(user_ctx, "user_name", None) or "").strip()
    return name if name and name != "anonymous" else None


def trino_connection_for_user(
    user_ctx: UserContext,
    catalog: Union[str, None] = None,
    schema: Union[str, None] = None,
) -> Union[Any, dict[str, Any]]:
    """ユーザー権限で trino connection を返す。失敗時は err() dict。

    :param catalog: 明示指定があれば config の catalog を上書きする
    :param schema: 同上
    """
    if trino is None:
        return err(ErrorCode.TRINO_QUERY_FAILED, "trino client is not installed")

    cfg = get_trino_config()
    if cfg is None:
        from solomon.trino.mode import is_internal_trino_mode

        if is_internal_trino_mode():
            return err(
                ErrorCode.TRINO_NOT_CONFIGURED,
                "Internal Trino warehouse is not ready. Wait for warehouse-launcher "
                "status=running, then restart Solomon or refresh the Tables tab.",
            )
        return err(
            ErrorCode.TRINO_NOT_CONFIGURED,
            "Trino connection is not configured. Set TRINO_MODE=external and "
            "TRINO_URL (or TRINO_HOST) plus auth env after deploy.",
        )

    basic_auth = not cfg.internal and _use_trino_basic_auth(cfg)
    # Basic 認証の主体 (サービスアカウント)。成り代わり時は user_name と異なる
    basic_principal: str | None = None

    if cfg.internal:
        user_name = user_ctx.user_name or "solomon"
    elif basic_auth:
        if not cfg.password:
            return err(
                ErrorCode.TRINO_NOT_CONFIGURED,
                "Trino Basic auth is enabled but TRINO_PASSWORD (or Connection "
                "password) is not set.",
            )
        if _use_trino_impersonation(cfg):
            # サービスアカウントで認証し、クエリはログインユーザーとして実行する。
            # ユーザーが分からないときにサービスアカウントの権限で代行しない
            end_user = _end_user_name(user_ctx)
            if not end_user:
                return err(
                    ErrorCode.AUTH_MISSING,
                    "Trino impersonation is on, but the signed-in user is unknown. "
                    "Open Solomon through the CML application URL.",
                )
            if not cfg.service_user:
                return err(
                    ErrorCode.TRINO_NOT_CONFIGURED,
                    "Trino impersonation needs TRINO_USER (the service account).",
                )
            basic_principal = cfg.service_user
            user_name = end_user
        else:
            user_name = cfg.service_user or user_ctx.user_name or "solomon"
            basic_principal = user_name
    elif not user_ctx.knox_jwt:
        return err(ErrorCode.AUTH_MISSING, "Knox JWT is required for Trino access")
    else:
        user_name = user_ctx.user_name

    connect_kwargs: dict[str, Any] = {
        "host": cfg.host,
        "port": cfg.port,
        "http_scheme": cfg.scheme,
        "user": user_name,
        "catalog": catalog or cfg.catalog,
        "schema": schema or cfg.schema,
        "verify": cfg.verify_ssl,
        "request_timeout": 30,
        "http_headers": {
            "X-Solomon-Request-Id": user_ctx.request_id,
        },
    }
    if not cfg.internal:
        if basic_auth:
            connect_kwargs["auth"] = BasicAuthentication(basic_principal, cfg.password)
        else:
            connect_kwargs["auth"] = JWTAuthentication(user_ctx.knox_jwt)

    conn = trino.dbapi.connect(**connect_kwargs)
    return conn


def map_trino_error(e: Exception, sql: str) -> dict[str, Any]:
    """trino の例外を ToolErrorResult に写像する。"""
    msg = str(e)
    lower = msg.lower()
    # 権限系
    if "impersonate" in lower:
        return err(
            ErrorCode.PERM_UNKNOWN,
            f"{msg} — In Ranger (cm_trino), grant 'impersonate' on the Trino User "
            "resource to the TRINO_USER service account, or set TRINO_IMPERSONATION=off.",
            sql_snippet=_snip(sql),
        )
    if "access denied" in lower or "not authorized" in lower:
        if "select" in lower:
            return err(ErrorCode.PERM_SELECT_DENIED, msg, sql_snippet=_snip(sql))
        if "insert" in lower:
            return err(ErrorCode.PERM_INSERT_DENIED, msg, sql_snippet=_snip(sql))
        if "create" in lower:
            return err(ErrorCode.PERM_CREATE_DENIED, msg, sql_snippet=_snip(sql))
        return err(ErrorCode.PERM_UNKNOWN, msg, sql_snippet=_snip(sql))
    upper = sql.strip().upper()
    # DDL 系 (schema not found 等も TRINO_TABLE_NOT_FOUND に誤分類しない)
    if upper.startswith(("CREATE", "DROP", "ALTER")):
        return err(ErrorCode.TRINO_DDL_FAILED, msg, sql_snippet=_snip(sql))
    # 存在しないテーブル (DML / メタ参照)
    if "does not exist" in lower or "table not found" in lower:
        return err(ErrorCode.TRINO_TABLE_NOT_FOUND, msg, sql_snippet=_snip(sql))
    return err(ErrorCode.TRINO_QUERY_FAILED, msg, sql_snippet=_snip(sql))


def _snip(sql: str, limit: int = 300) -> str:
    s = " ".join(sql.split())
    return s if len(s) <= limit else s[:limit] + "..."
