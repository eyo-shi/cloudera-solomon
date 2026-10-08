"""ファイルフォーマット判定 Tool。

拡張子より **マジックバイト** を優先。CSV は ``csv.Sniffer`` +
``charset-normalizer`` で区切り文字とエンコーディングを推定。Parquet は
pyarrow でメタ情報を読む (Excel は :mod:`solomon.tools.excel`)。
"""
from __future__ import annotations

import base64
import csv
import io
from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.logging import get_logger
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext
from solomon.tools._s3_client import map_s3_error, s3_client_for_user
from solomon.tools.kanken import decode_kanken_bytes, is_kanken_text, parse_kanken_bytes
from solomon.tools.vb import is_vb_report_text, parse_vb_bytes

_logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# MagicByteTool
# ------------------------------------------------------------------ #

# (prefix bytes, format label)
# 順序が重要: 具体的なパターンから先に判定
_MAGIC_PATTERNS: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "xlsx"),  # ZIP-based (xlsx/docx/pptx)
    (b"\xd0\xcf\x11\xe0", "xls"),  # OLE2 Compound (legacy Excel/Word)
    (b"PAR1", "parquet"),  # Parquet magic
    (b"ORC\x00", "orc"),
    (b"Obj\x01", "avro"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"%PDF", "pdf"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpeg"),
)

_TEXT_JSON_LEADING = frozenset("{[")
_UTF8_BOM = b"\xef\xbb\xbf"


class MagicByteArgs(BaseModel):
    content_b64: str = Field(
        ...,
        description="判定対象の先頭バイト列 (base64)。S3GetRangeTool の出力を渡す。",
    )
    filename_hint: Optional[str] = Field(
        None,
        description="判定に失敗した場合の補助として使うファイル名 (拡張子)",
    )


class MagicByteTool(BaseSolomonTool):
    """マジックバイトからフォーマットを判定する。"""

    name: str = "magic_byte"
    description: str = (
        "Identify file format from the first few bytes (base64). Returns "
        "one of: xlsx, xls, parquet, orc, avro, gzip, bzip2, zstd, pdf, "
        "png, jpeg, json, csv, tsv, text, or unknown."
    )
    args_schema: type[BaseModel] = MagicByteArgs
    requires_auth: bool = False  # 純関数的な判定なので auth 不要

    def run(
        self,
        user_ctx: Optional[UserContext],
        content_b64: str,
        filename_hint: Optional[str] = None,
        **_: Any,
    ) -> dict[str, Any]:
        try:
            raw = base64.b64decode(content_b64, validate=True)
        except Exception:  # noqa: BLE001
            return err(ErrorCode.FORMAT_CORRUPT, "content_b64 is not valid base64")

        head = raw[:16]
        # 1. マジックバイト完全一致
        for pat, fmt in _MAGIC_PATTERNS:
            if head.startswith(pat):
                return ok({"format": fmt, "confidence": "high", "method": "magic"})

        # 2. UTF-8 BOM 付きテキスト
        if raw.startswith(_UTF8_BOM):
            raw = raw[len(_UTF8_BOM) :]

        # 3. テキスト判定 (最初の 1 KB が printable/whitespace ASCII/UTF-8)
        sample = raw[:2048]
        try:
            text_sample = sample.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text_sample = sample.decode("cp932")  # Shift_JIS 系
            except UnicodeDecodeError:
                return ok(
                    {
                        "format": "unknown",
                        "confidence": "low",
                        "method": "binary_fallback",
                    }
                )
        stripped = text_sample.lstrip()
        if stripped and stripped[0] in _TEXT_JSON_LEADING:
            return ok({"format": "json", "confidence": "medium", "method": "leading_char"})

        # 3-b. J5 完検 (メタ KV 行 + 固定幅測定テーブル)
        if is_kanken_text(stripped):
            return ok(
                {
                    "format": "kanken",
                    "confidence": "high",
                    "method": "kanken_meta_header",
                }
            )

        # 3-c. VB 試験帳票 (CP932 日本語帳票)
        if is_vb_report_text(stripped):
            return ok(
                {
                    "format": "vb",
                    "confidence": "high",
                    "method": "vb_report_title",
                }
            )

        # 4. CSV / TSV 推定 (区切り候補が行内に均一に現れるか)
        first_lines = stripped.splitlines()[:5]
        if first_lines:
            for delim, label in ((",", "csv"), ("\t", "tsv"), (";", "csv")):
                counts = [ln.count(delim) for ln in first_lines]
                if counts[0] >= 1 and all(c == counts[0] for c in counts):
                    return ok(
                        {
                            "format": label,
                            "confidence": "medium",
                            "method": "delimiter_uniformity",
                            "delimiter_hint": delim,
                        }
                    )

        # 5. 拡張子ヒントで救済
        if filename_hint:
            ext = filename_hint.rsplit(".", 1)[-1].lower() if "." in filename_hint else ""
            if ext in {"csv", "tsv", "json", "parquet", "xlsx", "xls"}:
                return ok(
                    {
                        "format": "csv" if ext == "tsv" else ext,
                        "confidence": "low",
                        "method": "extension_fallback",
                    }
                )

        return ok({"format": "text", "confidence": "low", "method": "default_text"})


# ------------------------------------------------------------------ #
# CSVSnifferTool
# ------------------------------------------------------------------ #
class CSVSnifferArgs(BaseModel):
    content_b64: Optional[str] = Field(
        None,
        description="先頭バイト列 (base64)。S3 直読みが使える場合は bucket+key を優先。",
    )
    bucket: Optional[str] = Field(
        None, description="S3 バケット名 (content_b64 の代わりに先頭を直読み)"
    )
    key: Optional[str] = Field(None, description="S3 オブジェクトキー")
    max_sample_bytes: int = Field(65536, ge=1024, le=1_048_576)


def _decode_csv_sample(raw: bytes) -> tuple[str, str] | dict[str, Any]:
    """CSV サンプル bytes を (encoding, text) にデコード。失敗時は err dict。"""
    encoding = "utf-8"
    if raw.startswith(_UTF8_BOM):
        raw = raw[len(_UTF8_BOM) :]
        encoding = "utf-8-sig"
    try:
        return encoding, raw.decode(encoding)
    except UnicodeDecodeError:
        try:
            from charset_normalizer import from_bytes  # type: ignore
        except ImportError:
            return err(
                ErrorCode.FORMAT_ENCODING_UNKNOWN,
                "charset-normalizer is required for non-UTF8 CSV",
            )
        result = from_bytes(raw).best()
        if result is None:
            return err(
                ErrorCode.FORMAT_ENCODING_UNKNOWN,
                "could not detect encoding",
            )
        encoding = result.encoding or "utf-8"
        return encoding, str(result)


def _guess_csv_delimiter(text: str) -> str:
    """csv.Sniffer 失敗時の区切り文字フォールバック。"""
    first_lines = text.splitlines()[:5]
    for delim in (",", "\t", ";", "|"):
        if not first_lines:
            break
        counts = [ln.count(delim) for ln in first_lines]
        if counts[0] >= 1 and all(c == counts[0] for c in counts):
            return delim
    return ","


def _sniff_csv_text(text: str) -> dict[str, Any]:
    """CSV/TSV テキストから encoding/delimiter/header/preview を返す。"""
    sample = text[:8192]
    delimiter = ","
    quotechar = '"'
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
        quotechar = dialect.quotechar
    except csv.Error:
        delimiter = _guess_csv_delimiter(text)

    has_header = False
    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        pass

    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar=quotechar)
    rows = list(reader)[:20]
    return {
        "delimiter": delimiter,
        "quotechar": quotechar,
        "has_header": has_header,
        "preview_rows": rows,
        "preview_row_count": len(rows),
    }


class CSVSnifferTool(BaseSolomonTool):
    """CSV/TSV の encoding + 区切り文字 + ヘッダ有無を推定する。"""

    name: str = "csv_sniff"
    description: str = (
        "Detect encoding, delimiter, quotechar and whether the first row is a "
        "header for a CSV/TSV sample. Prefer bucket+key to read the first "
        "max_sample_bytes from S3 directly (avoids corrupted base64 from LLM). "
        "Alternatively pass content_b64 from s3_get_range."
    )
    args_schema: type[BaseModel] = CSVSnifferArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        content_b64: Optional[str] = None,
        bucket: Optional[str] = None,
        key: Optional[str] = None,
        max_sample_bytes: int = 65536,
        **_: Any,
    ) -> dict[str, Any]:
        raw: bytes
        if bucket and key:
            client = s3_client_for_user(user_ctx)
            if isinstance(client, dict):
                return client
            end = max_sample_bytes - 1
            try:
                resp = client.get_object(
                    Bucket=bucket, Key=key, Range=f"bytes=0-{end}"
                )
                raw = resp["Body"].read()
            except Exception as e:  # noqa: BLE001
                return map_s3_error(e, bucket, key)
        elif content_b64:
            try:
                raw = base64.b64decode(content_b64, validate=True)[:max_sample_bytes]
            except Exception:  # noqa: BLE001
                return err(ErrorCode.FORMAT_CORRUPT, "content_b64 is not valid base64")
        else:
            return err(
                ErrorCode.FORMAT_CORRUPT,
                "provide bucket+key or content_b64",
            )

        decoded = _decode_csv_sample(raw)
        if isinstance(decoded, dict):
            return decoded
        encoding, text = decoded
        sniffed = _sniff_csv_text(text)
        return ok({"encoding": encoding, **sniffed})


# ------------------------------------------------------------------ #
# KankenSniffTool
# ------------------------------------------------------------------ #
class KankenSniffArgs(BaseModel):
    bucket: Optional[str] = None
    key: Optional[str] = None
    content_b64: Optional[str] = None
    max_sample_bytes: int = Field(65536, ge=1024, le=1_048_576)


class KankenSniffTool(BaseSolomonTool):
    """J5 完検テキストの検出・Shift-JIS デコード・メタ/ヘッダー行の特定。"""

    name: str = "kanken_sniff"
    description: str = (
        "Detect J5 kanken (完成検査) text files: decode Shift-JIS/UTF-8, locate "
        "meta key/value header rows and the measurement table header row. "
        "Prefer bucket+key for S3 direct read."
    )
    args_schema: type[BaseModel] = KankenSniffArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        bucket: Optional[str] = None,
        key: Optional[str] = None,
        content_b64: Optional[str] = None,
        max_sample_bytes: int = 65536,
        **_: Any,
    ) -> dict[str, Any]:
        raw: bytes
        if bucket and key:
            client = s3_client_for_user(user_ctx)
            if isinstance(client, dict):
                return client
            end = max_sample_bytes - 1
            try:
                resp = client.get_object(
                    Bucket=bucket, Key=key, Range=f"bytes=0-{end}"
                )
                raw = resp["Body"].read()
            except Exception as e:  # noqa: BLE001
                return map_s3_error(e, bucket, key)
        elif content_b64:
            try:
                raw = base64.b64decode(content_b64, validate=True)[:max_sample_bytes]
            except Exception:  # noqa: BLE001
                return err(ErrorCode.FORMAT_CORRUPT, "content_b64 is not valid base64")
        else:
            return err(
                ErrorCode.FORMAT_CORRUPT,
                "provide bucket+key or content_b64",
            )

        try:
            source_encoding, text = decode_kanken_bytes(raw)
        except ValueError as e:
            return err(ErrorCode.FORMAT_ENCODING_UNKNOWN, str(e))

        if not is_kanken_text(text):
            return ok(
                {
                    "format": "text",
                    "supported": False,
                    "reason": "file does not match kanken meta/header pattern",
                }
            )

        parsed = parse_kanken_bytes(raw)
        return ok(
            {
                "format": "kanken",
                "supported": True,
                "encoding": "utf-8",
                "source_encoding": source_encoding,
                "header_row": parsed.get("header_row"),
                "meta_kv": parsed.get("meta_kv") or {},
                "row_count_hint": parsed.get("row_count", 0),
                "columns": parsed.get("columns") or [],
                "preview_rows": (parsed.get("rows") or [])[:5],
            }
        )


# ------------------------------------------------------------------ #
# ParquetMetaTool
# ------------------------------------------------------------------ #
class ParquetMetaArgs(BaseModel):
    bucket: str
    key: str


class ParquetMetaTool(BaseSolomonTool):
    """Parquet ファイルのスキーマと行数を pyarrow で読む。

    S3 から本文をストリーミングで取得し、フッタのメタデータだけ読む。
    """

    name: str = "parquet_meta"
    description: str = (
        "Read the Parquet footer metadata (schema, num_rows, num_row_groups) "
        "for an S3-hosted Parquet file. Streaming; no full download."
    )
    args_schema: type[BaseModel] = ParquetMetaArgs

    def run(
        self,
        user_ctx: Optional[UserContext],
        bucket: str,
        key: str,
        **_: Any,
    ) -> dict[str, Any]:
        try:
            import pyarrow.parquet as pq  # type: ignore
        except ImportError:
            return err(ErrorCode.FORMAT_UNSUPPORTED, "pyarrow is not installed")
        client = s3_client_for_user(user_ctx)
        if isinstance(client, dict):
            return client
        # 全量読むと大きいので BytesIO に落とし込む (pyarrow のリモート FS は環境依存)
        try:
            resp = client.get_object(Bucket=bucket, Key=key)
            body: bytes = resp["Body"].read()
        except Exception as e:  # noqa: BLE001
            return map_s3_error(e, bucket, key)
        try:
            reader = pq.ParquetFile(io.BytesIO(body))
            schema = reader.schema_arrow
            columns = [
                {"name": f.name, "type": str(f.type), "nullable": f.nullable}
                for f in schema
            ]
            return ok(
                {
                    "num_rows": reader.metadata.num_rows,
                    "num_row_groups": reader.metadata.num_row_groups,
                    "columns": columns,
                }
            )
        except Exception as e:  # noqa: BLE001
            return err(ErrorCode.FORMAT_CORRUPT, f"parquet read failed: {e}")
