/**
 * File Preview タブ: S3 上のオブジェクトを形式別に表示する。
 *
 * 対応形式 (バックエンド `/api/files/preview` に準拠):
 *   csv         -> グリッド
 *   json        -> pretty-print JSON (ツリー化は v2)
 *   jsonl       -> 1 行ずつテーブル化
 *   excel       -> シートタブ + データグリッド
 *   parquet     -> スキーマ + サンプル行数
 *   markdown    -> Markdown ソース / Preview 切替
 *   text/log/yaml -> 行番号付きプレーンテキスト
 *   その他      -> フォーマット + head_bytes を表示
 */
import { Fragment, useEffect, useState } from "react";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { useFilePreview } from "../../../api/files";
import { useTabStore } from "../../../stores/tabStore";
import type { FilePreviewResponse, TabDescriptor } from "../../../types";

type MarkdownViewMode = "markdown" | "preview";

interface Props {
  tab: TabDescriptor;
}

export function FilePreviewTab({ tab }: Props) {
  const bucket = String(tab.ref.bucket ?? "");
  const key = String(tab.ref.key ?? "");
  const [sheet, setSheet] = useState<string | undefined>(undefined);
  const [markdownView, setMarkdownView] = useState<MarkdownViewMode>("markdown");
  const patchTabRef = useTabStore((s) => s.patchTabRef);
  const { data, isLoading, error } = useFilePreview({ bucket, key, sheet, rows: 200 });

  useEffect(() => {
    setMarkdownView("markdown");
  }, [key]);

  useEffect(() => {
    patchTabRef(tab.id, { markdownView });
  }, [markdownView, patchTabRef, tab.id]);

  if (!bucket || !key) return <p className="placeholder">bucket/key 不正</p>;
  if (isLoading) return <p className="placeholder">読み込み中…</p>;
  if (error) {
    return (
      <div className="tab-error">
        <strong>File Preview 失敗</strong>
        <pre>{String((error as any).message ?? error)}</pre>
      </div>
    );
  }
  if (!data) return <p className="placeholder">no data</p>;

  if (data.status === "error") {
    return (
      <div className="tab-error">
        <strong>{data.error_code}</strong>
        <p>{data.message}</p>
      </div>
    );
  }

  return (
    <div className="tab-content tab-content--file-preview">
      <div className="tab-meta">
        <FilePathBreadcrumb bucket={bucket} objectKey={key} />
        <span className="meta-badge">{data.format ?? "?"}</span>
        {data.format === "markdown" && (
          <MarkdownViewToggle value={markdownView} onChange={setMarkdownView} />
        )}
        {data.encoding && <span className="meta-badge">{data.encoding}</span>}
        {data.total_size !== undefined && (
          <span className="meta-badge">{humanBytes(data.total_size)}</span>
        )}
      </div>
      <FormatBody
        data={data}
        sheet={sheet}
        setSheet={setSheet}
        markdownView={markdownView}
      />
    </div>
  );
}

function MarkdownViewToggle({
  value,
  onChange,
}: {
  value: MarkdownViewMode;
  onChange: (mode: MarkdownViewMode) => void;
}) {
  return (
    <div className="file-preview-view-toggle" role="tablist" aria-label="Markdown view">
      <button
        type="button"
        role="tab"
        aria-selected={value === "preview"}
        className={
          "file-preview-view-toggle__btn" +
          (value === "preview" ? " file-preview-view-toggle__btn--active" : "")
        }
        onClick={() => onChange("preview")}
      >
        Preview
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={value === "markdown"}
        className={
          "file-preview-view-toggle__btn" +
          (value === "markdown" ? " file-preview-view-toggle__btn--active" : "")
        }
        onClick={() => onChange("markdown")}
      >
        Markdown
      </button>
    </div>
  );
}

function FormatBody({
  data,
  sheet,
  setSheet,
  markdownView,
}: {
  data: FilePreviewResponse;
  sheet: string | undefined;
  setSheet: (s: string | undefined) => void;
  markdownView: MarkdownViewMode;
}) {
  switch (data.format) {
    case "csv":
    case "tsv":
      return (
        <CsvBody
          columns={data.columns ?? data.header ?? []}
          rows={data.rows ?? []}
        />
      );
    case "json":
      return <JsonBody value={data.json ?? data.value} />;
    case "jsonl":
      return (
        <JsonlBody
          rows={(data.jsonl ?? data.rows ?? []) as unknown[]}
        />
      );
    case "excel":
      return <ExcelBody data={data} sheet={sheet} setSheet={setSheet} />;
    case "parquet":
      return <ParquetBody data={data} />;
    case "markdown":
      return markdownView === "preview" ? (
        <MarkdownPreviewBody
          text={data.text ?? ""}
          truncated={Boolean(data.truncated)}
        />
      ) : (
        <TextBody
          text={data.text ?? ""}
          truncated={Boolean(data.truncated)}
        />
      );
    case "text":
    case "log":
    case "yaml":
      return (
        <TextBody
          text={data.text ?? ""}
          truncated={Boolean(data.truncated)}
        />
      );
    default:
      return (
        <p className="placeholder">
          未対応フォーマット (format={data.format ?? "unknown"})
        </p>
      );
  }
}

// ---------------- format-specific bodies ---------------- //

function CsvBody({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="table-scroll">
      <table className="preview-table">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={i}>{c || `col_${i}`}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j}>{cellStr(v)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JsonBody({ value }: { value: unknown }) {
  const pretty = value === undefined ? "" : JSON.stringify(value, null, 2);
  return <pre className="json-block">{pretty}</pre>;
}

function JsonlBody({ rows }: { rows: unknown[] }) {
  return (
    <ol className="jsonl-list">
      {rows.map((r, i) => (
        <li key={i}>
          <pre className="json-block">{JSON.stringify(r, null, 2)}</pre>
        </li>
      ))}
    </ol>
  );
}

function ExcelBody({
  data,
  sheet,
  setSheet,
}: {
  data: FilePreviewResponse;
  sheet: string | undefined;
  setSheet: (s: string | undefined) => void;
}) {
  const sheets = (data.sheets ?? []) as Array<Record<string, unknown>>;
  const primary = data.primary_sheet as string | undefined;
  const currentName = sheet ?? primary ?? (sheets[0]?.sheet as string | undefined);
  const current = sheets.find((s) => s.sheet === currentName) ?? sheets[0];
  if (!current) return <p className="placeholder">シートが見つかりません</p>;

  const columns = ((current.columns as string[]) ?? []).map((c, i) => c || `col_${i}`);
  const sampleRows = ((current.sample_rows as unknown[][]) ?? []) as unknown[][];
  const metaKv = (current.meta_kv as Array<Record<string, unknown>>) ?? [];

  return (
    <>
      {sheets.length > 1 && (
        <div className="excel-tabs">
          {sheets.map((s) => {
            const nm = s.sheet as string;
            return (
              <button
                key={nm}
                className={
                  "excel-tab" + (nm === currentName ? " excel-tab--active" : "")
                }
                onClick={() => setSheet(nm)}
              >
                {nm}
                {nm === primary && (
                  <span className="excel-tab-badge">primary</span>
                )}
              </button>
            );
          })}
        </div>
      )}
      {metaKv.length > 0 && (
        <div className="excel-meta">
          {metaKv.map((kv, i) => (
            <div key={i} className="excel-meta-row">
              <span className="excel-meta-key">{cellStr(kv.key)}</span>
              <span className="excel-meta-val">{cellStr(kv.value)}</span>
            </div>
          ))}
        </div>
      )}
      <div className="table-scroll">
        <table className="preview-table preview-table--excel">
          <thead>
            <tr>
              {columns.map((c, i) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sampleRows.map((r, i) => (
              <tr key={i}>
                {r.map((v, j) => (
                  <td key={j}>{cellStr(v)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function MarkdownPreviewBody({
  text,
  truncated,
}: {
  text: string;
  truncated: boolean;
}) {
  return (
    <div className="text-preview markdown-file-preview">
      {truncated && (
        <p className="text-preview-note">先頭 2MB のみ表示しています</p>
      )}
      <div className="text-preview-scroll markdown-body">
        <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
          {text || " "}
        </Markdown>
      </div>
    </div>
  );
}

function TextBody({
  text,
  truncated,
}: {
  text: string;
  truncated: boolean;
}) {
  const lines = text.length ? text.split(/\r?\n/) : [""];
  return (
    <div className="text-preview">
      {truncated && (
        <p className="text-preview-note">先頭 2MB のみ表示しています</p>
      )}
      <div className="text-preview-scroll">
        <pre className="text-preview-body">
          {lines.map((line, index) => (
            <div key={index} className="text-preview-line">
              <span className="text-preview-ln" aria-hidden="true">
                {index + 1}
              </span>
              <code className="text-preview-content">{line || " "}</code>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

function ParquetBody({ data }: { data: FilePreviewResponse }) {
  return (
    <>
      <div className="tab-meta">
        <span className="meta-badge">{data.num_row_groups ?? 0} row groups</span>
        <span className="meta-badge">{data.num_rows ?? 0} rows</span>
      </div>
      <table className="preview-table">
        <thead>
          <tr>
            <th>column</th>
            <th>type</th>
          </tr>
        </thead>
        <tbody>
          {(data.schema ?? []).map((c, i) => (
            <tr key={i}>
              <td>{c.name}</td>
              <td>
                <code>{c.type}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ---------------- path breadcrumb ---------------- //

function FilePathBreadcrumb({
  bucket,
  objectKey,
}: {
  bucket: string;
  objectKey: string;
}) {
  const segments = [bucket, ...objectKey.split("/").filter(Boolean)];
  return (
    <nav className="file-path-breadcrumb" aria-label="File path">
      {segments.map((segment, index) => (
        <Fragment key={`${index}-${segment}`}>
          {index > 0 && (
            <span className="file-path-breadcrumb__sep" aria-hidden="true">
              &gt;
            </span>
          )}
          <span
            className={
              "file-path-breadcrumb__part" +
              (index === segments.length - 1
                ? " file-path-breadcrumb__part--leaf"
                : "")
            }
            title={segment}
          >
            {segment}
          </span>
        </Fragment>
      ))}
    </nav>
  );
}

// ---------------- utils ---------------- //

function cellStr(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function humanBytes(n: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}
