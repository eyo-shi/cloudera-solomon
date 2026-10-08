/**
 * Cytoscape ベースの Graph 可視化。
 * 右下: Zoom in / Zoom out / Zoom to fit / Layout selector。
 */
import cytoscape, {
  type Core,
  type ElementDefinition,
  type LayoutOptions,
  type NodeSingular,
} from "cytoscape";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { primaryNodeColor } from "../../../graph/colors";
import type { GraphEdgeDTO, GraphNodeDTO } from "../../../types";
import { attachDragPhysics } from "./graphDragPhysics";

type GraphLayoutMode = "force" | "hierarchical";

const NODE_FONT_SIZE = 10;
/** Neo4j Browser 風の固定ノード直径 (px)。 */
const NODE_DIAMETER = 56;
/** 円内に収めるラベルの最大幅 (px, 10px フォント)。 */
const NODE_LABEL_MAX_WIDTH = 44;

function measureLabelWidth(label: string): number {
  if (typeof document === "undefined") {
    return label.length * NODE_FONT_SIZE * 0.6;
  }
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return label.length * NODE_FONT_SIZE * 0.6;
  ctx.font = `${NODE_FONT_SIZE}px Helvetica, Arial, sans-serif`;
  return ctx.measureText(label).width;
}

/** Neo4j Browser 同様、長い名前は 1 行で ``...`` 省略する。 */
function ellipsizeNodeLabel(label: string, maxWidth: number): string {
  const text = label.trim();
  if (!text || measureLabelWidth(text) <= maxWidth) return text;
  const ellipsis = "...";
  let end = text.length;
  while (end > 0) {
    const candidate = text.slice(0, end).trimEnd() + ellipsis;
    if (measureLabelWidth(candidate) <= maxWidth) return candidate;
    end -= 1;
  }
  return ellipsis;
}

function toElements(
  nodes: GraphNodeDTO[],
  edges: GraphEdgeDTO[],
): ElementDefinition[] {
  const nodeEls: ElementDefinition[] = nodes.map((n) => ({
    data: {
      id: n.id,
      label: ellipsizeNodeLabel(n.caption, NODE_LABEL_MAX_WIDTH),
      fullLabel: n.caption,
      labels: n.labels.join(", "),
      primaryLabel: n.labels[0] ?? "Node",
      color: primaryNodeColor(n.labels),
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

interface LayoutGraphShape {
  nodeCount: number;
  edgeCount: number;
}

/** ラベル選択などエッジなし結果は Neo4j Browser 同様に円状配置する。 */
function layoutOptions(
  mode: GraphLayoutMode,
  graph: LayoutGraphShape,
  animate = true,
): LayoutOptions {
  const duration = animate ? 250 : 0;
  if (graph.edgeCount === 0 && graph.nodeCount > 0) {
    return {
      name: "circle",
      animate,
      animationDuration: duration,
      padding: 40,
      avoidOverlap: true,
      spacingFactor: 1.35,
      startAngle: (3 / 2) * Math.PI,
      clockwise: true,
    };
  }
  if (mode === "hierarchical") {
    return {
      name: "breadthfirst",
      animate,
      animationDuration: duration,
      padding: 30,
      directed: true,
      spacingFactor: 1.2,
    };
  }
  return {
    name: "cose",
    animate,
    animationDuration: duration,
    padding: 30,
    nodeRepulsion: 8000,
    idealEdgeLength: 120,
    edgeElasticity: 100,
    randomize: true,
  };
}

export interface GraphSelection {
  kind: "node" | "edge";
  id: string;
  label: string;
  properties: Record<string, unknown>;
  extra?: Record<string, unknown>;
}

export interface GraphCanvasHandle {
  downloadPng: () => void;
  downloadSvg: () => void;
}

interface GraphCanvasProps {
  nodes: GraphNodeDTO[];
  edges: GraphEdgeDTO[];
  searchQuery?: string;
  /** 全画面表示などコンテナサイズが変わったときに Cytoscape を再レイアウトする */
  layoutRevision?: string;
  onSelectionChange?: (selection: GraphSelection | null) => void;
}

function nodeMatchesSearch(node: NodeSingular, query: string): boolean {
  const q = query.toLowerCase();
  const label = String(node.data("label") ?? "").toLowerCase();
  const fullLabel = String(node.data("fullLabel") ?? label).toLowerCase();
  const id = String(node.id()).toLowerCase();
  const labels = String(node.data("labels") ?? "").toLowerCase();
  if (label.includes(q) || fullLabel.includes(q) || id.includes(q) || labels.includes(q)) {
    return true;
  }
  const props = node.data("properties") as Record<string, unknown> | undefined;
  if (props) {
    for (const value of Object.values(props)) {
      if (String(value ?? "").toLowerCase().includes(q)) return true;
    }
  }
  return false;
}

function triggerDownload(filename: string, href: string) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.click();
  if (href.startsWith("blob:")) {
    URL.revokeObjectURL(href);
  }
}

function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function exportGraphPng(cy: Core) {
  const canvas = cy.container()?.querySelector("canvas");
  if (!(canvas instanceof HTMLCanvasElement)) return;
  triggerDownload("graph.png", canvas.toDataURL("image/png"));
}

function exportGraphSvg(cy: Core) {
  const w = cy.width();
  const h = cy.height();
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`,
    `<rect width="100%" height="100%" fill="#ffffff"/>`,
  ];
  cy.edges().forEach((edge) => {
    const src = edge.source().renderedPosition();
    const tgt = edge.target().renderedPosition();
    parts.push(
      `<line x1="${src.x}" y1="${src.y}" x2="${tgt.x}" y2="${tgt.y}" stroke="#94a3b8" stroke-width="2"/>`,
    );
  });
  cy.nodes().forEach((node) => {
    const bb = node.renderedBoundingBox({ includeLabels: false });
    const cx = (bb.x1 + bb.x2) / 2;
    const cy = (bb.y1 + bb.y2) / 2;
    const r = Math.max(bb.w, bb.h) / 2;
    const color = String(node.data("color") ?? "#64748b");
    const label = escapeXml(String(node.data("label") ?? ""));
    parts.push(
      `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${color}" stroke="#ffffff" stroke-width="2"/>`,
      `<text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="middle" fill="#000000" font-size="${NODE_FONT_SIZE}" font-family="sans-serif">${label}</text>`,
    );
  });
  parts.push("</svg>");
  const blob = new Blob([parts.join("")], { type: "image/svg+xml;charset=utf-8" });
  triggerDownload("graph.svg", URL.createObjectURL(blob));
}

function IconZoomIn() {
  return (
    <svg className="graph-canvas-controls__svg" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="6.5" cy="6.5" r="3.75" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <path d="M9.5 9.5 13 13" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
      <path d="M4.75 6.5h3.5M6.5 4.75v3.5" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}

function IconZoomOut() {
  return (
    <svg className="graph-canvas-controls__svg" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="6.5" cy="6.5" r="3.75" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <path d="M9.5 9.5 13 13" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
      <path d="M4.75 6.5h3.5" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}

function IconZoomFit() {
  return (
    <svg className="graph-canvas-controls__svg" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M2.5 5.5V2.5h3M10 2.5h3.5v3M13.5 10v3.5H10M6 13.5H2.5V10"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconForceLayout() {
  return (
    <svg className="graph-canvas-controls__svg" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="1.5" fill="currentColor" />
      <circle cx="8" cy="2.75" r="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <circle cx="3" cy="11.5" r="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <circle cx="13" cy="11.5" r="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <path
        d="M8 6.5V4M5.5 10 6.5 9M10.5 9 10 10"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconHierarchicalLayout() {
  return (
    <svg className="graph-canvas-controls__svg" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="3" r="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <circle cx="3.5" cy="12" r="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <circle cx="8" cy="12" r="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <circle cx="12.5" cy="12" r="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <path
        d="M8 4.25v3.5M8 7.75 3.5 10.75M8 7.75l4.5 3"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinecap="round"
      />
    </svg>
  );
}

const LAYOUT_ITEMS: Array<{
  mode: GraphLayoutMode;
  label: string;
  Icon: () => JSX.Element;
}> = [
  { mode: "force", label: "Force-based layout", Icon: IconForceLayout },
  { mode: "hierarchical", label: "Hierarchical layout", Icon: IconHierarchicalLayout },
];

export const GraphCanvas = forwardRef<GraphCanvasHandle, GraphCanvasProps>(
  function GraphCanvas(
    { nodes, edges, searchQuery = "", layoutRevision, onSelectionChange },
    ref,
  ) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const layoutMenuRef = useRef<HTMLDivElement>(null);
  const layoutModeRef = useRef<GraphLayoutMode>("force");
  const onSelectionChangeRef = useRef(onSelectionChange);
  const [layoutMode, setLayoutMode] = useState<GraphLayoutMode>("force");
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);

  layoutModeRef.current = layoutMode;
  onSelectionChangeRef.current = onSelectionChange;

  useImperativeHandle(ref, () => ({
    downloadPng: () => {
      const cy = cyRef.current;
      if (cy) exportGraphPng(cy);
    },
    downloadSvg: () => {
      const cy = cyRef.current;
      if (cy) exportGraphSvg(cy);
    },
  }));

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const q = searchQuery.trim();
    if (!q) {
      cy.nodes().style("opacity", 1);
      cy.edges().style("opacity", 1);
      return;
    }
    cy.nodes().forEach((node) => {
      node.style("opacity", nodeMatchesSearch(node, q) ? 1 : 0.12);
    });
    cy.edges().forEach((edge) => {
      const srcOpacity = edge.source().style("opacity");
      const tgtOpacity = edge.target().style("opacity");
      const visible =
        (typeof srcOpacity === "number" ? srcOpacity : 1) > 0.5 &&
        (typeof tgtOpacity === "number" ? tgtOpacity : 1) > 0.5;
      edge.style("opacity", visible ? 1 : 0.08);
    });
  }, [searchQuery, nodes, edges]);

  useEffect(() => {
    if (!layoutMenuOpen) return;
    function onPointerDown(e: MouseEvent) {
      if (!layoutMenuRef.current?.contains(e.target as Node)) {
        setLayoutMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [layoutMenuOpen]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const frame = requestAnimationFrame(() => {
      cy.resize();
      cy.fit(undefined, 40);
    });
    return () => cancelAnimationFrame(frame);
  }, [layoutRevision]);

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
            "font-size": `${NODE_FONT_SIZE}px`,
            "text-wrap": "none",
            "text-overflow-wrap": "whitespace",
            width: `${NODE_DIAMETER}px`,
            height: `${NODE_DIAMETER}px`,
            shape: "ellipse",
            "background-color": "data(color)",
            color: "#000000",
            "border-width": "2px",
            "border-color": "#fff",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": "#fbbf24",
            "border-width": "3px",
          },
        },
        {
          selector: "edge",
          style: {
            label: "data(label)",
            "font-size": "9px",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            width: "2px",
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            color: "#64748b",
            "text-background-color": "#fff",
            "text-background-opacity": 0.85,
            "text-background-padding": "2px",
          },
        },
        {
          selector: "edge:selected",
          style: {
            "line-color": "#f59e0b",
            "target-arrow-color": "#f59e0b",
            width: "3px",
          },
        },
      ],
      layout: layoutOptions(
        layoutModeRef.current,
        { nodeCount: nodes.length, edgeCount: edges.length },
        false,
      ),
      wheelSensitivity: 0.2,
      autoungrabify: false,
    });

    const detachDragPhysics = attachDragPhysics(cy);

    cy.on("tap", "node", (evt) => {
      const d = evt.target.data();
      evt.target.select();
      onSelectionChangeRef.current?.({
        kind: "node",
        id: d.id,
        label: d.fullLabel ?? d.label,
        properties: d.properties ?? {},
        extra: { primaryLabel: d.primaryLabel, labels: d.labels },
      });
    });
    cy.on("tap", "edge", (evt) => {
      const d = evt.target.data();
      evt.target.select();
      onSelectionChangeRef.current?.({
        kind: "edge",
        id: d.id,
        label: d.label,
        properties: d.properties ?? {},
        extra: { source: d.source, target: d.target, relType: d.label },
      });
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        cy.$(":selected").unselect();
        onSelectionChangeRef.current?.(null);
      }
    });

    cy.fit(undefined, 40);
    cyRef.current = cy;

    const container = containerRef.current;
    const resizeObserver =
      typeof ResizeObserver !== "undefined" && container
        ? new ResizeObserver(() => {
            cy.resize();
          })
        : null;
    resizeObserver?.observe(container);

    return () => {
      resizeObserver?.disconnect();
      detachDragPhysics();
      onSelectionChangeRef.current?.(null);
      cy.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges]);

  function zoomBy(factor: number) {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({
      level: cy.zoom() * factor,
      renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
    });
  }

  function zoomToFit() {
    cyRef.current?.fit(undefined, 40);
  }

  function applyLayout(mode: GraphLayoutMode) {
    const cy = cyRef.current;
    if (!cy) return;
    setLayoutMode(mode);
    cy.layout(
      layoutOptions(mode, { nodeCount: nodes.length, edgeCount: edges.length }),
    ).run();
  }

  const activeLayout = LAYOUT_ITEMS.find((item) => item.mode === layoutMode)!;

  return (
    <div className="graph-canvas-wrap">
      <div ref={containerRef} className="graph-canvas" />
      <div className="graph-canvas-controls" ref={layoutMenuRef}>
        <button
          type="button"
          className="graph-canvas-controls__btn"
          title="Zoom in"
          aria-label="Zoom in"
          onClick={() => zoomBy(1.25)}
        >
          <IconZoomIn />
        </button>
        <button
          type="button"
          className="graph-canvas-controls__btn"
          title="Zoom out"
          aria-label="Zoom out"
          onClick={() => zoomBy(0.8)}
        >
          <IconZoomOut />
        </button>
        <span className="graph-canvas-controls__divider" aria-hidden="true" />
        <button
          type="button"
          className="graph-canvas-controls__btn"
          title="Zoom to fit"
          aria-label="Zoom to fit"
          onClick={zoomToFit}
        >
          <IconZoomFit />
        </button>
        <span className="graph-canvas-controls__divider" aria-hidden="true" />
        <div className="graph-canvas-controls__layout">
          <button
            type="button"
            className="graph-canvas-controls__btn graph-canvas-controls__btn--layout"
            title="Layout"
            aria-label="Layout"
            aria-expanded={layoutMenuOpen}
            onClick={() => setLayoutMenuOpen((open) => !open)}
          >
            <activeLayout.Icon />
            <span className="graph-canvas-controls__chevron" aria-hidden="true">
              ▾
            </span>
          </button>
          {layoutMenuOpen && (
            <div className="graph-canvas-layout-menu" role="menu">
              {LAYOUT_ITEMS.map(({ mode, label, Icon }) => (
                <button
                  key={mode}
                  type="button"
                  role="menuitemradio"
                  aria-checked={layoutMode === mode}
                  className={
                    "graph-canvas-layout-menu__item" +
                    (layoutMode === mode ? " graph-canvas-layout-menu__item--active" : "")
                  }
                  onClick={() => {
                    applyLayout(mode);
                    setLayoutMenuOpen(false);
                  }}
                >
                  <span className="graph-canvas-layout-menu__check" aria-hidden="true">
                    {layoutMode === mode ? "✓" : ""}
                  </span>
                  <Icon />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
