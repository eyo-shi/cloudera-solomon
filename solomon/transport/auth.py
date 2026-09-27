"""Knox JWT の抽出とデコード。

Cloudera Workbench Application は Knox の背後で動くため、既に Knox が
JWT の署名検証を済ませている。この層では **検証はしない**（Knox を信頼する）
が、`sub` / `preferred_username` などのクレームは取り出す。
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import jwt

from solomon.transport.user_context import UserContext

# Knox が転送してくるヘッダの候補 (デプロイ形態により異なる)
_JWT_HEADER_CANDIDATES = (
    "authorization",  # "Bearer <jwt>"
    "x-knox-jwt",
    "x-forwarded-access-token",
    "x-auth-request-access-token",
)
_USER_HEADER_CANDIDATES = (
    "x-forwarded-user",
    "x-remote-user",
    "remote-user",  # CML Application (BrowserSvcs)
    "cdsw-authenticated-user",
)
# CML Workbench Application: ブラウザ same-origin リクエストは Cookie で JWT を送る
_COOKIE_JWT_NAMES = (
    "_cdswuserstoken",
    "_basusertoken",
    "cdswuserstoken",
    "basusertoken",
)
_GROUPS_HEADER_CANDIDATES = (
    "x-forwarded-groups",
    "x-remote-groups",
)


def _lowercase_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def _decode_jwt_payload_unverified(token: str) -> dict[str, object]:
    """署名検証なしで JWT のペイロードだけ取り出す。

    Knox が既に検証済みという前提。改ざん検知はしないので
    ヘッダ値をトラストする境界は FastAPI 側で明示する。
    """
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except jwt.exceptions.PyJWTError:
        # フォールバック: 3 パート化して base64 decode を試みる
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        try:
            return json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}


def _looks_like_jwt(token: str) -> bool:
    parts = token.split(".")
    return len(parts) >= 3 and all(part.strip() for part in parts)


def _normalize_token(raw: str) -> str:
    text = unquote(raw.strip().strip('"'))
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


def _parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def _is_cml_application_mode() -> bool:
    """Workbench Application として起動されているか。"""
    if os.environ.get("TASK_TYPE") == "START_APPLICATION":
        return True
    raw = (os.environ.get("CDSW_APP_PORT") or "").strip()
    return bool(raw) and raw.isdigit() and int(raw) > 0


def _load_workload_jwt_file() -> Optional[str]:
    """CML workload pod の /tmp/jwt から Bearer トークンを読む (フォールバック)。"""
    path = Path(os.environ.get("SOLOMON_CML_JWT_PATH", "/tmp/jwt"))
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        if text.startswith("{"):
            data = json.loads(text)
            for key in ("access_token", "token", "jwt"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return _normalize_token(val)
        candidate = _normalize_token(text)
        return candidate or None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def extract_jwt_from_cookies(cookies: dict[str, str]) -> Optional[str]:
    """CML Workbench のセッション Cookie から Knox JWT / API token を取り出す。"""
    lowered = {k.lower(): v for k, v in cookies.items()}
    for name in _COOKIE_JWT_NAMES:
        raw = lowered.get(name.lower())
        if not raw:
            continue
        candidate = _normalize_token(raw)
        if _looks_like_jwt(candidate):
            return candidate
        # CML session token は JWT 形式でない opaque bearer のこともある
        if len(candidate) >= 20 and not candidate.isspace():
            return candidate
    return None


def extract_jwt(
    headers: dict[str, str],
    cookies: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """リクエストヘッダ / Cookie から Knox JWT を取り出す。"""
    lower = _lowercase_headers(headers)
    for h in _JWT_HEADER_CANDIDATES:
        raw = lower.get(h)
        if not raw:
            continue
        if h == "authorization":
            if raw.lower().startswith("bearer "):
                return raw[7:].strip() or None
            continue
        candidate = _normalize_token(raw)
        if _looks_like_jwt(candidate):
            return candidate
        return candidate or None
    if cookies:
        found = extract_jwt_from_cookies(cookies)
        if found:
            return found
    cookie_header = lower.get("cookie")
    if cookie_header:
        found = extract_jwt_from_cookies(_parse_cookie_header(cookie_header))
        if found:
            return found
    if _is_cml_application_mode():
        return _load_workload_jwt_file()
    return None


def build_user_context_from_headers(
    headers: dict[str, str],
    session_id: Optional[str] = None,
    cookies: Optional[dict[str, str]] = None,
) -> UserContext:
    """FastAPI 依存性から呼び出す想定のファクトリ。

    Knox JWT が無い場合 (開発モード等) は "anonymous" で構築する。
    プロダクション設定では JWT 必須にする middleware を上に置く。
    """
    lower = _lowercase_headers(headers)
    jwt_token = extract_jwt(headers, cookies=cookies)

    # ユーザー名: 明示ヘッダ → JWT claim → "anonymous"
    user_name: Optional[str] = None
    for h in _USER_HEADER_CANDIDATES:
        if lower.get(h):
            user_name = lower[h].strip()
            break
    groups: tuple[str, ...] = ()
    for h in _GROUPS_HEADER_CANDIDATES:
        if lower.get(h):
            groups = tuple(g.strip() for g in lower[h].split(",") if g.strip())
            break

    if jwt_token and (not user_name or not groups):
        claims = _decode_jwt_payload_unverified(jwt_token)
        if not user_name:
            for claim_key in ("preferred_username", "sub", "user"):
                v = claims.get(claim_key)
                if isinstance(v, str) and v:
                    user_name = v
                    break
        if not groups:
            raw_groups = claims.get("groups") or claims.get("roles") or []
            if isinstance(raw_groups, list):
                groups = tuple(str(g) for g in raw_groups if g)

    return UserContext(
        user_name=user_name or "anonymous",
        groups=groups,
        knox_jwt=jwt_token,
        session_id=session_id,
    )


def is_authenticated_context(ctx: UserContext) -> bool:
    """API 認可: Knox JWT または CML Application の remote-user セッション。"""
    if ctx.knox_jwt:
        return True
    return _is_cml_application_mode() and bool(ctx.user_name) and ctx.user_name != "anonymous"


def bearer_header(ctx: UserContext) -> dict[str, str]:
    """`Authorization: Bearer <jwt>` を組み立てるユーティリティ。JWT 未設定なら空。"""
    if not ctx.knox_jwt:
        return {}
    return {"Authorization": f"Bearer {ctx.knox_jwt}"}
