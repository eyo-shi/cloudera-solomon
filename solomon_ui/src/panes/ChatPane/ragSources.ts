export type RagSourcesPreset = "table" | "table_graph" | "table_search" | "all";

export type RagSourceName = "table" | "graph" | "search";

const STORAGE_KEY = "solomon.ragSourcesPreset";

export const RAG_PRESET_OPTIONS: {
  id: RagSourcesPreset;
  label: string;
}[] = [
  { id: "table", label: "テーブルのみ" },
  { id: "table_graph", label: "＋Graph" },
  { id: "table_search", label: "＋Search" },
  { id: "all", label: "全部" },
];

export function presetToSources(preset: RagSourcesPreset): RagSourceName[] {
  switch (preset) {
    case "table":
      return ["table"];
    case "table_graph":
      return ["table", "graph"];
    case "table_search":
      return ["table", "search"];
    case "all":
    default:
      return ["table", "graph", "search"];
  }
}

export function presetBadgeLabel(preset: RagSourcesPreset): string {
  const opt = RAG_PRESET_OPTIONS.find((o) => o.id === preset);
  return opt?.label ?? preset;
}

export function loadRagSourcesPreset(): RagSourcesPreset {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (
      raw === "table" ||
      raw === "table_graph" ||
      raw === "table_search" ||
      raw === "all"
    ) {
      return raw;
    }
  } catch {
    /* ignore */
  }
  return "all";
}

export function saveRagSourcesPreset(preset: RagSourcesPreset): void {
  try {
    localStorage.setItem(STORAGE_KEY, preset);
  } catch {
    /* ignore */
  }
}
