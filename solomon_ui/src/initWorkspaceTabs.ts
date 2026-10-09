import { useRightTabStore } from "./stores/rightTabStore";

/** 初回表示時に右ペイン (Agent) の既定タブを開く。中央はタブ 0 件の Welcome 表示のまま。 */
export function ensureDefaultWorkspaceTabs(): void {
  useRightTabStore.getState().ensureDefaults();
}
