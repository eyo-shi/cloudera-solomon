/**
 * Tables ワークスペース — 固定 SQL バー + 結果スタック (Graph タブと同型)。
 */
import { type FormEvent, useEffect, useRef } from "react";
import { useTablesStore } from "../../../stores/tablesStore";
import { TablesResultPanel } from "../tables/TablesResultPanel";

export function TablesTab() {
  const queryInput = useTablesStore((s) => s.queryInput);
  const panels = useTablesStore((s) => s.panels);
  const setQueryInput = useTablesStore((s) => s.setQueryInput);
  const runQueryInput = useTablesStore((s) => s.runQueryInput);
  const maximizedPanelId = useTablesStore((s) => s.maximizedPanelId);
  const stackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stack = stackRef.current;
    if (!stack || panels.length === 0) return;
    stack.scrollTo({ top: 0, behavior: "smooth" });
  }, [panels.length]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    runQueryInput();
  }

  return (
    <div className="tab-content tab-content--flush tab-content--graph tab-content--graph-workspace">
      <form className="graph-query-bar" onSubmit={onSubmit}>
        <span className="graph-query-bar__prompt">trino$</span>
        <input
          className="graph-query-bar__input"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder='SELECT * FROM "iceberg"."demo"."orders" LIMIT 100;'
          spellCheck={false}
        />
        <button
          type="submit"
          className="graph-query-bar__run"
          aria-label="Run query"
          title="Run query"
        >
          ▶
        </button>
      </form>

      <div
        className={
          "graph-results-stack" +
          (maximizedPanelId ? " graph-results-stack--maximized" : "")
        }
        ref={stackRef}
      >
        {panels.length === 0 && (
          <p className="graph-results-empty">
            左ペインのテーブルをクリックするか、上の SQL を入力して実行してください。
          </p>
        )}
        {panels.map((panel) => {
          if (maximizedPanelId && panel.id !== maximizedPanelId) return null;
          return (
            <TablesResultPanel
              key={panel.id}
              panel={panel}
              isMaximized={maximizedPanelId === panel.id}
            />
          );
        })}
      </div>
    </div>
  );
}
