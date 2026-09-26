/**
 * 左ペイン: データ Explorer（Tables / Storage / Graph / Search 切替）。
 *
 * 上部アイコンで各データソースを切替。
 * Search タブ: 表示ラベル "Search"、ツールチップ / aria-label "Semantic Search"。
 */
import { useState } from "react";
import { ExploreView } from "./ExploreView";
import {
  IconGraph,
  IconSemanticSearch,
  IconStorage,
  IconTables,
} from "./ExplorerIcons";
import { GraphView } from "./GraphView";
import { SearchView } from "./SearchView";
import { StorageView } from "./StorageView";

export type ExplorerMode = "tables" | "storage" | "graph" | "search";

const SEARCH_PLACEHOLDERS: Record<ExplorerMode, string> = {
  tables: "Search SQL tables…",
  storage: "Search storage…",
  graph: "Search graph nodes…",
  search: "Search indexed documents…",
};

export function TreePane() {
  const [mode, setMode] = useState<ExplorerMode>("tables");
  const [filter, setFilter] = useState("");

  return (
    <div className="tree-pane">
      <div className="explorer-toolbar">
        <button
          type="button"
          className={
            "explorer-toolbar__btn" +
            (mode === "tables" ? " explorer-toolbar__btn--active" : "")
          }
          aria-label="Tables"
          title="Tables"
          onClick={() => setMode("tables")}
        >
          <IconTables active={mode === "tables"} />
        </button>
        <button
          type="button"
          className={
            "explorer-toolbar__btn" +
            (mode === "storage" ? " explorer-toolbar__btn--active" : "")
          }
          aria-label="Storage"
          title="Storage"
          onClick={() => setMode("storage")}
        >
          <IconStorage active={mode === "storage"} />
        </button>
        <button
          type="button"
          className={
            "explorer-toolbar__btn" +
            (mode === "graph" ? " explorer-toolbar__btn--active" : "")
          }
          aria-label="Graph"
          title="Graph"
          onClick={() => setMode("graph")}
        >
          <IconGraph active={mode === "graph"} />
        </button>
        <button
          type="button"
          className={
            "explorer-toolbar__btn explorer-toolbar__btn--labeled" +
            (mode === "search" ? " explorer-toolbar__btn--active" : "")
          }
          aria-label="Semantic Search"
          title="Semantic Search"
          onClick={() => setMode("search")}
        >
          <IconSemanticSearch active={mode === "search"} />
          <span className="explorer-toolbar__label">Search</span>
        </button>
      </div>

      <div className="explorer-search">
        <input
          type="search"
          placeholder={SEARCH_PLACEHOLDERS[mode]}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <span className="explorer-search__icon" aria-hidden="true">
          ⌕
        </span>
      </div>

      <div className="tree-body explorer-body">
        {mode === "tables" && <ExploreView filter={filter} />}
        {mode === "storage" && <StorageView filter={filter} />}
        {mode === "graph" && <GraphView filter={filter} />}
        {mode === "search" && <SearchView filter={filter} />}
      </div>
    </div>
  );
}
