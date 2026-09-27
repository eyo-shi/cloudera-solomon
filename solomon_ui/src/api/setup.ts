import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

/** ChatPane 起動時に LLM 設定を確認する (未設定なら SetupGuideError)。 */
export function useLlmSetupProbe() {
  return useQuery({
    queryKey: ["setup", "llm"],
    queryFn: () => apiFetch<{ status: string }>("/api/setup/llm"),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}
