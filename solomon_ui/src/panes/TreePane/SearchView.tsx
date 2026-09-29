/**
 * Search (Semantic Search) ビュー — OpenSearch インデックス済みドキュメント一覧。
 */
import { isSetupGuideError } from "../../api/client";
import { refreshSearchExplorer } from "../../api/explorerRefresh";
import { useSearchDocuments } from "../../api/search";
import { useReportSetupGuideError } from "../../hooks/useReportSetupGuideError";
import { ExplorerRefreshButton } from "./ExplorerRefreshButton";

interface SearchViewProps {
  filter: string;
}

export function SearchView({ filter }: SearchViewProps) {
  const { data, isLoading, error, isFetching } = useSearchDocuments(filter);
  useReportSetupGuideError(error);

  const documents = data?.documents ?? [];

  const sectionHead = (
    <div className="explorer-section-head">
      <span className="explorer-section-title">Search</span>
      <span className="explorer-section-count">({documents.length})</span>
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
          const fq = doc.fq_name ?? `doc-${i}`;
          const name =
            (doc.dataset?.name as string | undefined) ??
            (doc.dataset?.description as string | undefined) ??
            fq;
          return (
            <li key={`${fq}-${i}`} className="explorer-search-doc">
              <span className="explorer-search-doc__name">{name}</span>
              {doc.fq_name && doc.fq_name !== name && (
                <span className="explorer-search-doc__fq">{doc.fq_name}</span>
              )}
            </li>
          );
        })}
        {documents.length === 0 && (
          <li className="explorer-placeholder">ドキュメントが見つかりません</li>
        )}
      </ul>
    </div>
  );
}
