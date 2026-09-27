"""boto3 S3 client を UserContext から組み立てるヘルパ。

Tool 実装 (:mod:`solomon.tools.s3` など) が薄く共通利用する。

認証 (優先順):

1. ``SOLOMON_IDBROKER_URL`` 未設定時 — CML Data Connection の
   ``get_base_connection()`` (Session と同じ経路) を複数候補名で試行。
2. ``SOLOMON_IDBROKER_URL`` 設定時 — Knox JWT を IDBroker で STS 資格情報に交換。

region / endpoint_url は :mod:`solomon.transport.config` の :func:`get_s3_config`
から取得する (Data Connection 由来 or env fallback)。
"""
from __future__ import annotations

from typing import Any, Union
from urllib.parse import urlparse

from solomon.transport.config import (
    _cml_get_connection,
    cml_data_available,
    get_s3_config,
    idbroker_configured,
    iter_s3_connection_names,
)
from solomon.transport.errors import ErrorCode, err
from solomon.transport.logging import get_logger
from solomon.transport.user_context import UserContext
from solomon.tools._idbroker import get_or_fetch_credentials

_logger = get_logger(__name__)

try:  # boto3 は本番依存。テストではモックする。
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        def __init__(self, response: dict, operation_name: str = "") -> None:
            super().__init__(str(response))
            self.response = response
            self.operation_name = operation_name


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/prefix/key`` を ``(bucket, key)`` に分解する。"""
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3:// URI: {uri}")
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip("/")


def _try_s3_client_from_cml_connections() -> tuple[Any | None, list[str]]:
    """CML Data Connection の boto3 client (Session の get_base_connection 相当)。"""
    tried: list[str] = []
    if not cml_data_available():
        return None, tried

    for name in iter_s3_connection_names():
        tried.append(name)
        conn = _cml_get_connection(name)
        if conn is None:
            continue
        getter = getattr(conn, "get_base_connection", None)
        if not callable(getter):
            _logger.debug(
                "s3.cml_connection_missing_get_base_connection",
                connection_name=name,
            )
            continue
        try:
            client = getter()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "s3.cml_connection_client_failed",
                connection_name=name,
                error=str(exc),
            )
            continue
        if client is None:
            continue
        _logger.info("s3.using_cml_data_connection", connection_name=name)
        return client, tried

    return None, tried


def _cml_s3_unavailable_error(tried: list[str]) -> dict[str, Any]:
    if not cml_data_available():
        return err(
            ErrorCode.S3_ASSUMEROLE_FAILED,
            "cml.data_v1 is not available in this runtime. "
            "Set SOLOMON_S3_CONNECTION_NAME and ensure cml.data_v1 is installed, "
            "or configure SOLOMON_IDBROKER_URL.",
        )
    if tried:
        joined = ", ".join(tried)
        return err(
            ErrorCode.S3_ASSUMEROLE_FAILED,
            "Could not obtain S3 credentials from CML Data Connection "
            f"(tried: {joined}). Set SOLOMON_S3_CONNECTION_NAME=S3 Object Store "
            "or configure SOLOMON_IDBROKER_URL.",
        )
    return err(
        ErrorCode.S3_ASSUMEROLE_FAILED,
        "No S3 Data Connection found. Set SOLOMON_S3_CONNECTION_NAME=S3 Object Store "
        "or configure SOLOMON_IDBROKER_URL.",
    )


def s3_client_for_user(user_ctx: UserContext) -> Union[Any, dict[str, Any]]:
    """ユーザー権限で boto3 S3 client を返す。失敗時は err() dict。"""
    if boto3 is None:
        return err(ErrorCode.S3_ASSUMEROLE_FAILED, "boto3 is not installed")

    cfg = get_s3_config()
    if not idbroker_configured():
        cml_client, tried = _try_s3_client_from_cml_connections()
        if cml_client is not None:
            return cml_client
        return _cml_s3_unavailable_error(tried)

    creds = get_or_fetch_credentials(user_ctx)
    if isinstance(creds, dict):
        return creds

    region = cfg.region if cfg else "us-east-1"
    endpoint_url = cfg.endpoint_url if cfg else None
    kwargs: dict[str, Any] = dict(
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        aws_session_token=creds.session_token,
        region_name=region,
    )
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def map_s3_error(e: Exception, bucket: str, key: str) -> dict[str, Any]:
    """boto3 の例外を ToolErrorResult に写像する。"""
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "NoSuchBucket", "404"):
            return err(ErrorCode.S3_NOT_FOUND, f"S3 not found: s3://{bucket}/{key}")
        if code in ("AccessDenied", "403"):
            return err(
                ErrorCode.S3_ACCESS_DENIED,
                f"S3 access denied: s3://{bucket}/{key}",
            )
        if code in ("InvalidRange", "416"):
            return err(
                ErrorCode.S3_RANGE_FAILED,
                f"Invalid range on s3://{bucket}/{key}",
            )
        return err(
            ErrorCode.S3_ASSUMEROLE_FAILED,
            f"S3 client error {code}: {e}",
        )
    if isinstance(e, BotoCoreError):
        return err(ErrorCode.S3_ASSUMEROLE_FAILED, f"boto3 error: {e}")
    return err(ErrorCode.S3_ASSUMEROLE_FAILED, f"Unexpected S3 error: {e}")
