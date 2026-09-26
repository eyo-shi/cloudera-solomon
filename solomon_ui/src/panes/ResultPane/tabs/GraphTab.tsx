/**
 * Graph 可視化タブ — Backend API から Graph を取得して中央ペインに描画。
 */
import { useMemo } from "react";
import { SetupGuideError } from "../../../api/client";
import { useGraphQuery } from "../../../api/graph";
import { useTabStore } from "../../../stores/tabStore";
import type { GraphQueryType, TabDescriptor } from "../../../types";
import { GraphCanvas } from "../graph/GraphCanvas";

interface Props {
  tab: TabDescriptor;
}

export function GraphTab({ tab }: Props) {
  const openTab = useTabStore((s) => s.openTab);
  const queryType = tab.ref.query_type as GraphQueryType | undefined;
  const params = useMemo(
    () => ({
      label: tab.ref.label as string | undefined,
      rel_type: tab.ref.rel_type as string | undefined,
      property_key: tab.ref.property_key as string | undefined,
      node_id: tab.ref.node_id as string | undefined,
      entity_hint: tab.ref.entity_hint as string | undefined,
      depth: tab.ref.depth as number | undefined,
    }),
    [tab.ref],
  );

  const enabled = !!queryType;
  const { data, isLoading, error } = useGraphQuery(queryType ?? null, params, enabled);

  function exploreNeighborhood(nodeId: string) {
    openTab({
      title: `Neighborhood: ${nodeId}`,
      kind: "graph",
      ref: {
        query_type: "neighborhood",
        node_id: nodeId,
        depth: 1,
        title: `Neighborhood: ${nodeId}`,
      },
      dedupeKey: `graph:nb:${nodeId}:1`,
    });
  }

  if (!queryType) return <p className="placeholder">Graph クエリが不正です</p>;
  if (isLoading) return <p className="placeholder">Graph を読み込み中…</p>;
  if (error instanceof SetupGuideError) {
    return (
      <p className="placeholder">
        Neo4j 未設定です。環境変数を確認してください。
      </p>
    );
  }
  if (error) {
    return (
      <div className="tab-error">
        <strong>Graph 取得に失敗</strong>
        <pre>{String((error as Error).message ?? error)}</pre>
      </div>
    );
  }
  if (!data) return <p className="placeholder">Graph データがありません</p>;

  const { graph, cypher, node_count, edge_count } = data;
  const empty = graph.nodes.length === 0;

  return (
    <div className="tab-content tab-content--graph">
      <div className="tab-meta">
        <span className="meta-badge">{node_count} nodes</span>
        <span className="meta-badge">{edge_count} edges</span>
        {graph.truncated && (
          <span className="meta-badge meta-badge--warn">truncated</span>
        )}
      </div>
      {cypher && (
        <details className="graph-cypher-details">
          <summary>Cypher</summary>
          <pre>{cypher}</pre>
        </details>
      )}
      {empty ? (
        <p className="placeholder">該当する Node / Relationship がありません</p>
      ) : (
        <GraphCanvas
          nodes={graph.nodes}
          edges={graph.edges}
          onExploreNeighborhood={exploreNeighborhood}
        />
      )}
    </div>
  );
}
