/**
 * Cursor 風 — 1 エージェント 1 行の実行タイムライン（running は同一行を更新）。
 */
import { useMemo, useState } from "react";
import type { StepEntry } from "../../stores/chatStore";

const AGENT_LABEL: Record<string, string> = {
  RouterCrew: "Router",
  IngestionCrew: "取り込み",
  AnalyticsSummaryCrew: "サマリー",
  AnalyticsDashboardCrew: "ダッシュボード",
  KnowledgeRagCrew: "ナレッジ検索",
  Chat: "応答",
};

function labelFor(agent: string): string {
  return AGENT_LABEL[agent] ?? agent.replace(/Crew$/, "");
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

interface Props {
  steps: StepEntry[];
  defaultCollapsed?: boolean;
  live?: boolean;
}

export function ActivityTimeline({ steps, defaultCollapsed = false, live = false }: Props) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const summary = useMemo(() => {
    if (steps.length === 0) return "";
    const running = steps.filter((s) => s.status === "running").length;
    const errors = steps.filter((s) => s.status === "error").length;
    const done = steps.filter((s) => s.status === "done").length;
    if (live && running > 0) return "実行中…";
    if (errors > 0) return `${errors} 件失敗 · ${done} 件完了`;
    if (done === steps.length) return `${done} ステップ完了`;
    return `${steps.length} ステップ`;
  }, [steps, live]);

  if (steps.length === 0) return null;

  return (
    <div
      className={
        "activity-timeline" + (live ? " activity-timeline--live" : "")
      }
    >
      <button
        type="button"
        className="activity-timeline__toggle"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((v) => !v)}
      >
        <span className="activity-timeline__chevron" aria-hidden="true">
          {collapsed ? "▸" : "▾"}
        </span>
        <span className="activity-timeline__summary">{summary}</span>
      </button>
      {!collapsed && (
        <ul className="activity-timeline__list">
          {steps.map((s) => (
            <li
              key={s.agent}
              className={"activity-timeline__row activity-timeline__row--" + s.status}
              title={s.message}
            >
              <StatusGlyph status={s.status} />
              <span className="activity-timeline__label">{labelFor(s.agent)}</span>
              <span className="activity-timeline__message">{s.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
