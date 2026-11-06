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

from solomon.transport.logging import get_logger
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)

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
# CML Application で信用するユーザー名ヘッダ。CML が認証後に付けるもので、
# それ以外 (X-Forwarded-User 等) はブラウザが自由に付けられるため読まない。
_CML_USER_HEADER = "remote-user"
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


def load_workload_jwt_token() -> Optional[str]:
    """CML workload pod の ``/tmp/jwt`` からデータレイク / IDBroker 用トークンを読む。"""
    return _load_workload_jwt_file()


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
        if not _is_header_safe_token(candidate):
            # Knox からのトークン取得に失敗すると、CML はエラーページ (HTML) を
            # そのまま /tmp/jwt に書くことがある。Bearer に載せると不正ヘッダになる
            _logger.warning(
                "auth.workload_jwt_invalid",
                path=str(path),
                length=len(candidate),
                looks_like_html=candidate.lstrip().startswith("<"),
            )
            return None
        return candidate or None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _is_header_safe_token(token: str) -> bool:
    """Bearer に載せられるトークンか (空白・改行・HTML を含まない)。"""
    return bool(token) and "<" not in token and not any(c.isspace() for c in token)


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

    CML Application では、CML が認証後に付ける ``Remote-User`` だけをユーザー名に
    使う。ユーザー名は Trino の成り代わり (Ranger の判定主体) に使うため、
    ブラウザが付けられるヘッダや署名を検証していない JWT のクレームからは取らない。
    """
    lower = _lowercase_headers(headers)
    jwt_token = extract_jwt(headers, cookies=cookies)
    cml_app = _is_cml_application_mode()

    # ユーザー名: 明示ヘッダ → JWT claim → "anonymous"
    user_name: Optional[str] = None
    user_headers = (_CML_USER_HEADER,) if cml_app else _USER_HEADER_CANDIDATES
    for h in user_headers:
        if lower.get(h, "").strip():
            user_name = lower[h].strip()
            break
    groups: tuple[str, ...] = ()
    for h in () if cml_app else _GROUPS_HEADER_CANDIDATES:
        if lower.get(h):
            groups = tuple(g.strip() for g in lower[h].split(",") if g.strip())
            break

    if jwt_token and (not user_name or not groups):
        claims = _decode_jwt_payload_unverified(jwt_token)
        if not user_name and not cml_app:
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
    """API 認可: Knox JWT または CML Application の remote-user セッション。

    CML Application では JWT があっても ``Remote-User`` が無ければ通さない
    (JWT は ``/tmp/jwt`` = アプリ作成者のトークンにフォールバックするため)。
    """
    has_user = bool(ctx.user_name) and ctx.user_name != "anonymous"
    if _is_cml_application_mode():
        return has_user
    return bool(ctx.knox_jwt)


def bearer_header(ctx: UserContext) -> dict[str, str]:
    """`Authorization: Bearer <jwt>` を組み立てるユーティリティ。JWT 未設定なら空。"""
    if not ctx.knox_jwt:
        return {}
    return {"Authorization": f"Bearer {ctx.knox_jwt}"}
