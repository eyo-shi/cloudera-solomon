/**
 * Cursor 風 Thinking + activity（-ing 実行中 → -ed 完了）。
 */
import { useEffect, useMemo, useState } from "react";
import type { StepEntry } from "../../stores/chatStore";
import {
  activityLabel,
  completedActivitySummary,
  presentActivity,
} from "./activityTense";

const AGENT_LABEL: Record<string, string> = {
  RouterCrew: "Router",
  IngestionCrew: "Ingestion",
  "Ingestion:Locate": "S3 Scout",
  "Ingestion:Sniff": "Format Sniffer",
  "Ingestion:Extract": "Data Extractor",
  "Ingestion:Schema": "Schema Drafter",
  "Ingestion:Permissions": "Table Creator",
  "Ingestion:CreateTable": "Table Creator",
  "Ingestion:Iceberg": "Table Creator",
  "Ingestion:Graph": "Graph Loader",
  "Ingestion:Ossie": "Ossie Drafter",
  "Ingestion:Search": "Search Indexer",
  "Ingestion:WrapUp": "Ingestion",
  AnalyticsSummaryCrew: "Analytics",
  AnalyticsDashboardCrew: "Analytics",
  KnowledgeRagCrew: "Knowledge RAG",
  Chat: "Chat",
};

const AGENT_ACTIVITY: Record<string, string> = {
  RouterCrew: "Classifying intent",
  IngestionCrew: "Running ingestion pipeline",
  "Ingestion:Locate": "Checking S3",
  "Ingestion:Sniff": "Detecting format",
  "Ingestion:Extract": "Reading sample data",
  "Ingestion:Schema": "Designing schema",
  "Ingestion:Permissions": "Checking permissions",
  "Ingestion:CreateTable": "Creating Iceberg table",
  "Ingestion:Iceberg": "Importing to Iceberg",
  "Ingestion:Graph": "Updating knowledge graph",
  "Ingestion:Ossie": "Drafting semantic layer",
  "Ingestion:Search": "Indexing OpenSearch",
  "Ingestion:WrapUp": "Finalizing report",
  AnalyticsSummaryCrew: "Generating summary",
  AnalyticsDashboardCrew: "Building dashboard",
  KnowledgeRagCrew: "Searching knowledge base",
  Chat: "Composing reply",
};

function labelFor(agent: string): string {
  return AGENT_LABEL[agent] ?? agent.replace(/Crew$/, "").replace(/^Ingestion:/, "");
}

function fallbackPresent(step: StepEntry): string {
  return AGENT_ACTIVITY[step.agent] ?? labelFor(step.agent);
}

function formatThoughtDuration(ms: number): string {
  const sec = Math.max(1, Math.round(ms / 1000));
  if (sec < 60) return `${sec}秒`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m < 60) return s > 0 ? `${m}分${s}秒` : `${m}分`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}時間${rm}分`;
}

function StatusGlyph({ status }: { status: StepEntry["status"] }) {
  if (status === "running") {
    return <span className="activity-timeline__spinner" aria-hidden="true" />;
  }
  if (status === "done") {
    return (
      <span className="activity-timeline__glyph activity-timeline__glyph--done" aria-hidden="true">
        ✓
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="activity-timeline__glyph activity-timeline__glyph--error" aria-hidden="true">
        ✕
      </span>
    );
  }
  return (
    <span className="activity-timeline__glyph activity-timeline__glyph--skipped" aria-hidden="true">
      ◦
    </span>
  );
}

function orderedActivitySteps(steps: StepEntry[]): StepEntry[] {
  const ingestion = steps.filter((s) => s.agent.startsWith("Ingestion:"));
  if (ingestion.length > 0) {
    const order = [
      "Ingestion:Locate",
      "Ingestion:Sniff",
      "Ingestion:Extract",
      "Ingestion:Schema",
      "Ingestion:Permissions",
      "Ingestion:CreateTable",
      "Ingestion:Iceberg",
      "Ingestion:Graph",
      "Ingestion:Ossie",
      "Ingestion:Search",
      "Ingestion:WrapUp",
    ];
    const rank = new Map(order.map((a, i) => [a, i]));
    return [...ingestion].sort(
      (a, b) => (rank.get(a.agent) ?? 99) - (rank.get(b.agent) ?? 99),
    );
  }
  return steps.filter((s) => s.agent !== "IngestionCrew" || s.status !== "running");
}

interface Props {
  steps: StepEntry[];
  narratives?: string[];
  defaultCollapsed?: boolean;
  live?: boolean;
  collapseWhenResult?: boolean;
}

export function ActivityTimeline({
  steps,
  narratives = [],
  defaultCollapsed = false,
  live = false,
  collapseWhenResult = false,
}: Props) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  useEffect(() => {
    if (collapseWhenResult) setCollapsed(true);
  }, [collapseWhenResult]);

  useEffect(() => {
    setCollapsed(defaultCollapsed);
  }, [defaultCollapsed]);

  const runningSteps = steps.filter((s) => s.status === "running");
  const running = runningSteps.length > 0;
  const errors = steps.filter((s) => s.status === "error").length;
  const activitySteps = useMemo(() => orderedActivitySteps(steps), [steps]);

  const labelStep = (s: StepEntry) => activityLabel(s, fallbackPresent(s));

  const runningSummary = useMemo(() => {
    const done = activitySteps.filter((s) => s.status === "done");
    const runningList = activitySteps.filter((s) => s.status === "running");
    const parts: string[] = [];
    if (done.length > 0) {
      parts.push(
        completedActivitySummary(
          done,
          (s) => activityLabel(s, fallbackPresent(s)),
        ),
      );
    }
    if (runningList.length > 0) {
      const current = runningList.map((s) =>
        presentActivity(s, fallbackPresent(s)),
      );
      parts.push(...current);
    }
    return parts.filter(Boolean).join(", ");
  }, [activitySteps]);

  const completedSummary = useMemo(
    () =>
      completedActivitySummary(activitySteps, (s) =>
        activityLabel(s, fallbackPresent(s)),
      ),
    [activitySteps],
  );

  const durationMs = useMemo(() => {
    if (steps.length === 0) return 0;
    const times = steps.map((s) => s.at).filter((t) => t > 0);
    if (times.length === 0) return 0;
    const start = Math.min(...times);
    const end = live && running ? Date.now() : Math.max(...times);
    return Math.max(0, end - start);
  }, [steps, live, running]);

  const headerTitle = useMemo(() => {
    if (live && running && runningSummary) return runningSummary;
    if (live && running) return "Thinking";
    if (!live && !running && completedSummary) return completedSummary;
    if (errors > 0) return completedSummary || "Thought";
    if (durationMs > 0 && durationMs < 90_000 && !completedSummary) {
      return "Thought briefly";
    }
    if (durationMs >= 90_000 && !completedSummary) {
      return `Thought for ${formatThoughtDuration(durationMs)}`;
    }
    return completedSummary || (live ? "Thinking" : "Thought briefly");
  }, [live, running, errors, durationMs, runningSummary, completedSummary]);

  const hasContent = steps.length > 0 || narratives.length > 0;
  if (!hasContent) return null;

  const showNarratives = narratives.length > 0;
  const showActivityList = activitySteps.length > 0;

  return (
    <div
      className={
        "activity-timeline thinking-block" +
        (live && running ? " activity-timeline--live thinking-block--live" : "")
      }
    >
      <button
        type="button"
        className="activity-timeline__toggle thinking-block__header"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((v) => !v)}
      >
        <span className="activity-timeline__chevron" aria-hidden="true">
          {collapsed ? "▸" : "▾"}
        </span>
        {live && running && (
          <span className="thinking-block__header-spinner" aria-hidden="true" />
        )}
        <span className="thinking-block__title">{headerTitle}</span>
        {!live && durationMs > 0 && collapsed && (
          <span className="thinking-block__duration">{formatThoughtDuration(durationMs)}</span>
        )}
      </button>

      {!collapsed && (
        <div className="thinking-block__body">
          {showNarratives && (
            <ul className="thinking-block__narratives">
              {narratives.map((line, i) => (
                <li key={`${i}-${line.slice(0, 24)}`}>{line}</li>
              ))}
            </ul>
          )}

          {showActivityList && (
            <ul className="thinking-block__activities">
              {activitySteps.map((s) => (
                <li
                  key={s.agent}
                  className={
                    "thinking-block__activity thinking-block__activity--" + s.status
                  }
                >
                  <StatusGlyph status={s.status} />
                  <div className="thinking-block__activity-text">
                    <span className="thinking-block__activity-name">{labelStep(s)}</span>
                    <span className="thinking-block__activity-agent">{labelFor(s.agent)}</span>
                    {s.message && s.status !== "running" && (
                      <span className="thinking-block__activity-detail">{s.message}</span>
                    )}
                    {s.message && s.status === "running" && (
                      <span className="thinking-block__activity-detail thinking-block__activity-detail--live">
                        {s.message}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {live && running && !showActivityList && steps.length > 0 && (
            <p className="thinking-block__hint">
              {steps.find((s) => s.status === "running")?.message ||
                "処理を実行しています…"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
