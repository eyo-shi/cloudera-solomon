/**
 * テーブル Explore ビュー。スキーマ選択とフラットなテーブル一覧。
 * スキーマ選択 → フラットなテーブル一覧。検索・ホバーツールチップ・ダブルクリックで中央表示。
 */
import { useEffect, useMemo, useState } from "react";
import { isSetupGuideError } from "../../api/client";
import { useSchemas, useTables } from "../../api/catalog";
import { refreshCatalogExplorer } from "../../api/explorerRefresh";
import { fetchTablePreview } from "../../api/query";
import { useReportSetupGuideError } from "../../hooks/useReportSetupGuideError";
import { useChatStore } from "../../stores/chatStore";
import { useTabStore } from "../../stores/tabStore";
import { ExplorerRefreshButton } from "./ExplorerRefreshButton";
import { IconDatabase, IconTableGrid } from "./ExplorerIcons";
import { NodeMenu } from "./NodeMenu";
import { TableColumnTooltip } from "./TableColumnTooltip";

const CATALOG = "iceberg";

interface ExploreViewProps {
  filter: string;
}

interface TableNode {
  id: string;
  name: string;
  fq: string;
}

export function ExploreView({ filter }: ExploreViewProps) {
  const { data, isLoading, error, isFetching } = useSchemas(CATALOG);
  const [schema, setSchema] = useState<string | null>(null);
  const [autoSelected, setAutoSelected] = useState(false);
  const [hovered, setHovered] = useState<{ fq: string; rect: DOMRect } | null>(
    null,
  );
  const [menuFor, setMenuFor] = useState<{
    x: number;
    y: number;
    node: TableNode;
  } | null>(null);

  const openTab = useTabStore((s) => s.openTab);
  const setPendingPrompt = useChatStore((s) => s.setPendingPrompt);

  const schemas = data?.schemas ?? [];
  const {
    data: tablesData,
    isLoading: tablesLoading,
    error: tablesError,
    isFetching: tablesFetching,
  } = useTables(schema, CATALOG);

  const filteredTables = useMemo(() => {
    const list = tablesData?.tables ?? [];
    if (!filter.trim()) return list;
    const f = filter.toLowerCase();
    return list.filter(
      (t) =>
        t.name.toLowerCase().includes(f) ||
        t.fq.toLowerCase().includes(f),
    );
  }, [tablesData, filter]);

  const sectionCount = schema ? filteredTables.length : schemas.length;
  const sectionBusy = schema ? tablesFetching : isFetching;

  useReportSetupGuideError(error);

  // 初回のみ: default スキーマがあれば自動選択、なければ先頭
  useEffect(() => {
    if (autoSelected || schemas.length === 0) return;
    const preferred = schemas.find((s) => s.toLowerCase() === "default");
    setSchema(preferred ?? schemas[0] ?? null);
    setAutoSelected(true);
  }, [schemas, autoSelected]);

  function openTablePreview(fq: string) {
    openTab({
      title: fq.split(".").slice(-1)[0] ?? fq,
      kind: "table_preview",
      ref: { fq },
      dedupeKey: `table:${fq}`,
    });
    fetchTablePreview(fq, 100).catch(() => {
      /* タブ側で再表示 */
    });
  }

  const sectionHead = (
    <div className="explorer-section-head">
      <span className="explorer-section-title">Tables</span>
      <span className="explorer-section-count">({sectionCount})</span>
      <div className="explorer-section-actions">
        <ExplorerRefreshButton
          isFetching={sectionBusy}
          onRefresh={() => void refreshCatalogExplorer()}
        />
      </div>
    </div>
  );

  if (isLoading) {
    return (
      <div className="explorer-view">
        {sectionHead}
        <p className="explorer-placeholder">Loading…</p>
      </div>
    );
  }
  if (isSetupGuideError(error)) {
    return (
      <div className="explorer-view">
        {sectionHead}
        <p className="explorer-placeholder">
          Trino 未設定です。右ペインの設定手順を確認してください。
        </p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="explorer-view">
        {sectionHead}
        <p className="explorer-error">スキーマ取得に失敗</p>
      </div>
    );
  }

  if (!schema) {
    return (
      <div className="explorer-view">
        {sectionHead}
        <ul className="explorer-table-list">
          {schemas.map((s) => (
            <li key={s}>
              <button
                type="button"
                className="explorer-table-row"
                onClick={() => setSchema(s)}
              >
                <IconDatabase />
                <span className="explorer-table-name">{s}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="explorer-view" onClick={() => setMenuFor(null)}>
      {sectionHead}

      <nav className="explorer-breadcrumb">
        <button
          type="button"
          className="explorer-breadcrumb__back"
          aria-label="スキーマ一覧へ戻る"
          onClick={() => setSchema(null)}
        >
          ‹
        </button>
        <IconDatabase />
        <span className="explorer-breadcrumb__label">{schema}</span>
      </nav>

      {tablesLoading && (
        <p className="explorer-placeholder">Loading tables…</p>
      )}
      {tablesError && (
        <p className="explorer-error">テーブル取得に失敗</p>
      )}
      {!tablesLoading && !tablesError && (
        <ul className="explorer-table-list">
          {filteredTables.map((t) => {
            const node: TableNode = { id: t.fq, name: t.name, fq: t.fq };
            return (
              <li key={t.fq}>
                <button
                  type="button"
                  className="explorer-table-row"
                  onDoubleClick={() => openTablePreview(t.fq)}
                  onMouseEnter={(e) =>
                    setHovered({ fq: t.fq, rect: e.currentTarget.getBoundingClientRect() })
                  }
                  onMouseLeave={() => setHovered(null)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setMenuFor({ x: e.clientX, y: e.clientY, node });
                  }}
                >
                  <IconTableGrid />
                  <span className="explorer-table-name">{t.name}</span>
                </button>
              </li>
            );
          })}
          {filteredTables.length === 0 && (
            <li className="explorer-placeholder">テーブルが見つかりません</li>
          )}
        </ul>
      )}

      {hovered && (
        <TableColumnTooltip fq={hovered.fq} anchor={hovered.rect} />
      )}

      {menuFor && (
        <NodeMenu
          x={menuFor.x}
          y={menuFor.y}
          onClose={() => setMenuFor(null)}
          items={[
            {
              label: "Preview (sample 100 rows)",
              onSelect: () => openTablePreview(menuFor.node.fq),
            },
            {
              label: "サマリーを作って",
              onSelect: () =>
                setPendingPrompt(
                  `テーブル ${menuFor.node.fq} のサマリーを作って`,
                ),
            },
            {
              label: "ダッシュボードを作って",
              onSelect: () =>
                setPendingPrompt(
                  `テーブル ${menuFor.node.fq} からダッシュボードを作って`,
                ),
            },
          ]}
        />
      )}
    </div>
  );
}
