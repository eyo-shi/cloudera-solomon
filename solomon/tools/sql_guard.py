"""Text2SQL / sql_query 向けの読み取り専用 SQL 検証。"""

from __future__ import annotations

import re

_MUTATION = re.compile(
    r"^\s*(CREATE|DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_READONLY_START = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def validate_readonly_sql(sql: str) -> str | None:
    stripped = (sql or "").strip()
    if not stripped:
        return "SQL is empty."
    if not _READONLY_START.match(stripped):
        return "Only read-only SQL starting with SELECT or WITH is allowed."
    parts = [p.strip() for p in stripped.split(";") if p.strip()]
    if len(parts) > 1:
        return "Multiple SQL statements are not allowed."
    if _MUTATION.match(stripped):
        return "Mutating SQL is not allowed."
    return None


__all__ = ["validate_readonly_sql"]
