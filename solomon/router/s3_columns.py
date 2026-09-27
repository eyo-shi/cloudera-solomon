"""S3 オブジェクトの列名を Router clarification 用に先読みする。"""

from __future__ import annotations

import base64

from solomon.tools.format import CSVSnifferTool, MagicByteTool, ParquetMetaTool
from solomon.tools._s3_client import s3_client_for_user
from solomon.transport.user_context import UserContext

_PREVIEW_BYTES = 2 * 1024 * 1024


def peek_s3_column_names(
    user_ctx: UserContext, bucket: str, key: str
) -> list[str] | None:
    """ファイル先頭を読み、ヘッダ / 列名一覧を best-effort で返す。"""
    client = s3_client_for_user(user_ctx)
    if isinstance(client, dict):
        return None
    try:
        resp = client.get_object(
            Bucket=bucket,
            Key=key,
            Range=f"bytes=0-{_PREVIEW_BYTES - 1}",
        )
        head_bytes: bytes = resp["Body"].read()
    except Exception:  # noqa: BLE001
        return None

    magic = MagicByteTool().run(
        user_ctx=None,
        content_b64=base64.b64encode(head_bytes).decode("ascii"),
        filename_hint=key.rsplit("/", 1)[-1],
    )
    if magic.get("status") != "ok":
        return None

    fmt = magic.get("format")
    if fmt in ("csv", "tsv"):
        sniff = CSVSnifferTool().run(
            user_ctx=None,
            content_b64=base64.b64encode(head_bytes).decode("ascii"),
        )
        if sniff.get("status") != "ok":
            return None
        if sniff.get("has_header") and sniff.get("preview_rows"):
            return [str(v) for v in sniff["preview_rows"][0]]
        return None

    if fmt in ("xlsx", "xls"):
        from solomon.tools.excel import ExcelHeaderDetectTool

        result = ExcelHeaderDetectTool().run(
            user_ctx=user_ctx, bucket=bucket, key=key
        )
        if result.get("status") != "ok":
            return None
        for sheet in result.get("sheets", []):
            columns = sheet.get("columns") or []
            if columns:
                return [str(c) for c in columns]
        return None

    if fmt == "parquet":
        meta = ParquetMetaTool().run(user_ctx=user_ctx, bucket=bucket, key=key)
        if meta.get("status") != "ok":
            return None
        names = [str(c.get("name", "")) for c in meta.get("columns", [])]
        return [n for n in names if n] or None

    return None
