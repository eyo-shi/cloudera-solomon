/**
 * OpenSearch inspection / dataset / business 文書の詳細。
 */
import { useEffect, useRef } from "react";
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

function BusinessDocumentBody({ doc }: { doc: SearchDocumentEntry }) {
  const highlightRef = useRef<HTMLElement | null>(null);
  const targetChunk = doc.chunk_id?.trim() || null;
  const labels = doc.metadata_labels ?? {};
  const metadata = doc.metadata ?? {};

  useEffect(() => {
    highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [doc.doc_id, targetChunk]);

  const metaEntries = Object.entries(metadata).filter(
    ([, v]) => v !== null && v !== undefined && String(v).trim() !== "",
  );

  const chunks =
    doc.chunks && doc.chunks.length > 0
      ? doc.chunks
      : doc.text
        ? [{ chunk_id: null, section: null, text: doc.text }]
        : [];

  return (
    <>
      <div className="tab-meta search-doc-meta">
        {doc.doc_type_label && (
          <div className="search-doc-meta__row search-doc-meta__row--primary">
            <span className="search-doc-meta__value">{doc.doc_type_label}</span>
          </div>
        )}
        {doc.doc_date && (
          <div className="search-doc-meta__row">
            <span className="search-doc-meta__value">{doc.doc_date}</span>
          </div>
        )}
        {doc.index && <MetaRow label="Index" value={doc.index} />}
      </div>
      {metaEntries.length > 0 && (
        <div className="search-doc-meta search-doc-meta--grid">
          {metaEntries.map(([key, val]) => (
            <MetaRow
              key={key}
              label={labels[key] ?? key}
              value={String(val)}
            />
          ))}
        </div>
      )}
      <div className="search-doc-sections">
        {chunks.map((chunk, i) => {
          const cid = chunk.chunk_id?.trim() || null;
          const isTarget = targetChunk && cid === targetChunk;
          const sectionTitle = chunk.section?.trim() || (cid ? `Section ${cid}` : `Part ${i + 1}`);
          return (
            <section
              key={cid ?? `part-${i}`}
              ref={isTarget ? highlightRef : undefined}
              className={
                isTarget
                  ? "search-doc-section search-doc-section--highlight"
                  : "search-doc-section"
              }
            >
              <h4 className="search-doc-section__title">{sectionTitle}</h4>
              <pre className="search-doc-section__text">{chunk.text ?? ""}</pre>
            </section>
          );
        })}
      </div>
    </>
  );
}

function LegacyDocumentBody({ doc }: { doc: SearchDocumentEntry }) {
  const payload = doc.payload ?? doc.dataset;
  const payloadJson =
    payload !== undefined && payload !== null
      ? JSON.stringify(payload, null, 2)
      : null;

  return (
    <>
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
    </>
  );
}

export function SearchDocumentTab({ tab }: Props) {
  const doc = asDocument(tab.ref);
  if (!doc) return <p className="placeholder">ドキュメント参照がありません</p>;
  if (doc.load_state === "loading") {
    return <p className="placeholder">文書を読み込んでいます…</p>;
  }
  if (doc.load_state === "error") {
    return (
      <p className="placeholder">
        文書を取得できませんでした: {doc.load_error ?? "unknown error"}
      </p>
    );
  }

  return (
    <div className="tab-content tab-content--search-document">
      {doc.document_type === "doc" ? (
        <BusinessDocumentBody doc={doc} />
      ) : (
        <LegacyDocumentBody doc={doc} />
      )}
    </div>
  );
}

export function searchDocumentDedupeKey(doc: SearchDocumentEntry): string {
  if (doc.doc_id) {
    return `search:doc:${doc.doc_id}`;
  }
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
): string {
  return openTab({
    title,
    kind: "search_document",
    ref: { document: { ...doc } },
    dedupeKey: searchDocumentDedupeKey(doc),
  });
}
