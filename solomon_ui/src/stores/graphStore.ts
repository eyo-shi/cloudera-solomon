/**
 * Graph ワークスペース — 単一 Graph タブ内のクエリ入力と結果スタック。
 */
import { create } from "zustand";
import {
  executeGraphCypher,
  fetchGraphQuery,
  labelCypher,
  propertyCypher,
  relationshipCypher,
} from "../api/graph";
import type {
  GraphQueryResponse,
  GraphQueryType,
  GraphVisualization,
} from "../types";
import { useTabStore } from "./tabStore";

export type GraphPanelView = "graph" | "table" | "raw";

export interface GraphResultPanel {
  id: string;
  cypher: string;
  /** パネル表示用 Cypher と異なる実行文（Graph 可視化向け RETURN 等） */
  runCypher?: string;
  cypherParams?: Record<string, string | number | boolean>;
  queryType: GraphQueryType | "cypher";
  status: "loading" | "ready" | "error";
  error?: string;
  data?: GraphQueryResponse;
  defaultView: GraphPanelView;
  /** 表示可能なビュー。未指定時は Graph / Table / Raw すべて。 */
  allowedViews?: GraphPanelView[];
  sidebarSpec?: GraphSidebarQuery;
  nodeId?: string;
  entityHint?: string;
}

export interface GraphSidebarQuery {
  queryType: GraphQueryType;
  label?: string;
  rel_type?: string;
  property_key?: string;
}

interface GraphState {
  queryInput: string;
  /** クエリバー実行時に POST へ渡す Cypher パラメータ（$trace_id 等） */
  queryParams: Record<string, string | number | boolean>;
  panels: GraphResultPanel[];
  maximizedPanelId: string | null;
  setQueryInput: (value: string) => void;
  appendSidebarQuery: (spec: GraphSidebarQuery) => void;
  runQueryInput: () => void;
  /** 指定パネルのグラフに、ノード近傍（1ホップ）をマージする */
  expandNeighborhoodInPanel: (panelId: string, nodeId: string) => void;
  appendEntityQuery: (entityHint: string) => void;
  /** Chat の solomon://graph-cypher リンクからパネルを追加して実行 */
  appendCypherQuery: (
    cypher: string,
    params?: Record<string, string | number | boolean>,
    runCypher?: string,
  ) => void;
  removePanel: (panelId: string) => void;
  rerunPanel: (panelId: string) => void;
  toggleMaximizePanel: (panelId: string) => void;
}

const GRAPH_TAB_KEY = "graph:workspace";

let _panelSeq = 0;
function nextPanelId(): string {
  _panelSeq += 1;
  return `graph-panel-${_panelSeq}`;
}

export function ensureGraphTab(): void {
  useTabStore.getState().openTab({
    title: "Graph",
    kind: "graph",
    ref: { workspace: true },
    dedupeKey: GRAPH_TAB_KEY,
  });
}

function panelLoader(panel: GraphResultPanel): () => Promise<GraphQueryResponse> {
  if (panel.sidebarSpec) {
    const spec = panel.sidebarSpec;
    const params: Record<string, string | number | undefined> = {};
    if (spec.label) params.label = spec.label;
    if (spec.rel_type) params.rel_type = spec.rel_type;
    if (spec.property_key) params.property_key = spec.property_key;
    return () => fetchGraphQuery(spec.queryType, params);
  }
  if (panel.queryType === "neighborhood" && panel.nodeId) {
    return () =>
      fetchGraphQuery("neighborhood", { node_id: panel.nodeId, depth: 1 });
  }
  if (panel.queryType === "entity" && panel.entityHint) {
    return () =>
      fetchGraphQuery("entity", { entity_hint: panel.entityHint });
  }
  const statement = (panel.runCypher ?? panel.cypher).trim();
  return () => executeGraphCypher(statement, panel.cypherParams ?? {});
}

function mergeGraphVisualizations(
  base: GraphVisualization,
  added: GraphVisualization,
): GraphVisualization {
  const nodeById = new Map(base.nodes.map((n) => [n.id, n]));
  for (const n of added.nodes) {
    if (!nodeById.has(n.id)) nodeById.set(n.id, n);
  }
  const edgeById = new Map(base.edges.map((e) => [e.id, e]));
  for (const e of added.edges) {
    if (!edgeById.has(e.id)) edgeById.set(e.id, e);
  }
  return {
    ...base,
    nodes: [...nodeById.values()],
    edges: [...edgeById.values()],
    truncated: Boolean(base.truncated || added.truncated),
  };
}

async function loadPanel(
  panelId: string,
  loader: () => Promise<GraphQueryResponse>,
): Promise<void> {
  useGraphStore.setState((s) => ({
    panels: s.panels.map((p) =>
      p.id === panelId
        ? { ...p, status: "loading" as const, error: undefined, data: undefined }
        : p,
    ),
  }));
  try {
    const data = await loader();
    useGraphStore.setState((s) => ({
      panels: s.panels.map((p) =>
        p.id === panelId ? { ...p, status: "ready" as const, data } : p,
      ),
    }));
  } catch (err) {
    useGraphStore.setState((s) => ({
      panels: s.panels.map((p) =>
        p.id === panelId
          ? {
              ...p,
              status: "error" as const,
              error: String((err as Error).message ?? err),
            }
          : p,
      ),
    }));
  }
}

export const useGraphStore = create<GraphState>((set, get) => ({
  queryInput: "",
  queryParams: {},
  panels: [],
  maximizedPanelId: null,

  setQueryInput: (value) => set({ queryInput: value }),

  appendSidebarQuery: (spec) => {
    ensureGraphTab();
    const panelId = nextPanelId();
    let cypher = "";
    let defaultView: GraphPanelView = "graph";
    let allowedViews: GraphPanelView[] | undefined;
    const params: Record<string, string | number | undefined> = {};

    if (spec.queryType === "label" && spec.label) {
      cypher = labelCypher(spec.label);
      params.label = spec.label;
      defaultView = "graph";
    } else if (spec.queryType === "relationship" && spec.rel_type) {
      cypher = relationshipCypher(spec.rel_type);
      params.rel_type = spec.rel_type;
      defaultView = "graph";
    } else if (spec.queryType === "property" && spec.property_key) {
      cypher = propertyCypher(spec.property_key);
      params.property_key = spec.property_key;
      defaultView = "table";
      allowedViews = ["table", "raw"];
    } else {
      return;
    }
    set((s) => ({
      queryInput: cypher,
      queryParams: {},
      panels: [
        {
          id: panelId,
          cypher,
          queryType: spec.queryType,
          status: "loading",
          defaultView,
          allowedViews,
          sidebarSpec: spec,
        },
        ...s.panels,
      ],
    }));

    void loadPanel(panelId, () => fetchGraphQuery(spec.queryType, params));
  },

  runQueryInput: () => {
    const cypher = get().queryInput.trim();
    if (!cypher) return;
    ensureGraphTab();
    const queryParams = get().queryParams;

    const panelId = nextPanelId();
    set((s) => ({
      panels: [
        {
          id: panelId,
          cypher,
          cypherParams:
            Object.keys(queryParams).length > 0 ? queryParams : undefined,
          queryType: "cypher",
          status: "loading",
          defaultView: "graph",
        },
        ...s.panels,
      ],
    }));

    void loadPanel(panelId, () => executeGraphCypher(cypher, queryParams));
  },

  appendCypherQuery: (cypher, params, runCypher) => {
    const text = cypher.trim();
    if (!text) return;
    ensureGraphTab();
    const panelId = nextPanelId();
    const cypherParams = params && Object.keys(params).length > 0 ? params : undefined;
    const runText = runCypher?.trim();
    const run = runText && runText !== text ? runText : undefined;
    const executeStatement = run ?? text;
    set((s) => ({
      queryInput: text,
      queryParams: cypherParams ?? {},
      panels: [
        {
          id: panelId,
          cypher: text,
          runCypher: run,
          cypherParams,
          queryType: "cypher",
          status: "loading",
          defaultView: "graph",
        },
        ...s.panels,
      ],
    }));
    void loadPanel(panelId, () =>
      executeGraphCypher(executeStatement, cypherParams ?? {}),
    );
  },

  expandNeighborhoodInPanel: (panelId, nodeId) => {
    const panel = get().panels.find((p) => p.id === panelId);
    if (!panel?.data?.graph) return;

    const cypher = `MATCH (n) WHERE coalesce(n.id, elementId(n)) = "${nodeId}" MATCH path = (n)-[*1..1]-(m) RETURN path LIMIT 25;`;
    set({ queryInput: cypher });

    void (async () => {
      try {
        const fetched = await fetchGraphQuery("neighborhood", {
          node_id: nodeId,
          depth: 1,
        });
        if (!fetched.graph) {
          throw new Error("Neighborhood query returned no graph data");
        }
        useGraphStore.setState((s) => ({
          panels: s.panels.map((p) => {
            if (p.id !== panelId || !p.data?.graph) return p;
            const graph = mergeGraphVisualizations(p.data.graph, fetched.graph);
            return {
              ...p,
              error: undefined,
              data: {
                ...p.data,
                graph,
                node_count: graph.nodes.length,
                edge_count: graph.edges.length,
              },
            };
          }),
        }));
      } catch (err) {
        useGraphStore.setState((s) => ({
          panels: s.panels.map((p) =>
            p.id === panelId
              ? {
                  ...p,
                  error: String((err as Error).message ?? err),
                }
              : p,
          ),
        }));
      }
    })();
  },

  appendEntityQuery: (entityHint) => {
    ensureGraphTab();
    const cypher = `MATCH (sys:System) WHERE toLower(sys.name) CONTAINS toLower("${entityHint}") RETURN sys LIMIT 25;`;
    const panelId = nextPanelId();
    set((s) => ({
      queryInput: cypher,
      queryParams: {},
      panels: [
        {
          id: panelId,
          cypher,
          queryType: "entity",
          status: "loading",
          defaultView: "graph",
          entityHint,
        },
        ...s.panels,
      ],
    }));
    void loadPanel(panelId, () =>
      fetchGraphQuery("entity", { entity_hint: entityHint }),
    );
  },

  removePanel: (panelId) => {
    set((s) => ({
      panels: s.panels.filter((p) => p.id !== panelId),
      maximizedPanelId:
        s.maximizedPanelId === panelId ? null : s.maximizedPanelId,
    }));
  },

  toggleMaximizePanel: (panelId) => {
    set((s) => ({
      maximizedPanelId:
        s.maximizedPanelId === panelId ? null : panelId,
    }));
  },

  rerunPanel: (panelId) => {
    const panel = get().panels.find((p) => p.id === panelId);
    if (!panel) return;
    set({
      queryInput: panel.cypher,
      queryParams: panel.cypherParams ?? {},
    });
    void loadPanel(panelId, panelLoader(panel));
  },
}));
