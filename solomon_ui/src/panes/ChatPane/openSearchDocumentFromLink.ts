import { apiFetch } from "../../api/client";
import { openSearchDocumentTab } from "../ResultPane/tabs/SearchDocumentTab";
import type { SearchDocumentEntry } from "../../types";
import type { useTabStore } from "../../stores/tabStore";

import { normalizeSolomonHref } from "./solomonAppLinks";

const SCHEME = "solomon://search-document";

export function isSearchDocumentLink(href: string | undefined): boolean {
  return Boolean(normalizeSolomonHref(href)?.startsWith(SCHEME));
}

export function parseSearchDocumentLink(href: string): URLSearchParams | null {
  if (!href.startsWith(SCHEME)) return null;
  const query = href.includes("?") ? href.slice(href.indexOf("?") + 1) : "";
  return new URLSearchParams(query);
}

async function fetchSearchDocument(
  params: URLSearchParams,
): Promise<SearchDocumentEntry> {
  const docId = params.get("doc_id");
  const objectKey = params.get("object_key");
  if (!docId && !objectKey) {
    throw new Error("doc_id or object_key missing in search document link");
  }
  const apiParams = new URLSearchParams();
  if (docId) apiParams.set("doc_id", docId);
  else if (objectKey) apiParams.set("object_key", objectKey);
  const format = params.get("format");
  if (format) apiParams.set("format", format);
  const res = await apiFetch<{ document: SearchDocumentEntry }>(
    `/api/search/document?${apiParams.toString()}`,
  );
  const doc = res.document;
  const chunkId = params.get("chunk_id");
  if (chunkId && !doc.chunk_id) {
    doc.chunk_id = chunkId;
  }
  return doc;
}

export async function openSearchDocumentFromLink(
  href: string,
  openTab: ReturnType<typeof useTabStore.getState>["openTab"],
): Promise<void> {
  const normalized = normalizeSolomonHref(href) ?? href;
  const params = parseSearchDocumentLink(normalized);
  if (!params) return;

  const docId = params.get("doc_id");
  const objectKey = params.get("object_key") ?? "";
  const stub: SearchDocumentEntry = docId
    ? {
        document_type: "doc",
        doc_id: docId,
        chunk_id: params.get("chunk_id"),
        title: docId,
      }
    : {
        object_key: objectKey,
        format: params.get("format"),
        trace_id: params.get("trace_id"),
        index: params.get("index"),
        vb_machine_no: params.get("vb_machine_no"),
        title: objectKey.split("/").filter(Boolean).pop() ?? objectKey,
      };

  const titleFromStub =
    stub.title ??
    (docId || objectKey.split("/").filter(Boolean).pop()) ??
    "document";
  openSearchDocumentTab(openTab, stub, String(titleFromStub));

  try {
    const doc = await fetchSearchDocument(params);
    openSearchDocumentTab(
      openTab,
      doc,
      doc.title ??
        (doc.object_key
          ? doc.object_key.split("/").filter(Boolean).pop()
          : null) ??
        doc.doc_id ??
        String(titleFromStub),
    );
  } catch {
    /* 404 等 — stub タブのまま */
  }
}
