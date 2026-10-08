import { useState } from "react";

/**
 * 左ペイン: データ Explorer（Tables / Storage / Graph / Search 切替）。
 *
 * 上部アイコンで各データソースを切替。
 * Search タブ: アイコンのみ。ツールチップ / aria-label は "Semantic Search"。
 */
import { useExplorerStore, type ExplorerMode } from "../../stores/explorerStore";
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

export type { ExplorerMode };

const SEARCH_PLACEHOLDERS: Record<ExplorerMode, string> = {
  tables: "Search SQL tables…",
  storage: "Search storage…",
  graph: "Search graph nodes…",
  search: "Search indexed documents…",
};

export function TreePane() {
  const mode = useExplorerStore((s) => s.mode);
  const setMode = useExplorerStore((s) => s.setMode);
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
            "explorer-toolbar__btn" +
            (mode === "search" ? " explorer-toolbar__btn--active" : "")
          }
          aria-label="Semantic Search"
          title="Semantic Search"
          onClick={() => setMode("search")}
        >
          <IconSemanticSearch active={mode === "search"} />
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
        {/* モード切替でアンマウントしない (Storage のフォルダ展開状態を保持) */}
        <section
          className="explorer-panel"
          aria-hidden={mode !== "tables"}
          hidden={mode !== "tables"}
        >
          <ExploreView filter={filter} />
        </section>
        <section
          className="explorer-panel"
          aria-hidden={mode !== "storage"}
          hidden={mode !== "storage"}
        >
          <StorageView filter={filter} />
        </section>
        <section
          className="explorer-panel"
          aria-hidden={mode !== "graph"}
          hidden={mode !== "graph"}
        >
          <GraphView filter={filter} />
        </section>
        <section
          className="explorer-panel"
          aria-hidden={mode !== "search"}
          hidden={mode !== "search"}
        >
          <SearchView filter={filter} />
        </section>
      </div>
    </div>
  );
}
