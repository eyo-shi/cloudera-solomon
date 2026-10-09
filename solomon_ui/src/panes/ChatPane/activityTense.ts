/**
 * Cursor 風: Checking S3 → Checked S3 / Importing to Iceberg → Imported to Iceberg
 */
import type { StepEntry } from "../../stores/chatStore";

/** 進行形 (SSE / 既定) → 完了形 */
export const ACTIVITY_PAST: Record<string, string> = {
  "Classifying intent": "Classified intent",
  "Running ingestion pipeline": "Completed ingestion pipeline",
  "Ingestion complete": "Ingestion complete",
  "Checking S3": "Checked S3",
  "Detecting format": "Detected format",
  "Reading sample data": "Read sample data",
  "Designing schema": "Designed schema",
  "Checking permissions": "Checked permissions",
  "Creating Iceberg table": "Created Iceberg table",
  "Importing to Iceberg": "Imported to Iceberg",
  "Updating knowledge graph": "Updated knowledge graph",
  "Drafting semantic layer": "Drafted semantic layer",
  "Indexing OpenSearch": "Indexed OpenSearch",
  "Finalizing report": "Finalized report",
  "Generating summary": "Generated summary",
  "Building dashboard": "Built dashboard",
  "Searching knowledge base": "Searched knowledge base",
  "Composing reply": "Composed reply",
};

export function presentActivity(
  step: Pick<StepEntry, "agent" | "activity">,
  fallbackPresent: string,
): string {
  const raw = step.activity?.trim();
  return raw || fallbackPresent;
}

export function activityLabel(
  step: StepEntry,
  fallbackPresent: string,
): string {
  const present = presentActivity(step, fallbackPresent);
  if (step.status === "running") return present;
  if (step.status === "skipped") {
    const past = toPastTense(present);
    return past.startsWith("Skipped") ? past : `Skipped: ${past}`;
  }
  if (step.status === "error") {
    return `Failed: ${present}`;
  }
  return toPastTense(present);
}

export function toPastTense(present: string): string {
  const exact = ACTIVITY_PAST[present];
  if (exact) return exact;
  if (/\b\w+ing\b/.test(present)) {
    return present.replace(/\b(\w*?)ing\b/g, (_m, stem: string) => {
      if (stem.endsWith("tt")) return `${stem.slice(0, -1)}ed`;
      if (stem.endsWith("t")) return `${stem}ed`;
      if (stem === "run") return "ran";
      if (stem === "ead") return "read";
      if (stem === "uild") return "built";
      return `${stem}ed`;
    });
  }
  return present;
}

/** 折りたたみヘッダー用: "Checked S3, imported to Iceberg, …" */
export function completedActivitySummary(
  steps: StepEntry[],
  labelForStep: (step: StepEntry) => string,
): string {
  const parts = steps
    .filter((s) => s.status === "done")
    .map((s) => labelForStep(s))
    .filter(Boolean);
  if (parts.length === 0) return "";
  if (parts.length === 1) return parts[0];
  if (parts.length <= 4) {
    return parts
      .map((p, i) => (i === 0 ? p : p.charAt(0).toLowerCase() + p.slice(1)))
      .join(", ");
  }
  const head = parts.slice(0, 2).join(", ");
  const tail = parts[parts.length - 1];
  const tailLower = tail.charAt(0).toLowerCase() + tail.slice(1);
  return `${head}, …, ${tailLower}`;
}
