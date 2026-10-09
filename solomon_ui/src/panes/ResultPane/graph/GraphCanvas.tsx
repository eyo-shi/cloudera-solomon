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

function nodeElement(n: GraphNodeDTO): ElementDefinition {
  return {
    data: {
      id: n.id,
      label: ellipsizeNodeLabel(n.caption, NODE_LABEL_MAX_WIDTH),
      fullLabel: n.caption,
      labels: n.labels.join(", "),
      primaryLabel: n.labels[0] ?? "Node",
      color: primaryNodeColor(n.labels),
      properties: n.properties,
    },
  };
}

function edgeElement(e: GraphEdgeDTO): ElementDefinition {
  return {
    data: {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.type,
      properties: e.properties,
    },
  };
}

const NEW_NODE_RING_RADIUS = 110;

/** 近傍展開など — 既存ノードは動かさず、追加ノードだけアンカー周りに配置する。 */
function layoutNewNodes(cy: Core, newNodeIds: string[]): void {
  if (newNodeIds.length === 0) return;
  const newSet = new Set(newNodeIds);
  const placed = new Set<string>();

  function anchoredNeighbors(id: string): NodeSingular[] {
    const node = cy.getElementById(id);
    if (node.empty()) return [];
    return node.neighborhood("node").filter((n) => {
      const nid = n.id();
      return nid !== id && (!newSet.has(nid) || placed.has(nid));
    }) as unknown as NodeSingular[];
  }

  let progress = true;
  let guard = 0;
  while (progress && guard++ < newNodeIds.length * 4) {
    progress = false;
    for (const id of newNodeIds) {
      if (placed.has(id)) continue;
      const anchors = anchoredNeighbors(id);
      if (anchors.length === 0) continue;

      const anchor = anchors[0];
      const ap = anchor.position();
      const peers = newNodeIds.filter(
        (nid) =>
          !placed.has(nid) &&
          anchoredNeighbors(nid).some((a) => a.id() === anchor.id()),
      );
      const idx = Math.max(0, peers.indexOf(id));
      const count = Math.max(peers.length, 1);
      const angle = (2 * Math.PI * idx) / count - Math.PI / 2;
      cy.getElementById(id).position({
        x: ap.x + NEW_NODE_RING_RADIUS * Math.cos(angle),
        y: ap.y + NEW_NODE_RING_RADIUS * Math.sin(angle),
      });
      placed.add(id);
      progress = true;
    }
  }

  for (const id of newNodeIds) {
    if (placed.has(id)) continue;
    const node = cy.getElementById(id);
    if (node.empty()) continue;
    const others = cy.nodes().not(node);
    if (others.length === 0) {
      node.position({ x: 0, y: 0 });
      continue;
    }
    const bb = others.boundingBox();
    const cx = (bb.x1 + bb.x2) / 2;
    const cyMid = (bb.y1 + bb.y2) / 2;
    node.position({ x: cx + NEW_NODE_RING_RADIUS, y: cyMid });
  }
}

function syncGraphElements(
  cy: Core,
  nodes: GraphNodeDTO[],
  edges: GraphEdgeDTO[],
  layoutMode: GraphLayoutMode,
): void {
  const desiredNodeIds = new Set(nodes.map((n) => n.id));
  const desiredEdgeIds = new Set(edges.map((e) => e.id));

  cy.nodes().forEach((n) => {
    if (!desiredNodeIds.has(n.id())) n.remove();
  });
  cy.edges().forEach((e) => {
    if (!desiredEdgeIds.has(e.id())) e.remove();
  });

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  cy.nodes().forEach((el) => {
    const dto = nodeById.get(el.id());
    if (!dto) return;
    el.data({
      label: ellipsizeNodeLabel(dto.caption, NODE_LABEL_MAX_WIDTH),
      fullLabel: dto.caption,
      labels: dto.labels.join(", "),
      primaryLabel: dto.labels[0] ?? "Node",
      color: primaryNodeColor(dto.labels),
      properties: dto.properties,
    });
  });

  const existingNodeIds = new Set(cy.nodes().map((n) => n.id()));
  const newNodes = nodes.filter((n) => !existingNodeIds.has(n.id));
  const existingEdgeIds = new Set(cy.edges().map((e) => e.id()));
  const newEdges = edges.filter((e) => !existingEdgeIds.has(e.id));

  const isInitialPopulation = cy.nodes().length === 0 && nodes.length > 0;

  if (newNodes.length > 0 || newEdges.length > 0) {
    cy.add([
      ...newNodes.map(nodeElement),
      ...newEdges.map(edgeElement),
    ]);
  }

  if (isInitialPopulation) {
    cy.layout(
      layoutOptions(
        layoutMode,
        { nodeCount: nodes.length, edgeCount: edges.length },
        false,
      ),
    ).run();
    cy.fit(undefined, 40);
  } else if (newNodes.length > 0) {
    layoutNewNodes(
      cy,
      newNodes.map((n) => n.id),
    );
  }
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
  /** 結果パネル全画面時 — キャンバスを親の高さいっぱいに伸ばす */
  fillHeight?: boolean;
  /** 全画面表示などコンテナサイズが変わったときに Cytoscape を再レイアウトする */
  layoutRevision?: string;
  onSelectionChange?: (selection: GraphSelection | null) => void;
  /** ノードダブルクリック — 近傍グラフを別パネルで開く等 */
  onNodeDoubleClick?: (nodeId: string) => void;
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
    {
      nodes,
      edges,
      searchQuery = "",
      fillHeight = false,
      layoutRevision,
      onSelectionChange,
      onNodeDoubleClick,
    },
    ref,
  ) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const layoutMenuRef = useRef<HTMLDivElement>(null);
  const layoutModeRef = useRef<GraphLayoutMode>("force");
  const onSelectionChangeRef = useRef(onSelectionChange);
  const onNodeDoubleClickRef = useRef(onNodeDoubleClick);
  const [layoutMode, setLayoutMode] = useState<GraphLayoutMode>("force");
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);
  const [pointerInside, setPointerInside] = useState(false);
  const [nodeGrabbing, setNodeGrabbing] = useState(false);
  const setNodeGrabbingRef = useRef(setNodeGrabbing);
  setNodeGrabbingRef.current = setNodeGrabbing;

  layoutModeRef.current = layoutMode;
  onSelectionChangeRef.current = onSelectionChange;
  onNodeDoubleClickRef.current = onNodeDoubleClick;

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
    let cancelled = false;
    const syncViewport = () => {
      if (cancelled) return;
      cy.resize();
      if (layoutRevision === "maximized") {
        cy.fit(undefined, 40);
      }
    };
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(syncViewport);
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(id);
    };
  }, [layoutRevision]);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
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
    cy.on("dbltap", "node", (evt) => {
      const nodeId = String(evt.target.id());
      if (nodeId) {
        onNodeDoubleClickRef.current?.(nodeId);
      }
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

    const releaseNodeGrab = () => setNodeGrabbingRef.current(false);
    const onNodePointerDown = () => {
      setNodeGrabbingRef.current(true);
      const onWindowRelease = () => {
        releaseNodeGrab();
        window.removeEventListener("mouseup", onWindowRelease);
        window.removeEventListener("touchend", onWindowRelease);
      };
      window.addEventListener("mouseup", onWindowRelease);
      window.addEventListener("touchend", onWindowRelease);
    };
    cy.on("mousedown", "node", onNodePointerDown);
    cy.on("touchstart", "node", onNodePointerDown);
    cy.on("free", "node", releaseNodeGrab);

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
      cy.removeListener("mousedown", "node", onNodePointerDown);
      cy.removeListener("touchstart", "node", onNodePointerDown);
      cy.removeListener("free", "node", releaseNodeGrab);
      onSelectionChangeRef.current?.(null);
      setNodeGrabbingRef.current(false);
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    syncGraphElements(cy, nodes, edges, layoutModeRef.current);
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

  const wrapClassName =
    "graph-canvas-wrap" +
    (fillHeight ? " graph-canvas-wrap--fill" : "") +
    (pointerInside ? " graph-canvas-wrap--hand" : "") +
    (nodeGrabbing ? " graph-canvas-wrap--grabbing" : "");

  return (
    <div
      className={wrapClassName}
      onMouseEnter={() => setPointerInside(true)}
      onMouseLeave={() => {
        setPointerInside(false);
        setNodeGrabbing(false);
      }}
    >
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
