/**
 * テーブル Explore ビュー — スキーマを accordion 展開し、テーブル一覧をネスト表示。
 */
import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { isSetupGuideError } from "../../api/client";
import { useSchemas, useTables } from "../../api/catalog";
import { refreshCatalogExplorer } from "../../api/explorerRefresh";
import { useReportSetupGuideError } from "../../hooks/useReportSetupGuideError";
import { useChatStore } from "../../stores/chatStore";
import { useTablesStore } from "../../stores/tablesStore";
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
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [initialExpandDone, setInitialExpandDone] = useState(false);
  const [hovered, setHovered] = useState<{ fq: string; rect: DOMRect } | null>(
    null,
  );
  const [menuFor, setMenuFor] = useState<{
    x: number;
    y: number;
    node: TableNode;
  } | null>(null);

  const appendTablePreview = useTablesStore((s) => s.appendTablePreview);
  const setPendingPrompt = useChatStore((s) => s.setPendingPrompt);

  const schemas = data?.schemas ?? [];

  const filteredSchemas = useMemo(() => {
    if (!filter.trim()) return schemas;
    const f = filter.toLowerCase();
    return schemas.filter((s) => s.toLowerCase().includes(f));
  }, [schemas, filter]);

  const sectionCount = schemas.length;
  useReportSetupGuideError(error);

  useEffect(() => {
    if (initialExpandDone || schemas.length === 0) return;
    const preferred = schemas.find((s) => s.toLowerCase() === "demo") ?? schemas[0];
    if (preferred) {
      setExpanded(new Set([`${CATALOG}.${preferred}`]));
    }
    setInitialExpandDone(true);
  }, [schemas, initialExpandDone]);

  function toggleSchema(schemaKey: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(schemaKey)) next.delete(schemaKey);
      else next.add(schemaKey);
      return next;
    });
  }

  function openTable(fq: string) {
    appendTablePreview(fq, 100);
  }

  const sectionHead = (
    <div className="explorer-section-head">
      <span className="explorer-section-title">Tables</span>
      <span className="explorer-section-count">({sectionCount})</span>
      <div className="explorer-section-actions">
        <ExplorerRefreshButton
          isFetching={isFetching}
          onRefresh={() => void refreshCatalogExplorer()}
        />
      </div>
    </div>
  );

  if (isLoading) {
    return (
      <div className="explorer-view explorer-view--tables">
        {sectionHead}
        <p className="explorer-placeholder">Loading…</p>
      </div>
    );
  }
  if (isSetupGuideError(error)) {
    return (
      <div className="explorer-view explorer-view--tables">
        {sectionHead}
        <p className="explorer-placeholder">
          Trino 未接続です。warehouse-launcher の起動を待つか、右ペインの設定手順を確認してください。
        </p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="explorer-view explorer-view--tables">
        {sectionHead}
        <p className="explorer-error">スキーマ取得に失敗</p>
      </div>
    );
  }

  return (
    <div
      className="explorer-view explorer-view--tables"
      onClick={() => setMenuFor(null)}
    >
      {sectionHead}

      <ul className="tree-list explorer-catalog-tree">
        {filteredSchemas.map((schema) => {
          const schemaKey = `${CATALOG}.${schema}`;
          const isOpen = expanded.has(schemaKey);
          return (
            <li key={schemaKey} className="tree-node">
              <button
                type="button"
                className="tree-row tree-row--schema explorer-tree-row"
                onClick={() => toggleSchema(schemaKey)}
              >
                <span className="tree-caret">{isOpen ? "▾" : "▸"}</span>
                <IconDatabase />
                <span className="tree-label">{schema}</span>
              </button>
              {isOpen && (
                <SchemaTables
                  catalog={CATALOG}
                  schema={schema}
                  filter={filter}
                  onOpen={openTable}
                  onHover={(fq, rect) => setHovered({ fq, rect })}
                  onHoverEnd={() => setHovered(null)}
                  onMenu={(e, node) => {
                    e.preventDefault();
                    setMenuFor({ x: e.clientX, y: e.clientY, node });
                  }}
                />
              )}
            </li>
          );
        })}
        {filteredSchemas.length === 0 && (
          <li className="explorer-placeholder">スキーマが見つかりません</li>
        )}
      </ul>

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
              onSelect: () => openTable(menuFor.node.fq),
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

interface SchemaTablesProps {
  catalog: string;
  schema: string;
  filter: string;
  onOpen: (fq: string) => void;
  onHover: (fq: string, rect: DOMRect) => void;
  onHoverEnd: () => void;
  onMenu: (e: ReactMouseEvent, node: TableNode) => void;
}

function SchemaTables({
  catalog,
  schema,
  filter,
  onOpen,
  onHover,
  onHoverEnd,
  onMenu,
}: SchemaTablesProps) {
  const { data, isLoading, error } = useTables(schema, catalog);
  if (isLoading) {
    return <p className="explorer-placeholder explorer-catalog-tree__loading">…</p>;
  }
  if (error) {
    return <p className="tree-error explorer-catalog-tree__error">読み込み失敗</p>;
  }

  const tables = data?.tables ?? [];
  const f = filter.trim().toLowerCase();
  const filtered = f
    ? tables.filter(
        (t) =>
          t.name.toLowerCase().includes(f) ||
          t.fq.toLowerCase().includes(f),
      )
    : tables;

  return (
    <ul className="tree-child-list explorer-catalog-tree__tables">
      {filtered.map((t) => {
        const node: TableNode = { id: t.fq, name: t.name, fq: t.fq };
        return (
          <li key={t.fq}>
            <button
              type="button"
              className="tree-row tree-row--table explorer-tree-row explorer-tree-row--table"
              onClick={() => onOpen(t.fq)}
              onMouseEnter={(e) =>
                onHover(t.fq, e.currentTarget.getBoundingClientRect())
              }
              onMouseLeave={onHoverEnd}
              onContextMenu={(e) => onMenu(e, node)}
            >
              <IconTableGrid />
              <span className="tree-label" title={t.fq}>
                {t.name}
              </span>
            </button>
          </li>
        );
      })}
      {filtered.length === 0 && (
        <li className="explorer-placeholder">テーブルが見つかりません</li>
      )}
    </ul>
  );
}
