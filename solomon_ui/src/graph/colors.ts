/** Neo4j Browser 風ラベル色 — 左ペインと Graph 可視化で共有。 */

const PALETTE = [
  "#A5D6A7",
  "#BCAAA4",
  "#CE93D8",
  "#90CAF9",
  "#FFF59D",
  "#FFAB91",
  "#80CBC4",
  "#F48FB1",
  "#9FA8DA",
  "#C5E1A5",
  "#B39DDB",
  "#81D4FA",
];

const KNOWN_LABEL_COLORS: Record<string, string> = {
  System: "#2563eb",
  Dataset: "#059669",
  Column: "#7c3aed",
  Document: "#d97706",
  SourceFile: "#64748b",
  Schema: "#0891b2",
  MetadataEntry: "#be185d",
};

function hashLabel(label: string): number {
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) {
    hash = label.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash);
}

export function labelColor(label: string): string {
  if (KNOWN_LABEL_COLORS[label]) return KNOWN_LABEL_COLORS[label];
  return PALETTE[hashLabel(label) % PALETTE.length];
}

export function primaryNodeColor(labels: string[]): string {
  return labelColor(labels[0] ?? "Node");
}
