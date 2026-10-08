/**
 * 左 Explorer の表示モード (Tables / Storage / Graph / Search)。
 * 中央ペインの active タブ種別と連動する。
 */
import { create } from "zustand";
import {
  refreshCatalogExplorer,
  refreshGraphSchema,
  refreshStorageExplorer,
} from "../api/explorerRefresh";
import type { ArtifactType } from "../types";

export type ExplorerMode = "tables" | "storage" | "graph" | "search";

interface ExplorerState {
  mode: ExplorerMode;
  setMode: (mode: ExplorerMode) => void;
  syncToTabKind: (kind: ArtifactType) => void;
}

function refreshExplorerMode(mode: ExplorerMode): void {
  switch (mode) {
    case "tables":
      void refreshCatalogExplorer();
      break;
    case "storage":
      void refreshStorageExplorer();
      break;
    case "graph":
      void refreshGraphSchema();
      break;
    default:
      break;
  }
}

/** 中央タブ種別 → 左 Explorer モード。 */
export function explorerModeForTabKind(
  kind: ArtifactType,
): ExplorerMode | null {
  switch (kind) {
    case "graph":
      return "graph";
    case "tables":
    case "table_preview":
    case "sql":
    case "dashboard":
    case "summary":
      return "tables";
    case "file_preview":
      return "storage";
    default:
      return null;
  }
}

export const useExplorerStore = create<ExplorerState>((set, get) => ({
  mode: "tables",
  setMode: (next) => {
    const prev = get().mode;
    if (next !== prev) {
      refreshExplorerMode(next);
    }
    set({ mode: next });
  },
  syncToTabKind: (kind) => {
    const mode = explorerModeForTabKind(kind);
    if (mode) {
      get().setMode(mode);
    }
  },
}));
