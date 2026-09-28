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
import type { GraphQueryResponse, GraphQueryType } from "../types";
import { useTabStore } from "./tabStore";

export type GraphPanelView = "graph" | "table" | "raw";

export interface GraphResultPanel {
  id: string;
  cypher: string;
  queryType: GraphQueryType | "cypher";
  status: "loading" | "ready" | "error";
  error?: string;
  data?: GraphQueryResponse;
  defaultView: GraphPanelView;
}

export interface GraphSidebarQuery {
  queryType: GraphQueryType;
  label?: string;
  rel_type?: string;
  property_key?: string;
}

interface GraphState {
  queryInput: string;
  panels: GraphResultPanel[];
  setQueryInput: (value: string) => void;
  appendSidebarQuery: (spec: GraphSidebarQuery) => void;
  runQueryInput: () => void;
  appendNeighborhood: (nodeId: string) => void;
  appendEntityQuery: (entityHint: string) => void;
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

async function loadPanel(
  panelId: string,
  loader: () => Promise<GraphQueryResponse>,
): Promise<void> {
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
  panels: [],

  setQueryInput: (value) => set({ queryInput: value }),

  appendSidebarQuery: (spec) => {
    ensureGraphTab();
    let cypher = "";
    let defaultView: GraphPanelView = "graph";
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
    } else {
      return;
    }

    const panelId = nextPanelId();
    set((s) => ({
      queryInput: cypher,
      panels: [
        ...s.panels,
        {
          id: panelId,
          cypher,
          queryType: spec.queryType,
          status: "loading",
          defaultView,
        },
      ],
    }));

    void loadPanel(panelId, () => fetchGraphQuery(spec.queryType, params));
  },

  runQueryInput: () => {
    const cypher = get().queryInput.trim();
    if (!cypher) return;
    ensureGraphTab();

    const panelId = nextPanelId();
    set((s) => ({
      panels: [
        ...s.panels,
        {
          id: panelId,
          cypher,
          queryType: "cypher",
          status: "loading",
          defaultView: "graph",
        },
      ],
    }));

    void loadPanel(panelId, () => executeGraphCypher(cypher));
  },

  appendNeighborhood: (nodeId) => {
    ensureGraphTab();
    const cypher = `MATCH (n) WHERE coalesce(n.id, elementId(n)) = "${nodeId}" MATCH path = (n)-[*1..1]-(m) RETURN path LIMIT 25;`;
    const panelId = nextPanelId();
    set((s) => ({
      queryInput: cypher,
      panels: [
        ...s.panels,
        {
          id: panelId,
          cypher,
          queryType: "neighborhood",
          status: "loading",
          defaultView: "graph",
        },
      ],
    }));
    void loadPanel(panelId, () =>
      fetchGraphQuery("neighborhood", { node_id: nodeId, depth: 1 }),
    );
  },

  appendEntityQuery: (entityHint) => {
    ensureGraphTab();
    const cypher = `MATCH (sys:System) WHERE toLower(sys.name) CONTAINS toLower("${entityHint}") RETURN sys LIMIT 25;`;
    const panelId = nextPanelId();
    set((s) => ({
      queryInput: cypher,
      panels: [
        ...s.panels,
        {
          id: panelId,
          cypher,
          queryType: "entity",
          status: "loading",
          defaultView: "graph",
        },
      ],
    }));
    void loadPanel(panelId, () =>
      fetchGraphQuery("entity", { entity_hint: entityHint }),
    );
  },
}));
