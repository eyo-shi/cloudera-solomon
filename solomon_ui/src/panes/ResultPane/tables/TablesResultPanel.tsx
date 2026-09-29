/**
 * Trino SQL 1 件分の結果フレーム (Graph の Table ビュー相当、Raw 切替なし)。
 */
import { useState } from "react";
import {
  type TablesResultPanel as TablesResultPanelState,
  useTablesStore,
} from "../../../stores/tablesStore";
import type { QueryResponse } from "../../../types";
import { IconChevronToggle } from "../../TreePane/ExplorerIcons";

interface Props {
  panel: TablesResultPanelState;
  isMaximized?: boolean;
}

function IconMaximize({ active }: { active?: boolean }) {
  return (
    <svg className="graph-frame__icon-svg" viewBox="0 0 16 16" aria-hidden="true">
      {active ? (
        <path
          d="M10 2h4v4M14 2 9 7M6 14H2v-4M2 14l5-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : (
        <path
          d="M6 2h4v4M10 2 5 7M10 14H6v-4M6 14l5-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  );
}

function renderCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function QueryResultTable({ data }: { data: QueryResponse }) {
  return (
    <div className="graph-frame__table-wrap">
      <table className="graph-result-table">
        <thead>
          <tr>
            <th className="graph-result-table__row-num" />
            {data.columns.map((col) => (
              <th key={col.name}>{col.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, idx) => (
            <tr key={idx}>
              <td className="graph-result-table__row-num">{idx + 1}</td>
              {row.map((cell, j) => (
                <td key={j}>
                  <code>{renderCell(cell)}</code>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TablesResultPanel({ panel, isMaximized = false }: Props) {
  const removePanel = useTablesStore((s) => s.removePanel);
  const toggleMaximizePanel = useTablesStore((s) => s.toggleMaximizePanel);
  const [collapsed, setCollapsed] = useState(false);

  const recordCount = panel.data?.rows.length ?? 0;

  function onToggleMaximize() {
    if (!isMaximized && collapsed) setCollapsed(false);
    toggleMaximizePanel(panel.id);
  }

  return (
    <section
      className={
        "graph-frame" +
        (collapsed ? " graph-frame--collapsed" : "") +
        (isMaximized ? " graph-frame--maximized" : "")
      }
    >
      <div className="graph-frame__query-bar">
        <div className="graph-frame__query-text">
          <span className="graph-frame__prompt">trino$</span>
          <span className="graph-frame__cypher">{panel.sql}</span>
        </div>
        <div className="graph-frame__query-actions">
          <button
            type="button"
            className="graph-frame__icon-btn"
            title={collapsed ? "結果を表示" : "結果を折りたたむ"}
            aria-label={collapsed ? "結果を表示" : "結果を折りたたむ"}
            onClick={() => setCollapsed((v) => !v)}
          >
            <IconChevronToggle expanded={!collapsed} className="graph-frame__icon-svg" />
          </button>
          <button
            type="button"
            className={
              "graph-frame__icon-btn" +
              (isMaximized ? " graph-frame__icon-btn--active" : "")
            }
            title={isMaximized ? "全画面を解除" : "全画面表示"}
            aria-label={isMaximized ? "全画面を解除" : "全画面表示"}
            onClick={onToggleMaximize}
          >
            <IconMaximize active={isMaximized} />
          </button>
          <button
            type="button"
            className="graph-frame__icon-btn graph-frame__icon-btn--close"
            title="結果パネルを削除"
            aria-label="結果パネルを削除"
            onClick={() => removePanel(panel.id)}
          >
            ×
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="graph-frame__body">
          {panel.status === "loading" && (
            <p className="graph-frame__status">Running…</p>
          )}
          {panel.status === "error" && (
            <p className="graph-frame__error">{panel.error ?? "Query failed"}</p>
          )}
          {panel.status === "ready" && panel.data && (
            <>
              <div className="graph-frame__table-panel">
                <QueryResultTable data={panel.data} />
              </div>
              <footer className="graph-frame__footer">
                Fetched {recordCount} records
                {panel.data.truncated ? " (truncated)" : ""}
              </footer>
            </>
          )}
        </div>
      )}
    </section>
  );
}
