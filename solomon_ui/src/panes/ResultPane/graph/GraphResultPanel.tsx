/**
 * Neo4j Browser 風の 1 クエリ結果フレーム (Graph / Table / Raw + Results overview)。
 */
import { useMemo, useState } from "react";
import { labelColor } from "../../../graph/colors";
import type { GraphNodeDTO, GraphQueryResponse } from "../../../types";
import { GraphCanvas } from "./GraphCanvas";

export type GraphPanelView = "graph" | "table" | "raw";

interface Props {
  panel: {
    id: string;
    cypher: string;
    status: "loading" | "ready" | "error";
    error?: string;
    data?: GraphQueryResponse;
    defaultView: GraphPanelView;
  };
  onExploreNeighborhood?: (nodeId: string) => void;
}

function countByLabel(nodes: GraphNodeDTO[]): Array<{ label: string; count: number }> {
  const counts = new Map<string, number>();
  for (const node of nodes) {
    const primary = node.labels[0] ?? "Node";
    counts.set(primary, (counts.get(primary) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

function countByRelType(edges: { type: string }[]): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  for (const edge of edges) {
    counts.set(edge.type, (counts.get(edge.type) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => a.type.localeCompare(b.type));
}

function propertyTableFromGraph(
  nodes: GraphNodeDTO[],
  propertyKey?: string,
): { columns: string[]; rows: Record<string, string>[] } {
  const key = propertyKey ?? "value";
  const columns = ["entity", key];
  const rows = nodes.map((node) => ({
    entity: `"${node.labels[0] ?? "node"}"`,
    [key]: JSON.stringify(node.properties[key] ?? node.properties.name ?? null),
  }));
  return { columns, rows };
}

export function GraphResultPanel({ panel, onExploreNeighborhood }: Props) {
  const [view, setView] = useState<GraphPanelView>(panel.defaultView);

  const data = panel.data;
  const nodes = data?.graph.nodes ?? [];
  const edges = data?.graph.edges ?? [];
  const labelCounts = useMemo(() => countByLabel(nodes), [nodes]);
  const relCounts = useMemo(() => countByRelType(edges), [edges]);

  const propertyKey = useMemo(() => {
    if (panel.data?.query_type !== "property") return undefined;
    const match = panel.cypher.match(/n\.([A-Za-z_][A-Za-z0-9_]*) AS/);
    return match?.[1];
  }, [panel.cypher, panel.data?.query_type]);

  const tableData = useMemo(() => {
    if (panel.defaultView === "table" || panel.data?.query_type === "property") {
      return propertyTableFromGraph(nodes, propertyKey);
    }
    return {
      columns: ["labels", "caption", "id"],
      rows: nodes.map(
        (node): Record<string, string> => ({
          labels: JSON.stringify(node.labels),
          caption: JSON.stringify(node.caption),
          id: JSON.stringify(node.id),
        }),
      ),
    };
  }, [nodes, propertyKey, panel.defaultView, panel.data?.query_type]);

  const recordCount =
    view === "table" && panel.defaultView === "table"
      ? tableData.rows.length
      : edges.length > 0
        ? edges.length
        : nodes.length;

  return (
    <section className="graph-result-panel">
      <div className="graph-result-panel__toolbar">
        <div className="graph-result-panel__views">
          {(panel.defaultView === "table"
            ? (["table", "raw"] as const)
            : (["graph", "table", "raw"] as const)
          ).map((mode) => (
            <button
              key={mode}
              type="button"
              className={
                "graph-result-panel__view-btn" +
                (view === mode ? " graph-result-panel__view-btn--active" : "")
              }
              onClick={() => setView(mode)}
            >
              {mode === "graph" ? "Graph" : mode === "table" ? "Table" : "Raw"}
            </button>
          ))}
        </div>
      </div>

      {panel.status === "loading" && (
        <p className="graph-result-panel__status">Running…</p>
      )}
      {panel.status === "error" && (
        <p className="graph-result-panel__error">{panel.error ?? "Query failed"}</p>
      )}

      {panel.status === "ready" && data && view === "graph" && (
        <div className="graph-result-panel__body">
          <div className="graph-result-panel__main">
            {nodes.length === 0 ? (
              <p className="graph-result-panel__status">No graph results</p>
            ) : (
              <GraphCanvas
                nodes={nodes}
                edges={edges}
                onExploreNeighborhood={onExploreNeighborhood}
              />
            )}
          </div>
          <aside className="graph-result-overview">
            <h4 className="graph-result-overview__title">Results overview</h4>
            <div className="graph-result-overview__section">
              <div className="graph-result-overview__label">
                Nodes ({nodes.length})
              </div>
              <div className="graph-result-overview__chips">
                <span className="graph-chip graph-chip--wildcard">
                  * ({nodes.length})
                </span>
                {labelCounts.map(({ label, count }) => (
                  <span
                    key={label}
                    className="graph-chip graph-chip--node"
                    style={{ backgroundColor: labelColor(label) }}
                  >
                    {label} ({count})
                  </span>
                ))}
              </div>
            </div>
            {edges.length > 0 && (
              <div className="graph-result-overview__section">
                <div className="graph-result-overview__label">
                  Relationships ({edges.length})
                </div>
                <div className="graph-result-overview__chips">
                  <span className="graph-chip graph-chip--rel">
                    * ({edges.length})
                  </span>
                  {relCounts.map(({ type, count }) => (
                    <span key={type} className="graph-chip graph-chip--rel">
                      {type} ({count})
                    </span>
                  ))}
                </div>
              </div>
            )}
          </aside>
        </div>
      )}

      {panel.status === "ready" && data && view === "table" && (
        <div className="graph-result-panel__table-wrap">
          <table className="graph-result-table">
            <thead>
              <tr>
                {tableData.columns.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableData.rows.map((row, idx) => (
                <tr key={idx}>
                  {tableData.columns.map((col) => (
                    <td key={col}>
                      <code>{row[col] ?? ""}</code>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {panel.status === "ready" && data && view === "raw" && (
        <pre className="graph-result-panel__raw">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}

      {panel.status === "ready" && (
        <footer className="graph-result-panel__footer">
          Fetched {recordCount} records
        </footer>
      )}
    </section>
  );
}
