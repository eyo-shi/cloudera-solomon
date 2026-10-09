/**
 * Neo4j Browser 風の 1 クエリ結果フレーム。
 * 各フレーム上部に発行クエリを表示し、その下に Graph / Table / Raw 結果を載せる。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { labelColor } from "../../../graph/colors";
import {
  type GraphPanelView,
  type GraphResultPanel as GraphResultPanelState,
  useGraphStore,
} from "../../../stores/graphStore";
import type { GraphNodeDTO } from "../../../types";
import { IconChevronToggle } from "../../TreePane/ExplorerIcons";
import { GraphCanvas, type GraphCanvasHandle, type GraphSelection } from "./GraphCanvas";
import { GraphCanvasTopbar } from "./GraphCanvasTopbar";

export type { GraphPanelView };

interface Props {
  panel: GraphResultPanelState;
  isMaximized?: boolean;
}

function IconMaximize({ active }: { active?: boolean }) {
  return (
    <svg className="graph-frame__icon-svg" viewBox="0 0 16 16" aria-hidden="true">
      {active ? (
        <>
          <path
            d="M10 2h4v4M14 2 9 7M6 14H2v-4M2 14l5-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      ) : (
        <>
          <path
            d="M6 2h4v4M10 2 5 7M10 14H6v-4M6 14l5-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      )}
    </svg>
  );
}

const ALL_VIEWS: GraphPanelView[] = ["graph", "table", "raw"];
const TABLE_VIEWS: GraphPanelView[] = ["table", "raw"];

function resolveViewModes(panel: GraphResultPanelState): GraphPanelView[] {
  if (panel.allowedViews?.length) return panel.allowedViews;
  if (panel.queryType === "property" || panel.data?.query_type === "property") {
    return TABLE_VIEWS;
  }
  return ALL_VIEWS;
}

function initialView(
  panel: GraphResultPanelState,
  viewModes: GraphPanelView[],
): GraphPanelView {
  if (viewModes.includes(panel.defaultView)) return panel.defaultView;
  return viewModes[0] ?? "table";
}

const VIEW_LABELS: Record<GraphPanelView, string> = {
  graph: "Graph",
  table: "Table",
  raw: "Raw",
};

function ViewTabs({
  viewModes,
  view,
  onChange,
  placement,
}: {
  viewModes: GraphPanelView[];
  view: GraphPanelView;
  onChange: (mode: GraphPanelView) => void;
  placement: "overlay" | "inline";
}) {
  return (
    <div
      className={
        "graph-frame__view-bar" +
        (placement === "overlay"
          ? " graph-frame__view-bar--overlay"
          : " graph-frame__view-bar--inline")
      }
    >
      <div className="graph-frame__views" role="tablist">
        {viewModes.map((mode) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={view === mode}
            className={
              "graph-frame__view-btn" +
              (view === mode ? " graph-frame__view-btn--active" : "")
            }
            onClick={() => onChange(mode)}
          >
            {VIEW_LABELS[mode]}
          </button>
        ))}
      </div>
    </div>
  );
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

function formatDetailValue(value: unknown): string {
  if (typeof value === "string") return `"${value}"`;
  if (value === null || value === undefined) return "null";
  return JSON.stringify(value);
}

function detailRows(
  id: string,
  properties: Record<string, unknown>,
): Array<{ key: string; value: string }> {
  const rows: Array<{ key: string; value: string }> = [
    { key: "<id>", value: id },
  ];
  for (const [key, value] of Object.entries(properties)) {
    if (key === "id") continue;
    rows.push({ key, value: formatDetailValue(value) });
  }
  return rows;
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* ignore */
  }
}

function IconCopy() {
  return (
    <svg className="graph-detail-sidebar__copy-icon" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="5" y="5" width="8" height="8" rx="1" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <path d="M4 11V3.5A.5.5 0 0 1 4.5 3H11" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  );
}

function GraphResultSidebar({
  selection,
  labelCounts,
  relCounts,
  nodeTotal,
  edgeTotal,
}: {
  selection: GraphSelection | null;
  labelCounts: Array<{ label: string; count: number }>;
  relCounts: Array<{ type: string; count: number }>;
  nodeTotal: number;
  edgeTotal: number;
}) {
  if (!selection) {
    return (
      <aside className="graph-result-sidebar">
        <h4 className="graph-result-sidebar__title">Results overview</h4>
        <div className="graph-result-overview__section">
          <div className="graph-result-overview__label">Nodes ({nodeTotal})</div>
          <div className="graph-result-overview__chips">
            <span className="graph-chip graph-chip--wildcard">* ({nodeTotal})</span>
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
        {edgeTotal > 0 && (
          <div className="graph-result-overview__section">
            <div className="graph-result-overview__label">
              Relationships ({edgeTotal})
            </div>
            <div className="graph-result-overview__chips">
              <span className="graph-chip graph-chip--rel">* ({edgeTotal})</span>
              {relCounts.map(({ type, count }) => (
                <span key={type} className="graph-chip graph-chip--rel">
                  {type} ({count})
                </span>
              ))}
            </div>
          </div>
        )}
      </aside>
    );
  }

  const isNode = selection.kind === "node";
  const title = isNode ? "Node details" : "Relationship details";
  const rows = detailRows(selection.id, selection.properties);
  const allText = rows.map((r) => `${r.key}: ${r.value}`).join("\n");
  const primaryLabel =
    String(selection.extra?.primaryLabel ?? selection.extra?.labels ?? "Node")
      .split(",")[0]
      .trim() || "Node";
  const relType = String(selection.extra?.relType ?? selection.label);

  return (
    <aside className="graph-result-sidebar graph-result-sidebar--detail">
      <div className="graph-detail-sidebar__head">
        <h4 className="graph-result-sidebar__title">{title}</h4>
        <button
          type="button"
          className="graph-detail-sidebar__copy-all"
          title="Copy all"
          aria-label="Copy all"
          onClick={() => void copyText(allText)}
        >
          <IconCopy />
        </button>
      </div>
      {isNode ? (
        <span
          className="graph-chip graph-chip--node graph-detail-sidebar__chip"
          style={{ backgroundColor: labelColor(primaryLabel) }}
        >
          {primaryLabel}
        </span>
      ) : (
        <span className="graph-chip graph-chip--rel graph-detail-sidebar__chip">
          {relType}
        </span>
      )}
      <table className="graph-detail-kv-table">
        <thead>
          <tr>
            <th>Key</th>
            <th>Value</th>
            <th className="graph-detail-kv-table__actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td className="graph-detail-kv-table__key">{row.key}</td>
              <td className="graph-detail-kv-table__value">
                <code>{row.value}</code>
              </td>
              <td className="graph-detail-kv-table__actions">
                <button
                  type="button"
                  className="graph-detail-sidebar__copy-row"
                  title="Copy key and value"
                  aria-label={`Copy ${row.key}: ${row.value}`}
                  onClick={() => void copyText(`${row.key}: ${row.value}`)}
                >
                  <IconCopy />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </aside>
  );
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

export function GraphResultPanel({ panel, isMaximized = false }: Props) {
  const removePanel = useGraphStore((s) => s.removePanel);
  const toggleMaximizePanel = useGraphStore((s) => s.toggleMaximizePanel);
  const expandNeighborhoodInPanel = useGraphStore(
    (s) => s.expandNeighborhoodInPanel,
  );
  const viewModes = useMemo(() => resolveViewModes(panel), [
    panel.allowedViews,
    panel.queryType,
    panel.data?.query_type,
  ]);
  const [view, setView] = useState<GraphPanelView>(() =>
    initialView(panel, resolveViewModes(panel)),
  );
  const [collapsed, setCollapsed] = useState(false);
  const [graphSelection, setGraphSelection] = useState<GraphSelection | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const canvasRef = useRef<GraphCanvasHandle>(null);

  useEffect(() => {
    if (!viewModes.includes(view)) {
      setView(viewModes[0] ?? "table");
    }
  }, [view, viewModes]);

  useEffect(() => {
    if (view !== "graph") {
      setGraphSelection(null);
      setSearchOpen(false);
      setSearchQuery("");
      setDownloadMenuOpen(false);
    }
  }, [view]);

  const data = panel.data;
  const nodes = data?.graph.nodes ?? [];
  const edges = data?.graph.edges ?? [];
  const labelCounts = useMemo(() => countByLabel(nodes), [nodes]);
  const relCounts = useMemo(() => countByRelType(edges), [edges]);

  const propertyKey = useMemo(() => {
    const isProperty =
      panel.queryType === "property" || panel.data?.query_type === "property";
    if (!isProperty) return undefined;
    const match =
      panel.cypher.match(/n\.([A-Za-z_][A-Za-z0-9_]*) AS/) ??
      panel.sidebarSpec?.property_key?.match(/^([A-Za-z_][A-Za-z0-9_]*)$/);
    return match?.[1];
  }, [panel.cypher, panel.data?.query_type, panel.queryType, panel.sidebarSpec?.property_key]);

  const isPropertyResult =
    panel.queryType === "property" || panel.data?.query_type === "property";

  const tableData = useMemo(() => {
    if (isPropertyResult) {
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
  }, [nodes, propertyKey, isPropertyResult]);

  const recordCount =
    view === "table"
      ? tableData.rows.length
      : edges.length > 0
        ? edges.length
        : nodes.length;

  function onToggleCollapse() {
    setCollapsed((v) => !v);
  }

  function onToggleMaximize(e: React.MouseEvent) {
    e.stopPropagation();
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
          <span className="graph-frame__prompt">neo4j$</span>
          <span className="graph-frame__cypher">{panel.cypher}</span>
        </div>
        <div className="graph-frame__query-actions">
          <button
            type="button"
            className="graph-frame__icon-btn"
            title={collapsed ? "結果を表示" : "結果を折りたたむ"}
            aria-label={collapsed ? "結果を表示" : "結果を折りたたむ"}
            onClick={onToggleCollapse}
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

          {panel.status === "ready" && data && (
            <>
              {view === "graph" && (
                <div
                  className={
                    "graph-frame__split" +
                    (!sidebarOpen ? " graph-frame__split--no-sidebar" : "")
                  }
                >
                  <div className="graph-frame__main">
                    <ViewTabs
                      viewModes={viewModes}
                      view={view}
                      onChange={setView}
                      placement="overlay"
                    />
                    <GraphCanvasTopbar
                      searchOpen={searchOpen}
                      searchQuery={searchQuery}
                      sidebarOpen={sidebarOpen}
                      downloadMenuOpen={downloadMenuOpen}
                      canvasRef={canvasRef}
                      onSearchOpenChange={setSearchOpen}
                      onSearchQueryChange={setSearchQuery}
                      onSidebarOpenChange={setSidebarOpen}
                      onDownloadMenuOpenChange={setDownloadMenuOpen}
                    />
                    {nodes.length === 0 ? (
                      <p className="graph-frame__status">No graph results</p>
                    ) : (
                      <GraphCanvas
                        ref={canvasRef}
                        nodes={nodes}
                        edges={edges}
                        searchQuery={searchQuery}
                        fillHeight={isMaximized}
                        layoutRevision={
                          isMaximized
                            ? `maximized-${panel.id}`
                            : `normal-${panel.id}`
                        }
                        onSelectionChange={setGraphSelection}
                        onNodeClick={(nodeId) =>
                          expandNeighborhoodInPanel(panel.id, nodeId)
                        }
                      />
                    )}
                  </div>
                  {sidebarOpen && (
                    <GraphResultSidebar
                      selection={graphSelection}
                      labelCounts={labelCounts}
                      relCounts={relCounts}
                      nodeTotal={nodes.length}
                      edgeTotal={edges.length}
                    />
                  )}
                </div>
              )}

              {view === "table" && (
                <div className="graph-frame__table-panel">
                  <ViewTabs
                    viewModes={viewModes}
                    view={view}
                    onChange={setView}
                    placement="inline"
                  />
                  <div className="graph-frame__table-wrap">
                    <table className="graph-result-table">
                      <thead>
                        <tr>
                          <th className="graph-result-table__row-num" />
                          {tableData.columns.map((col) => (
                            <th key={col}>{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {tableData.rows.map((row, idx) => (
                          <tr key={idx}>
                            <td className="graph-result-table__row-num">{idx + 1}</td>
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
                </div>
              )}

              {view === "raw" && (
                <div className="graph-frame__raw-panel">
                  <ViewTabs
                    viewModes={viewModes}
                    view={view}
                    onChange={setView}
                    placement="inline"
                  />
                  <pre className="graph-frame__raw">
                    {JSON.stringify(data, null, 2)}
                  </pre>
                </div>
              )}

              <footer className="graph-frame__footer">
                Fetched {recordCount} records
              </footer>
            </>
          )}
        </div>
      )}
    </section>
  );
}
