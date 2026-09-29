/**
 * Graph (Neo4j) ビュー — Database information 風スキーマブラウザ。
 */
import { useMemo } from "react";
import { isSetupGuideError } from "../../api/client";
import { refreshGraphSchema } from "../../api/explorerRefresh";
import { useGraphSchema } from "../../api/graph";
import { labelColor } from "../../graph/colors";
import { useReportSetupGuideError } from "../../hooks/useReportSetupGuideError";
import { useGraphStore } from "../../stores/graphStore";
import type { GraphQueryType } from "../../types";
import { ExplorerRefreshButton } from "./ExplorerRefreshButton";

interface GraphViewProps {
  filter: string;
}

function filterList(items: string[], filter: string): string[] {
  const q = filter.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) => item.toLowerCase().includes(q));
}

export function GraphView({ filter }: GraphViewProps) {
  const { data, isLoading, error, isFetching } = useGraphSchema();
  const appendSidebarQuery = useGraphStore((s) => s.appendSidebarQuery);
  useReportSetupGuideError(error);

  const labels = useMemo(
    () => filterList(data?.node_labels ?? [], filter),
    [data?.node_labels, filter],
  );
  const relTypes = useMemo(
    () => filterList(data?.relationship_types ?? [], filter),
    [data?.relationship_types, filter],
  );
  const propKeys = useMemo(
    () => filterList(data?.property_keys ?? [], filter),
    [data?.property_keys, filter],
  );

  function dispatch(
    queryType: GraphQueryType,
    ref: { label?: string; rel_type?: string; property_key?: string },
  ) {
    appendSidebarQuery({ queryType, ...ref });
  }

  const sectionHead = (
    <div className="explorer-section-head">
      <span className="explorer-section-title">Database information</span>
      <div className="explorer-section-actions">
        <ExplorerRefreshButton
          isFetching={isFetching}
          onRefresh={() => void refreshGraphSchema()}
        />
      </div>
    </div>
  );

  if (isLoading) {
    return (
      <div className="explorer-view explorer-view--graph">
        {sectionHead}
        <p className="explorer-placeholder">Loading schema…</p>
      </div>
    );
  }
  if (isSetupGuideError(error)) {
    return (
      <div className="explorer-view explorer-view--graph">
        {sectionHead}
        <p className="explorer-placeholder">
          Neo4j 未設定です。右ペインの設定手順を確認してください。
        </p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="explorer-view explorer-view--graph">
        {sectionHead}
        <p className="explorer-error">スキーマ取得に失敗</p>
      </div>
    );
  }

  const empty =
    labels.length === 0 && relTypes.length === 0 && propKeys.length === 0;
  const nodeTotal = data?.node_count ?? labels.length;
  const relTotal = data?.relationship_count ?? relTypes.length;

  return (
    <div className="explorer-view explorer-view--graph">
      {sectionHead}
      <div className="graph-db-info">
        {empty && (
          <p className="explorer-placeholder">グラフスキーマが空です</p>
        )}

        {labels.length > 0 && (
          <section className="graph-db-section">
            <div className="graph-db-section__head">Nodes ({nodeTotal})</div>
            <div className="graph-db-section__chips">
              <span className="graph-chip graph-chip--wildcard">*</span>
              {labels.map((label) => (
                <button
                  key={label}
                  type="button"
                  className="graph-chip graph-chip--node graph-chip--btn"
                  style={{ backgroundColor: labelColor(label) }}
                  onClick={() => dispatch("label", { label })}
                  title={`Explore :${label}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>
        )}

        {relTypes.length > 0 && (
          <section className="graph-db-section">
            <div className="graph-db-section__head">
              Relationships ({relTotal})
            </div>
            <div className="graph-db-section__chips">
              <span className="graph-chip graph-chip--rel">*</span>
              {relTypes.map((relType) => (
                <button
                  key={relType}
                  type="button"
                  className="graph-chip graph-chip--rel graph-chip--btn"
                  onClick={() => dispatch("relationship", { rel_type: relType })}
                  title={`Explore :${relType}`}
                >
                  {relType}
                </button>
              ))}
            </div>
          </section>
        )}

        {propKeys.length > 0 && (
          <section className="graph-db-section">
            <div className="graph-db-section__head">Property keys</div>
            <div className="graph-db-section__chips">
              {propKeys.map((key) => (
                <button
                  key={key}
                  type="button"
                  className="graph-chip graph-chip--prop graph-chip--btn"
                  onClick={() => dispatch("property", { property_key: key })}
                  title={`Explore property ${key}`}
                >
                  {key}
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
