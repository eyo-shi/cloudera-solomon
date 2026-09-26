/**
 * Cytoscape ベースの Graph 可視化。
 * Zoom / Pan / Fit / Reset、Node/Edge クリック、Neighborhood 探索。
 */
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useRef, useState } from "react";
import type { GraphEdgeDTO, GraphNodeDTO } from "../../../types";

const LABEL_COLORS: Record<string, string> = {
  System: "#2563eb",
  Dataset: "#059669",
  Column: "#7c3aed",
  Document: "#d97706",
  SourceFile: "#64748b",
  Schema: "#0891b2",
  MetadataEntry: "#be185d",
};

function nodeColor(labels: string[]): string {
  for (const label of labels) {
    if (LABEL_COLORS[label]) return LABEL_COLORS[label];
  }
  return "#475569";
}

function toElements(
  nodes: GraphNodeDTO[],
  edges: GraphEdgeDTO[],
): ElementDefinition[] {
  const nodeEls: ElementDefinition[] = nodes.map((n) => ({
    data: {
      id: n.id,
      label: n.caption,
      labels: n.labels.join(", "),
      primaryLabel: n.labels[0] ?? "Node",
      color: nodeColor(n.labels),
      properties: n.properties,
    },
  }));
  const edgeEls: ElementDefinition[] = edges.map((e) => ({
    data: {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.type,
      properties: e.properties,
    },
  }));
  return [...nodeEls, ...edgeEls];
}

export interface GraphSelection {
  kind: "node" | "edge";
  id: string;
  label: string;
  properties: Record<string, unknown>;
  extra?: Record<string, unknown>;
}

interface GraphCanvasProps {
  nodes: GraphNodeDTO[];
  edges: GraphEdgeDTO[];
  onExploreNeighborhood?: (nodeId: string) => void;
}

export function GraphCanvas({
  nodes,
  edges,
  onExploreNeighborhood,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [selection, setSelection] = useState<GraphSelection | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: toElements(nodes, edges),
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": 10,
            "text-wrap": "wrap",
            "text-max-width": 80,
            width: 56,
            height: 56,
            "background-color": "data(color)",
            color: "#fff",
            "border-width": 2,
            "border-color": "#fff",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": "#fbbf24",
            "border-width": 3,
          },
        },
        {
          selector: "edge",
          style: {
            label: "data(label)",
            "font-size": 9,
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            width: 2,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            color: "#64748b",
            "text-background-color": "#fff",
            "text-background-opacity": 0.85,
            "text-background-padding": 2,
          },
        },
        {
          selector: "edge:selected",
          style: {
            "line-color": "#f59e0b",
            "target-arrow-color": "#f59e0b",
            width: 3,
          },
        },
      ],
      layout: { name: "cose", animate: false, padding: 30 },
      wheelSensitivity: 0.2,
    });

    cy.on("tap", "node", (evt) => {
      const d = evt.target.data();
      setSelection({
        kind: "node",
        id: d.id,
        label: d.label,
        properties: d.properties ?? {},
        extra: { labels: d.labels },
      });
    });
    cy.on("tap", "edge", (evt) => {
      const d = evt.target.data();
      setSelection({
        kind: "edge",
        id: d.id,
        label: d.label,
        properties: d.properties ?? {},
        extra: { source: d.source, target: d.target },
      });
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelection(null);
    });

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges]);

  function fit() {
    cyRef.current?.fit(undefined, 40);
  }
  function reset() {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().remove();
    cy.add(toElements(nodes, edges));
    cy.layout({ name: "cose", animate: false, padding: 30 }).run();
    cy.fit(undefined, 40);
    setSelection(null);
  }

  return (
    <div className="graph-canvas-wrap">
      <div className="graph-canvas-toolbar">
        <button type="button" className="graph-canvas-btn" onClick={fit}>
          Fit
        </button>
        <button type="button" className="graph-canvas-btn" onClick={reset}>
          Reset
        </button>
      </div>
      <div ref={containerRef} className="graph-canvas" />
      {selection && (
        <aside className="graph-detail-panel">
          <div className="graph-detail-panel__head">
            <strong>{selection.kind === "node" ? "Node" : "Relationship"}</strong>
            <button
              type="button"
              className="graph-detail-panel__close"
              onClick={() => setSelection(null)}
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <div className="graph-detail-panel__body">
            <div className="graph-detail-row">
              <span className="graph-detail-key">Label</span>
              <span>{selection.label}</span>
            </div>
            {selection.extra?.labels && (
              <div className="graph-detail-row">
                <span className="graph-detail-key">Labels</span>
                <span>{String(selection.extra.labels)}</span>
              </div>
            )}
            {selection.kind === "edge" && selection.extra && (
              <>
                <div className="graph-detail-row">
                  <span className="graph-detail-key">Source</span>
                  <code>{String(selection.extra.source)}</code>
                </div>
                <div className="graph-detail-row">
                  <span className="graph-detail-key">Target</span>
                  <code>{String(selection.extra.target)}</code>
                </div>
              </>
            )}
            <div className="graph-detail-props">
              <span className="graph-detail-key">Properties</span>
              <pre>{JSON.stringify(selection.properties, null, 2)}</pre>
            </div>
            {selection.kind === "node" && onExploreNeighborhood && (
              <button
                type="button"
                className="graph-explore-btn"
                onClick={() => onExploreNeighborhood(selection.id)}
              >
                関連 Graph を探索 (1-hop)
              </button>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
