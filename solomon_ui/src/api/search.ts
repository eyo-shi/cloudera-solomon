import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { SearchDocumentScope, SearchDocumentsResponse } from "../types";

/** Search タブは CDE Bronze の inspection-* を既定で検索する。 */
export const SEARCH_TAB_SCOPE: SearchDocumentScope = "inspection";

export function useSearchDocuments(filter: string) {
  const q = filter.trim();
  return useQuery({
    queryKey: ["search", "documents", SEARCH_TAB_SCOPE, q],
    queryFn: () => {
      const params = new URLSearchParams({
        q,
        scope: SEARCH_TAB_SCOPE,
      });
      return apiFetch<SearchDocumentsResponse>(
        `/api/search/documents?${params.toString()}`,
      );
    },
  });
}
