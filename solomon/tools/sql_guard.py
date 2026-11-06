"""Text2SQL / sql_query / /api/query 向けの読み取り専用 SQL 検証。

禁止語の列挙ではなく、許す文の種類を決め打ちする (許可リスト)。
禁止リストは先頭コメント (``/* x */ DROP ...``) や ``EXPLAIN ANALYZE INSERT``、
``SET SESSION`` / ``CALL`` などをすり抜けるため。
"""

from __future__ import annotations

import re

_MUTATION = re.compile(
    r"^\s*(CREATE|DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_READONLY_START = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
# 画面の SQL タブ / trino_query はメタデータ参照も許す
_STATEMENT_START = re.compile(r"^(SELECT|WITH|VALUES|TABLE|SHOW|DESCRIBE|DESC)\b", re.IGNORECASE)
# EXPLAIN [ANALYZE] [VERBOSE] [(...)] <statement> — 中身の文も読み取り専用であること
_EXPLAIN = re.compile(
    r"^EXPLAIN\b\s*(ANALYZE\b\s*)?(VERBOSE\b\s*)?(\([^)]*\)\s*)?",
    re.IGNORECASE,
)
_LEADING_COMMENT = re.compile(r"^\s*(--[^\n]*(\n|$)|/\*.*?\*/)", re.DOTALL)


def strip_leading_comments(sql: str) -> str:
    text = sql or ""
    while True:
        m = _LEADING_COMMENT.match(text)
        if not m:
            return text.strip()
        text = text[m.end():]


def _single_statement(sql: str) -> bool:
    return len([p for p in sql.split(";") if p.strip()]) <= 1


def validate_readonly_sql(sql: str) -> str | None:
    """エージェント / Text2SQL 用: SELECT か WITH の 1 文だけ。"""
    stripped = strip_leading_comments(sql)
    if not stripped:
        return "SQL is empty."
    if not _READONLY_START.match(stripped):
        return "Only read-only SQL starting with SELECT or WITH is allowed."
    if not _single_statement(stripped):
        return "Multiple SQL statements are not allowed."
    if _MUTATION.match(stripped):
        return "Mutating SQL is not allowed."
    return None


def validate_readonly_statement(sql: str) -> str | None:
    """SQL タブ / trino_query 用: SELECT・WITH・VALUES・TABLE・SHOW・DESCRIBE と
    それらの EXPLAIN の 1 文だけ。"""
    stripped = strip_leading_comments(sql)
    if not stripped:
        return "SQL is empty."
    if not _single_statement(stripped):
        return "Multiple SQL statements are not allowed."
    body = stripped
    m = _EXPLAIN.match(body)
    if m:
        body = strip_leading_comments(body[m.end():])
    if not _STATEMENT_START.match(body):
        return (
            "Only read-only statements are allowed "
            "(SELECT / WITH / VALUES / TABLE / SHOW / DESCRIBE / EXPLAIN)."
        )
    return None


__all__ = ["strip_leading_comments", "validate_readonly_sql", "validate_readonly_statement"]
