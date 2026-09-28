/**
 * 左 Explorer (Tables / Storage / Graph) の React Query キャッシュを更新する。
 */
import { queryClient } from "./queryClient";

export const EXPLORER_QUERY_KEYS = {
  catalog: ["catalog"] as const,
  files: ["files"] as const,
  graphSchema: ["graph", "schema"] as const,
};

export function refreshCatalogExplorer(): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: EXPLORER_QUERY_KEYS.catalog });
}

export function refreshStorageExplorer(): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: EXPLORER_QUERY_KEYS.files });
}

export function refreshGraphSchema(): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: EXPLORER_QUERY_KEYS.graphSchema });
}

/** Chat 取り込み完了など、複数ソースが変わりうるときに一括更新。 */
export function refreshAllExplorers(): Promise<void> {
  return Promise.all([
    refreshCatalogExplorer(),
    refreshStorageExplorer(),
    refreshGraphSchema(),
  ]).then(() => undefined);
}
