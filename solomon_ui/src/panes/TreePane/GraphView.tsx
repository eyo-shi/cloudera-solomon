/**
 * Graph (Neo4j) ビュー — Node Labels / Relationship Types / Property Keys。
 * クリックで中央ペインに Graph 可視化タブを開く。
 */
import { useEffect, useMemo } from "react";
import { SetupGuideError } from "../../api/client";
import { useGraphSchema } from "../../api/graph";
import { useChatStore } from "../../stores/chatStore";
import { useTabStore } from "../../stores/tabStore";
import type { GraphQueryType } from "../../types";

interface GraphViewProps {
  filter: string;
}

function filterList(items: string[], filter: string): string[] {
  const q = filter.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) => item.toLowerCase().includes(q));
}

export function GraphView({ filter }: GraphViewProps) {
  const { data, isLoading, error } = useGraphSchema();
  const setSetupError = useChatStore((s) => s.setSetupError);
  const openTab = useTabStore((s) => s.openTab);

  useEffect(() => {
    if (error instanceof SetupGuideError) {
      setSetupError(error);
    }
  }, [error, setSetupError]);

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

  function openGraph(
    queryType: GraphQueryType,
    title: string,
    ref: Record<string, string | number | undefined>,
    dedupeKey: string,
  ) {
    openTab({
      title,
      kind: "graph",
      ref: { query_type: queryType, title, ...ref },
      dedupeKey,
    });
  }

  if (isLoading) return <p className="explorer-placeholder">Loading schema…</p>;
  if (error instanceof SetupGuideError) {
    return (
      <p className="explorer-placeholder">
        Neo4j 未設定です。右ペインの設定手順を確認してください。
      </p>
    );
  }
  if (error) return <p className="explorer-error">スキーマ取得に失敗</p>;

  const empty =
    labels.length === 0 && relTypes.length === 0 && propKeys.length === 0;

  return (
    <div className="explorer-view explorer-view--graph">
      <div className="explorer-section-head">
        <span className="explorer-section-title">Graph</span>
      </div>

      {empty && (
        <p className="explorer-placeholder">グラフスキーマが空です</p>
      )}

      <SchemaSection
        title="Node Labels"
        count={labels.length}
        items={labels}
        onSelect={(label) =>
          openGraph(
            "label",
            label,
            { label },
            `graph:label:${label}`,
          )
        }
      />
      <SchemaSection
        title="Relationship Types"
        count={relTypes.length}
        items={relTypes}
        onSelect={(relType) =>
          openGraph(
            "relationship",
            relType,
            { rel_type: relType },
            `graph:rel:${relType}`,
          )
        }
      />
      <SchemaSection
        title="Property Keys"
        count={propKeys.length}
        items={propKeys}
        onSelect={(key) =>
          openGraph(
            "property",
            key,
            { property_key: key },
            `graph:prop:${key}`,
          )
        }
      />
    </div>
  );
}

function SchemaSection({
  title,
  count,
  items,
  onSelect,
}: {
  title: string;
  count: number;
  items: string[];
  onSelect: (item: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section className="graph-schema-section">
      <div className="graph-schema-section__head">
        <span className="graph-schema-section__title">{title}</span>
        <span className="explorer-section-count">({count})</span>
      </div>
      <ul className="graph-schema-list">
        {items.map((item) => (
          <li key={item}>
            <button
              type="button"
              className="graph-schema-item"
              onClick={() => onSelect(item)}
              title={`Explore ${title}: ${item}`}
            >
              {item}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
