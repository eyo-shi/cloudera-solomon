/**
 * Search (Semantic Search) ビュー — OpenSearch インデックス済みドキュメント一覧。
 */
import { SetupGuideError } from "../../api/client";
import { useSearchDocuments } from "../../api/search";

interface SearchViewProps {
  filter: string;
}

export function SearchView({ filter }: SearchViewProps) {
  const { data, isLoading, error } = useSearchDocuments(filter);

  if (isLoading) return <p className="explorer-placeholder">Loading documents…</p>;
  if (error instanceof SetupGuideError) {
    return (
      <p className="explorer-placeholder">
        Semantic Search 未設定です。Data Connection または環境変数を確認してください。
      </p>
    );
  }
  if (error) return <p className="explorer-error">ドキュメント取得に失敗</p>;

  const documents = data?.documents ?? [];

  return (
    <div className="explorer-view explorer-view--search">
      <div className="explorer-section-head">
        <span className="explorer-section-title">Search</span>
        <span className="explorer-section-count">({documents.length})</span>
      </div>
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
