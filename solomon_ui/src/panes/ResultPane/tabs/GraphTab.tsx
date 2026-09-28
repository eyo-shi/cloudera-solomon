/**
 * Graph ワークスペース — 固定クエリバー + 結果スタック (Neo4j Browser 風)。
 */
import { type FormEvent, useRef, useEffect } from "react";
import { useGraphStore } from "../../../stores/graphStore";
import { GraphResultPanel } from "../graph/GraphResultPanel";

export function GraphTab() {
  const queryInput = useGraphStore((s) => s.queryInput);
  const panels = useGraphStore((s) => s.panels);
  const setQueryInput = useGraphStore((s) => s.setQueryInput);
  const runQueryInput = useGraphStore((s) => s.runQueryInput);
  const appendNeighborhood = useGraphStore((s) => s.appendNeighborhood);
  const stackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (panels.length === 0) return;
    stackRef.current?.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [panels.length]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    runQueryInput();
  }

  return (
    <div className="tab-content tab-content--graph tab-content--graph-workspace">
      <form className="graph-query-bar" onSubmit={onSubmit}>
        <span className="graph-query-bar__prompt">neo4j$</span>
        <input
          className="graph-query-bar__input"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="MATCH (n) RETURN n LIMIT 25;"
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

      <div className="graph-results-stack" ref={stackRef}>
        {panels.length === 0 && (
          <p className="graph-results-empty">
            左ペインの Node / Relationship / Property key をクリックするか、
            上のクエリを入力して実行してください。
          </p>
        )}
        {panels.map((panel) => (
          <GraphResultPanel
            key={panel.id}
            panel={panel}
            onExploreNeighborhood={appendNeighborhood}
          />
        ))}
      </div>
    </div>
  );
}
