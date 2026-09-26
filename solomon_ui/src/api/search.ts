import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { SearchDocumentsResponse } from "../types";

export function useSearchDocuments(filter: string) {
  const q = filter.trim();
  return useQuery({
    queryKey: ["search", "documents", q],
    queryFn: () =>
      apiFetch<SearchDocumentsResponse>(
        `/api/search/documents?q=${encodeURIComponent(q)}`,
      ),
  });
}
