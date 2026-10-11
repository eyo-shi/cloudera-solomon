/**
 * Search (Semantic Search) ビュー — CDE Bronze ``inspection-*`` ドキュメント一覧。
 */
import { isSetupGuideError } from "../../api/client";
import { refreshSearchExplorer } from "../../api/explorerRefresh";
import { useSearchDocuments } from "../../api/search";
import { useReportSetupGuideError } from "../../hooks/useReportSetupGuideError";
import type { SearchDocumentEntry } from "../../types";
import { ExplorerRefreshButton } from "./ExplorerRefreshButton";

interface SearchViewProps {
  filter: string;
}

function displayTitle(doc: SearchDocumentEntry, index: number): string {
  if (doc.title) return doc.title;
  if (doc.fq_name) return doc.fq_name;
  if (doc.object_key) {
    const parts = doc.object_key.split("/");
    return parts[parts.length - 1] || doc.object_key;
  }
  return `doc-${index}`;
}

function displaySubtitle(doc: SearchDocumentEntry): string | null {
  if (doc.subtitle) return doc.subtitle;
  const bits: string[] = [];
  if (doc.format) bits.push(doc.format);
  if (doc.trace_id) bits.push(`KIBAN ${doc.trace_id}`);
  if (doc.vb_machine_no) bits.push(`VB ${doc.vb_machine_no}`);
  if (doc.fq_name && doc.fq_name !== doc.title) bits.push(doc.fq_name);
  return bits.length ? bits.join(" · ") : null;
}

export function SearchView({ filter }: SearchViewProps) {
  const { data, isLoading, error, isFetching } = useSearchDocuments(filter);
  useReportSetupGuideError(error);

  const documents = data?.documents ?? [];
  const indexHint = data?.index ?? "inspection-*";

  const sectionHead = (
    <div className="explorer-section-head">
      <span className="explorer-section-title">Search</span>
      <span className="explorer-section-count">({documents.length})</span>
      <span className="explorer-section-meta" title={indexHint}>
        {indexHint}
      </span>
      <div className="explorer-section-actions">
        <ExplorerRefreshButton
          isFetching={isFetching}
          onRefresh={() => void refreshSearchExplorer()}
        />
      </div>
    </div>
  );

  if (isLoading) {
    return (
      <div className="explorer-view explorer-view--search">
        {sectionHead}
        <p className="explorer-placeholder">Loading documents…</p>
      </div>
    );
  }
  if (isSetupGuideError(error)) {
    return (
      <div className="explorer-view explorer-view--search">
        {sectionHead}
        <p className="explorer-placeholder">
          Semantic Search 未設定です。右ペインの設定手順を確認してください。
        </p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="explorer-view explorer-view--search">
        {sectionHead}
        <p className="explorer-error">ドキュメント取得に失敗</p>
      </div>
    );
  }

  return (
    <div className="explorer-view explorer-view--search">
      {sectionHead}
      <ul className="explorer-list">
        {documents.map((doc, i) => {
          const title = displayTitle(doc, i);
          const subtitle = displaySubtitle(doc);
          const key =
            doc.object_key ??
            doc.fq_name ??
            `${doc.index ?? "doc"}-${i}`;
          return (
            <li key={`${key}-${i}`} className="explorer-search-doc">
              <span className="explorer-search-doc__name">{title}</span>
              {subtitle && (
                <span className="explorer-search-doc__fq">{subtitle}</span>
              )}
              {doc.object_key && (
                <span className="explorer-search-doc__path">{doc.object_key}</span>
              )}
            </li>
          );
        })}
        {documents.length === 0 && (
          <li className="explorer-placeholder">
            {filter.trim()
              ? "一致する Bronze ファイルがありません"
              : "inspection-* にドキュメントがありません（CDE 取込を Run してください）"}
          </li>
        )}
      </ul>
    </div>
  );
}
