/**
 * Tables ワークスペース — 単一 Tables タブ内の SQL 入力と結果スタック。
 */
import { create } from "zustand";
import { apiFetch } from "../api/client";
import type { QueryResponse } from "../types";
import { useTabStore } from "./tabStore";

export interface TablesResultPanel {
  id: string;
  sql: string;
  status: "loading" | "ready" | "error";
  error?: string;
  data?: QueryResponse;
  catalog?: string;
}

interface TablesState {
  queryInput: string;
  panels: TablesResultPanel[];
  maximizedPanelId: string | null;
  setQueryInput: (value: string) => void;
  appendTablePreview: (fq: string, maxRows?: number) => void;
  runQueryInput: (catalog?: string) => void;
  removePanel: (panelId: string) => void;
  toggleMaximizePanel: (panelId: string) => void;
  rerunPanel: (panelId: string) => void;
}

const TABLES_TAB_KEY = "tables:workspace";
const DEFAULT_CATALOG = "iceberg";

let _panelSeq = 0;
function nextPanelId(): string {
  _panelSeq += 1;
  return `tables-panel-${_panelSeq}`;
}

export function ensureTablesTab(): void {
  useTabStore.getState().openTab({
    title: "Tables",
    kind: "tables",
    ref: { workspace: true },
    dedupeKey: TABLES_TAB_KEY,
  });
}

function previewSql(fq: string, maxRows: number): string {
  const parts = fq.split(".");
  if (parts.length !== 3) {
    throw new Error(`Invalid fq: ${fq}`);
  }
  const [catalog, schema, table] = parts;
  return `SELECT * FROM "${catalog}"."${schema}"."${table}" LIMIT ${maxRows}`;
}

async function executeSql(
  sql: string,
  catalog: string = DEFAULT_CATALOG,
): Promise<QueryResponse> {
  return apiFetch<QueryResponse>("/api/query", {
    method: "POST",
    body: JSON.stringify({ sql, catalog, max_rows: 100 }),
  });
}

async function loadPanel(
  panelId: string,
  loader: () => Promise<QueryResponse>,
): Promise<void> {
  useTablesStore.setState((s) => ({
    panels: s.panels.map((p) =>
      p.id === panelId
        ? { ...p, status: "loading" as const, error: undefined, data: undefined }
        : p,
    ),
  }));
  try {
    const data = await loader();
    useTablesStore.setState((s) => ({
      panels: s.panels.map((p) =>
        p.id === panelId ? { ...p, status: "ready" as const, data } : p,
      ),
    }));
  } catch (err) {
    useTablesStore.setState((s) => ({
      panels: s.panels.map((p) =>
        p.id === panelId
          ? {
              ...p,
              status: "error" as const,
              error: String((err as Error).message ?? err),
            }
          : p,
      ),
    }));
  }
}

export const useTablesStore = create<TablesState>((set, get) => ({
  queryInput: "",
  panels: [],
  maximizedPanelId: null,

  setQueryInput: (value) => set({ queryInput: value }),

  appendTablePreview: (fq, maxRows = 100) => {
    const sql = previewSql(fq, maxRows);
    ensureTablesTab();
    const panelId = nextPanelId();
    const catalog = fq.split(".")[0] ?? DEFAULT_CATALOG;
    set((s) => ({
      queryInput: sql,
      panels: [
        {
          id: panelId,
          sql,
          status: "loading",
          catalog,
        },
        ...s.panels,
      ],
    }));
    void loadPanel(panelId, () => executeSql(sql, catalog));
  },

  runQueryInput: (catalog = DEFAULT_CATALOG) => {
    const sql = get().queryInput.trim();
    if (!sql) return;
    ensureTablesTab();
    const panelId = nextPanelId();
    set((s) => ({
      panels: [
        {
          id: panelId,
          sql,
          status: "loading",
          catalog,
        },
        ...s.panels,
      ],
    }));
    void loadPanel(panelId, () => executeSql(sql, catalog));
  },

  removePanel: (panelId) => {
    set((s) => ({
      panels: s.panels.filter((p) => p.id !== panelId),
      maximizedPanelId:
        s.maximizedPanelId === panelId ? null : s.maximizedPanelId,
    }));
  },

  toggleMaximizePanel: (panelId) => {
    set((s) => ({
      maximizedPanelId:
        s.maximizedPanelId === panelId ? null : panelId,
    }));
  },

  rerunPanel: (panelId) => {
    const panel = get().panels.find((p) => p.id === panelId);
    if (!panel) return;
    set({ queryInput: panel.sql });
    void loadPanel(panelId, () =>
      executeSql(panel.sql, panel.catalog ?? DEFAULT_CATALOG),
    );
  },
}));
