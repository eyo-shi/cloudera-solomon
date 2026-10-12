import { apiFetch } from "../../api/client";
import { openSearchDocumentTab } from "../ResultPane/tabs/SearchDocumentTab";
import type { SearchDocumentEntry } from "../../types";
import type { useTabStore } from "../../stores/tabStore";

const SCHEME = "solomon://search-document";

export function isSearchDocumentLink(href: string | undefined): boolean {
  return Boolean(href?.startsWith(SCHEME));
}

export function parseSearchDocumentLink(href: string): URLSearchParams | null {
  if (!href.startsWith(SCHEME)) return null;
  const query = href.includes("?") ? href.slice(href.indexOf("?") + 1) : "";
  return new URLSearchParams(query);
}

async function fetchSearchDocument(
  params: URLSearchParams,
): Promise<SearchDocumentEntry> {
  const objectKey = params.get("object_key");
  if (!objectKey) {
    throw new Error("object_key missing in search document link");
  }
  const apiParams = new URLSearchParams({ object_key: objectKey });
  const format = params.get("format");
  if (format) apiParams.set("format", format);
  const res = await apiFetch<{ document: SearchDocumentEntry }>(
    `/api/search/document?${apiParams.toString()}`,
  );
  return res.document;
}

export async function openSearchDocumentFromLink(
  href: string,
  openTab: ReturnType<typeof useTabStore.getState>["openTab"],
): Promise<void> {
  const params = parseSearchDocumentLink(href);
  if (!params) return;

  const objectKey = params.get("object_key") ?? "";
  const stub: SearchDocumentEntry = {
    object_key: objectKey,
    format: params.get("format"),
    trace_id: params.get("trace_id"),
    index: params.get("index"),
    vb_machine_no: params.get("vb_machine_no"),
    title: objectKey.split("/").filter(Boolean).pop() ?? objectKey,
  };

  let doc = stub;
  try {
    doc = await fetchSearchDocument(params);
  } catch {
    /* 404 等 — stub でタブを開く */
  }

  const title =
    doc.title ??
    (doc.object_key
      ? doc.object_key.split("/").filter(Boolean).pop()
      : null) ??
    "document";
  openSearchDocumentTab(openTab, doc, title);
}
