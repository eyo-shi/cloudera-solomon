/** Explorer 上部ツールバー用アイコン */

const EXPLORER_ICONS = {
  tables: "/explorer/tables.png",
  storage: "/explorer/storage.png",
  graph: "/explorer/graph.png",
  search: "/explorer/search.png",
} as const;

function ExplorerToolbarIcon({
  src,
  active,
}: {
  src: string;
  active?: boolean;
}) {
  return (
    <img
      src={src}
      alt=""
      className={"explorer-icon" + (active ? " explorer-icon--active" : "")}
      aria-hidden="true"
    />
  );
}

export function IconTables({ active }: { active?: boolean }) {
  return <ExplorerToolbarIcon src={EXPLORER_ICONS.tables} active={active} />;
}

export function IconStorage({ active }: { active?: boolean }) {
  return <ExplorerToolbarIcon src={EXPLORER_ICONS.storage} active={active} />;
}

export function IconTableGrid() {
  return (
    <svg className="explorer-table-icon" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2" y="2" width="12" height="12" rx="1" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <path d="M2 6h12M2 10h12M6 2v12M10 2v12" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

export function IconDatabase() {
  return (
    <svg className="explorer-breadcrumb-icon" viewBox="0 0 16 16" aria-hidden="true">
      <ellipse cx="8" cy="4" rx="5" ry="1.75" fill="currentColor" />
      <path d="M3 4v4c0 .97 2.24 1.75 5 1.75s5-.78 5-1.75V4" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <path d="M3 8v4c0 .97 2.24 1.75 5 1.75s5-.78 5-1.75V8" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  );
}

export function IconGraph({ active }: { active?: boolean }) {
  return <ExplorerToolbarIcon src={EXPLORER_ICONS.graph} active={active} />;
}

export function IconSemanticSearch({ active }: { active?: boolean }) {
  return <ExplorerToolbarIcon src={EXPLORER_ICONS.search} active={active} />;
}

export function IconSearch() {
  return (
    <svg className="explorer-search-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}
