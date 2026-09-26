"""共通 HTTP / 認証 / ロギング層。

Knox JWT / IDBroker STS 資格情報の伝搬をここで受け持ち、
Tool は user_context を経由してエンドユーザー権限で外部システムを叩く。

エクスポート:

    UserContext, get_user_context, set_user_context
    build_user_context_from_headers, bearer_header
    configure_logging, get_logger
    GandalfHttpClient
    ErrorCode, ToolErrorResult, ok, err
    BaseGandalfTool
"""
from __future__ import annotations

from gandalf.transport.auth import bearer_header, build_user_context_from_headers, extract_jwt
from gandalf.transport.errors import ErrorCode, ToolErrorResult, err, ok
from gandalf.transport.http import GandalfHttpClient
from gandalf.transport.logging import configure_logging, get_logger
from gandalf.transport.tool_base import BaseGandalfTool
from gandalf.transport.user_context import (
    AwsCredentials,
    UserContext,
    get_user_context,
    get_user_context_optional,
    reset_user_context,
    set_user_context,
)

__all__ = [
    "AwsCredentials",
    "BaseGandalfTool",
    "ErrorCode",
    "GandalfHttpClient",
    "ToolErrorResult",
    "UserContext",
    "bearer_header",
    "build_user_context_from_headers",
    "configure_logging",
    "err",
    "extract_jwt",
    "get_logger",
    "get_user_context",
    "get_user_context_optional",
    "ok",
    "reset_user_context",
    "set_user_context",
]
