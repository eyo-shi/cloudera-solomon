/**
 * OpenSearch inspection / dataset ドキュメントの詳細（Bronze payload 等）。
 */
import type { SearchDocumentEntry, TabDescriptor } from "../../../types";
import type { useTabStore } from "../../../stores/tabStore";

interface Props {
  tab: TabDescriptor;
}

function asDocument(ref: Record<string, unknown>): SearchDocumentEntry | null {
  const raw = ref.document;
  if (!raw || typeof raw !== "object") return null;
  return raw as SearchDocumentEntry;
}

function MetaRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="search-doc-meta__row">
      <span className="search-doc-meta__label">{label}</span>
      <span className="search-doc-meta__value">{value}</span>
    </div>
  );
}

export function SearchDocumentTab({ tab }: Props) {
  const doc = asDocument(tab.ref);
  if (!doc) return <p className="placeholder">ドキュメント参照がありません</p>;

  const payload = doc.payload ?? doc.dataset;
  const payloadJson =
    payload !== undefined && payload !== null
      ? JSON.stringify(payload, null, 2)
      : null;

  return (
    <div className="tab-content tab-content--search-document">
      <div className="tab-meta search-doc-meta">
        <MetaRow label="Index" value={doc.index ?? undefined} />
        <MetaRow label="Format" value={doc.format ?? undefined} />
        <MetaRow label="KIBAN / trace_id" value={doc.trace_id ?? undefined} />
        <MetaRow label="VB machine" value={doc.vb_machine_no ?? undefined} />
        <MetaRow label="Object key" value={doc.object_key ?? undefined} />
        {doc.fq_name && <MetaRow label="Dataset" value={doc.fq_name} />}
        {doc.score != null && (
          <MetaRow label="Score" value={String(doc.score)} />
        )}
      </div>
      {payloadJson ? (
        <pre className="search-doc-payload">{payloadJson}</pre>
      ) : (
        <p className="placeholder">payload がありません</p>
      )}
    </div>
  );
}

export function searchDocumentDedupeKey(doc: SearchDocumentEntry): string {
  const id =
    doc.object_key ??
    doc.fq_name ??
    doc.title ??
    doc.trace_id ??
    "unknown";
  return `search:${doc.index ?? "idx"}:${id}`;
}

export function openSearchDocumentTab(
  openTab: ReturnType<typeof useTabStore.getState>["openTab"],
  doc: SearchDocumentEntry,
  title: string,
): void {
  openTab({
    title,
    kind: "search_document",
    ref: { document: { ...doc } },
    dedupeKey: searchDocumentDedupeKey(doc),
  });
}
