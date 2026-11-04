/**
 * Search (Semantic Search) ビュー — dataset カタログと業務文書 (scope=docs/both) の一覧。
 */
import { apiFetch, isSetupGuideError } from "../../api/client";
import { refreshSearchExplorer } from "../../api/explorerRefresh";
import { useSearchDocuments } from "../../api/search";
import { useReportSetupGuideError } from "../../hooks/useReportSetupGuideError";
import type { SearchDocumentEntry } from "../../types";
import {
  openSearchDocumentTab,
  searchDocumentDedupeKey,
} from "../ResultPane/tabs/SearchDocumentTab";
import { useTabStore } from "../../stores/tabStore";
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
  if (doc.document_type === "doc") {
    if (doc.doc_type_label || doc.doc_type) bits.push(String(doc.doc_type_label || doc.doc_type));
    if (doc.doc_date) bits.push(doc.doc_date);
    if (doc.section) bits.push(doc.section);
    return bits.length ? bits.join(" · ") : null;
  }
  if (doc.format) bits.push(doc.format);
  if (doc.trace_id) bits.push(`KIBAN ${doc.trace_id}`);
  if (doc.vb_machine_no) bits.push(`VB ${doc.vb_machine_no}`);
  if (doc.fq_name && doc.fq_name !== doc.title) bits.push(doc.fq_name);
  return bits.length ? bits.join(" · ") : null;
}

/** 旧 API (scope=both で ``{datasets, docs}`` を返す) でも落ちないよう配列に揃える。 */
function asDocumentList(raw: unknown): SearchDocumentEntry[] {
  if (Array.isArray(raw)) return raw as SearchDocumentEntry[];
  if (raw && typeof raw === "object") {
    const grouped = raw as { datasets?: unknown; docs?: unknown };
    const datasets = Array.isArray(grouped.datasets) ? grouped.datasets : [];
    const docs = Array.isArray(grouped.docs)
      ? grouped.docs.map((d) => ({ document_type: "doc" as const, ...(d as object) }))
      : [];
    return [...datasets, ...docs] as SearchDocumentEntry[];
  }
  return [];
}

/**
 * 業務文書の検索ヒット (1 チャンク) から文書全体を取得してタブを開く。
 * openTab は同じ dedupeKey の既存タブを差し替えないので、取得してから開く。
 */
async function openBusinessDocument(
  openTab: ReturnType<typeof useTabStore.getState>["openTab"],
  doc: SearchDocumentEntry,
  title: string,
): Promise<void> {
  if (doc.doc_id) {
    try {
      const params = new URLSearchParams({ doc_id: doc.doc_id });
      const res = await apiFetch<{ document: SearchDocumentEntry }>(
        `/api/search/document?${params.toString()}`,
      );
      openSearchDocumentTab(
        openTab,
        { ...res.document, chunk_id: doc.chunk_id ?? res.document.chunk_id },
        res.document.title ?? title,
      );
      return;
    } catch {
      /* 取得できなければヒットしたチャンクだけで開く */
    }
  }
  openSearchDocumentTab(openTab, doc, title);
}

export function SearchView({ filter }: SearchViewProps) {
  const { data, isLoading, error, isFetching } = useSearchDocuments(filter);
  useReportSetupGuideError(error);
  const openTab = useTabStore((s) => s.openTab);
  const activeTab = useTabStore((s) => {
    const id = s.activeId;
    if (!id) return null;
    return s.tabs.find((t) => t.id === id) ?? null;
  });

  const documents = asDocumentList(data?.documents);
  const indexHint = data?.index ?? "solomon-datasets";
  const searchesDocs = data?.scope === "docs" || data?.scope === "both";
  const emptyMessage = filter.trim()
    ? searchesDocs
      ? "一致する dataset・文書がありません"
      : "一致する dataset がありません"
    : searchesDocs
      ? "キーワードを入力すると業務文書を検索します"
      : "Semantic Search に dataset がありません（別プロジェクトでインデックス投入後に表示されます）";

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
            doc.chunk_id ??
            `${doc.index ?? "doc"}-${i}`;
          const isBusinessDoc = doc.document_type === "doc";
          const dedupeKey = searchDocumentDedupeKey(doc);
          const isSelected =
            activeTab?.kind === "search_document" &&
            (activeTab.dedupeKey ?? "") === dedupeKey;
          return (
            <li key={`${key}-${i}`}>
              <button
                type="button"
                className={
                  "explorer-search-doc" +
                  (isSelected ? " explorer-search-doc--selected" : "")
                }
                onClick={() =>
                  isBusinessDoc
                    ? void openBusinessDocument(openTab, doc, title)
                    : openSearchDocumentTab(openTab, doc, title)
                }
              >
                <span className="explorer-search-doc__name">{title}</span>
                {subtitle && (
                  <span className="explorer-search-doc__fq">{subtitle}</span>
                )}
                {doc.object_key && (
                  <span className="explorer-search-doc__path">{doc.object_key}</span>
                )}
              </button>
            </li>
          );
        })}
        {documents.length === 0 && (
          <li className="explorer-placeholder">{emptyMessage}</li>
        )}
      </ul>
    </div>
  );
}
