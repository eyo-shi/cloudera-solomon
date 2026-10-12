"""Knox JWT を IDBroker CAB エンドポイントで AWS STS 短期資格情報と交換する。

Cloudera IDBroker は Knox JWT を受け取り、ユーザー / グループごとに mapping
された IAM ロールで AssumeRole を実施し、短期の (AccessKeyId, SecretAccessKey,
SessionToken, Expiration) を返す。この短期資格情報を UserContext スコープで
使い回すことで **エンドユーザー権限** の S3 アクセスを実現する。

環境変数:
  SOLOMON_IDBROKER_URL - IDBroker のベース URL (例: https://knox.example.com:8443/gateway)
  SOLOMON_KNOXTOKEN_URL - (任意) Knox delegation token API (未設定時は IDBroker + /dt/knoxtoken/api/v1/token)

セキュリティ:
  * fetched credentials は module-level dict にキャッシュされるが、キーは
    ``UserContext.request_id`` (UUID hex 32 桁) なので他リクエストと混同しない
  * expiration まで 60 秒を切ったら再取得
  * 資格情報の値は絶対にログ・LLM プロンプトへ流さない (redact filter 前提)
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Optional, Union

import httpx

from solomon.transport.auth import load_workload_jwt_token
from solomon.transport.errors import ErrorCode, err
from solomon.transport.logging import get_logger
from solomon.transport.user_context import AwsCredentials, UserContext

_logger = get_logger(__name__)

_IDBROKER_TIMEOUT_S = 15.0
_CAB_PATH = "/aws-cab/cab/api/v1/credentials"
_KNOXTOKEN_PATH = "/dt/knoxtoken/api/v1/token"
_REFRESH_MARGIN_S = 60  # 期限まで 60 秒未満なら再取得

# request_id -> AwsCredentials のキャッシュ (module-level)
# 1 リクエスト内で複数の S3 Tool 呼び出しが発生しても IDBroker を叩くのは 1 回
_creds_cache: dict[str, AwsCredentials] = {}


def clear_credentials(request_id: str) -> None:
    """FastAPI middleware がリクエスト終了時に呼ぶ。メモリリークの予防。"""
    _creds_cache.pop(request_id, None)


def _gc_expired(now: float) -> None:
    for rid in list(_creds_cache):
        if _creds_cache[rid].expiration_epoch <= now:
            del _creds_cache[rid]


def _parse_expiration(exp: Any) -> int:
    """IDBroker が返す Expiration を epoch 秒に変換する。

    IDBroker のバージョンにより epoch (int) だったり ISO8601 文字列だったりする。
    """
    if isinstance(exp, (int, float)):
        return int(exp)
    if isinstance(exp, str):
        # "2026-09-19T12:34:56Z" 形式
        return int(datetime.fromisoformat(exp.replace("Z", "+00:00")).timestamp())
    # 不明ならデフォ 30 分
    return int(time.time()) + 1800


def knoxtoken_url() -> str | None:
    """Knox delegation token を発行する URL (CAB が要求する audience 用)。"""
    custom = (os.environ.get("SOLOMON_KNOXTOKEN_URL") or "").strip()
    if custom:
        return custom.rstrip("/")
    idb = (os.environ.get("SOLOMON_IDBROKER_URL") or "").strip()
    if not idb:
        return None
    return f"{idb.rstrip('/')}{_KNOXTOKEN_PATH}"


def _knoxtoken_access_token(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in ("access_token", "token", "accessToken"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _knoxtoken_via_spnego(url: str) -> str | None:
    """Session / notebook 向け: Kerberos SPNEGO で Knox token を取得 (任意依存)。"""
    try:
        import requests
        from requests_kerberos import HTTPKerberosAuth, OPTIONAL
    except ImportError:
        return None
    try:
        resp = requests.get(
            url,
            auth=HTTPKerberosAuth(mutual_authentication=OPTIONAL),
            timeout=_IDBROKER_TIMEOUT_S,
        )
    except Exception:  # noqa: BLE001
        return None
    if resp.status_code >= 400:
        return None
    try:
        return _knoxtoken_access_token(resp.json())
    except ValueError:
        return None


def fetch_knox_delegation_token(user_ctx: UserContext) -> Optional[str]:
    """CML セッション JWT を Knox CAB 向け delegation token に交換する (可能な場合)。"""
    url = knoxtoken_url()
    if not url:
        return None
    try:
        with httpx.Client(timeout=_IDBROKER_TIMEOUT_S) as client:
            for label, raw in (
                ("session", user_ctx.knox_jwt),
                ("workload", load_workload_jwt_token()),
            ):
                if not raw or not raw.strip():
                    continue
                resp = client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {raw.strip()}",
                        "Accept": "application/json",
                    },
                )
                if resp.status_code >= 400:
                    _logger.debug(
                        "knoxtoken.failed",
                        method=label,
                        status=resp.status_code,
                    )
                    continue
                try:
                    tok = _knoxtoken_access_token(resp.json())
                except ValueError:
                    continue
                if tok:
                    _logger.debug("knoxtoken.ok", method=label)
                    return tok
    except httpx.HTTPError as exc:
        _logger.debug("knoxtoken.error", error=str(exc))

    tok = _knoxtoken_via_spnego(url)
    if tok:
        _logger.debug("knoxtoken.ok", method="spnego")
    return tok


def _cab_bearer_candidates(user_ctx: UserContext) -> list[str]:
    """CAB 用 Bearer の試行順（重複除去）。

    aws-cab は **Knox delegation token** (knoxtoken API) を期待することが多く、
    Workbench Cookie JWT や ``/tmp/jwt`` だけでは ``missing required token audience`` になる。
    """
    seen: set[str] = set()
    out: list[str] = []
    delegation = fetch_knox_delegation_token(user_ctx)
    if delegation:
        seen.add(delegation)
        out.append(delegation)
    for raw in (user_ctx.knox_jwt, load_workload_jwt_token()):
        if not raw:
            continue
        tok = raw.strip()
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _credential_fields(data: dict[str, Any]) -> dict[str, Any]:
    nested = data.get("Credentials")
    if isinstance(nested, dict):
        return nested
    return data


def fetch_aws_credentials(user_ctx: UserContext) -> Union[AwsCredentials, dict[str, Any]]:
    """Knox JWT を IDBroker に渡して STS credentials を取得する。

    成功時は :class:`AwsCredentials`、失敗時は ``{"status": "error", ...}`` dict。
    """
    idb_url = os.environ.get("SOLOMON_IDBROKER_URL")
    if not idb_url:
        return err(
            ErrorCode.S3_ASSUMEROLE_FAILED,
            "SOLOMON_IDBROKER_URL is not configured; cannot obtain S3 credentials.",
        )
    bearers = _cab_bearer_candidates(user_ctx)
    if not bearers:
        return err(
            ErrorCode.AUTH_MISSING,
            "Knox JWT is required to exchange for AWS credentials.",
        )

    base = idb_url.rstrip("/")
    endpoints = [f"{base}{_CAB_PATH}"]
    if user_ctx.groups:
        for group in user_ctx.groups:
            g = group.strip()
            if g:
                endpoints.append(f"{base}{_CAB_PATH}/group/{g}")

    resp: httpx.Response | None = None
    try:
        with httpx.Client(timeout=_IDBROKER_TIMEOUT_S) as client:
            for bearer in bearers:
                headers = {
                    "Authorization": f"Bearer {bearer}",
                    "Accept": "application/json",
                }
                for endpoint in endpoints:
                    resp = client.get(endpoint, headers=headers)
                    if resp.status_code < 400:
                        break
                    if resp.status_code not in (400, 401, 403):
                        break
                if resp is not None and resp.status_code < 400:
                    break
    except httpx.TimeoutException:
        _logger.warning("idbroker.timeout", user=user_ctx.user_name)
        return err(ErrorCode.S3_ASSUMEROLE_FAILED, "IDBroker request timed out.")
    except httpx.HTTPError as e:
        _logger.warning("idbroker.error", error=str(e), user=user_ctx.user_name)
        return err(ErrorCode.S3_ASSUMEROLE_FAILED, f"IDBroker call failed: {e}")

    if resp is None:
        return err(ErrorCode.S3_ASSUMEROLE_FAILED, "IDBroker call failed: no response.")

    body_preview = (resp.text or "")[:240]
    if resp.status_code in (401, 403):
        _logger.warning(
            "idbroker.access_denied",
            status=resp.status_code,
            user=user_ctx.user_name,
            body=body_preview,
        )
        return err(
            ErrorCode.S3_ACCESS_DENIED,
            f"IDBroker rejected Knox JWT with HTTP {resp.status_code}.",
            status_code=resp.status_code,
        )
    if resp.status_code >= 400:
        _logger.warning(
            "idbroker.status",
            status=resp.status_code,
            user=user_ctx.user_name,
            body=body_preview,
        )
        return err(
            ErrorCode.S3_ASSUMEROLE_FAILED,
            f"IDBroker returned HTTP {resp.status_code}.",
            status_code=resp.status_code,
        )
    try:
        data = resp.json()
    except ValueError:
        return err(
            ErrorCode.S3_ASSUMEROLE_FAILED,
            "IDBroker returned non-JSON body.",
        )
    try:
        fields = _credential_fields(data)
        creds = AwsCredentials(
            access_key_id=fields["AccessKeyId"],
            secret_access_key=fields["SecretAccessKey"],
            session_token=fields["SessionToken"],
            expiration_epoch=_parse_expiration(fields.get("Expiration")),
        )
    except (KeyError, TypeError) as e:
        return err(
            ErrorCode.S3_ASSUMEROLE_FAILED,
            f"IDBroker response malformed: missing/invalid {e}",
        )
    _logger.info(
        "idbroker.ok",
        user=user_ctx.user_name,
        expires_in_s=creds.expiration_epoch - int(time.time()),
    )
    return creds


def get_or_fetch_credentials(
    user_ctx: UserContext,
) -> Union[AwsCredentials, dict[str, Any]]:
    """キャッシュにあればそれ、なければ IDBroker を叩いて格納する。"""
    now = time.time()
    _gc_expired(now)
    cached = _creds_cache.get(user_ctx.request_id)
    if cached and cached.expiration_epoch - now > _REFRESH_MARGIN_S:
        return cached
    result = fetch_aws_credentials(user_ctx)
    if isinstance(result, AwsCredentials):
        _creds_cache[user_ctx.request_id] = result
    return result
