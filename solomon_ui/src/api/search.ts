import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { SearchDocumentScope, SearchDocumentsResponse } from "../types";

/** Search タブは外部パイプラインが投入済みの dataset カタログを読む。 */
export const SEARCH_TAB_SCOPE: SearchDocumentScope = "datasets";

export function useSearchDocuments(filter: string) {
  const q = filter.trim();
  return useQuery({
    queryKey: ["search", "documents", SEARCH_TAB_SCOPE, q],
    queryFn: () => {
      const params = new URLSearchParams({ q });
      return apiFetch<SearchDocumentsResponse>(
        `/api/search/documents?${params.toString()}`,
      );
    },
  });
}
