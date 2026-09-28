/** Explorer 上部ツールバー用アイコン */

function toolbarIconClass(active?: boolean) {
  return "explorer-icon" + (active ? " explorer-icon--active" : "");
}

export function IconTables({ active }: { active?: boolean }) {
  return (
    <svg className={toolbarIconClass(active)} viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2" y="2" width="12" height="12" rx="1.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <path d="M2 6h12M2 10h12M6 2v12M10 2v12" stroke="currentColor" strokeWidth="0.875" />
    </svg>
  );
}

export function IconStorage({ active }: { active?: boolean }) {
  return (
    <svg className={toolbarIconClass(active)} viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M2.5 5.5 4 4h3.5L9 5.5H13.5V12a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V5.5z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinejoin="round"
      />
    </svg>
  );
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
  return (
    <svg className={toolbarIconClass(active)} viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="4.25" cy="4.25" r="1.75" fill="none" stroke="currentColor" strokeWidth="1" />
      <circle cx="11.75" cy="4.25" r="1.75" fill="none" stroke="currentColor" strokeWidth="1" />
      <circle cx="8" cy="11.75" r="1.75" fill="none" stroke="currentColor" strokeWidth="1" />
      <path
        d="M5.75 5.5 7.25 10M10.25 5.5 8.75 10"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function IconSemanticSearch({ active }: { active?: boolean }) {
  return (
    <svg className={toolbarIconClass(active)} viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="7" cy="7" r="4.25" fill="none" stroke="currentColor" strokeWidth="1" />
      <path d="M10.25 10.25 13.5 13.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
    </svg>
  );
}

export function IconSearch() {
  return (
    <svg className="explorer-search-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}

/** 展開/折りたたみ chevron — Graph 結果パネルと Storage ツリーで共用。 */
export function IconChevronToggle({
  expanded,
  className = "tree-caret-icon",
}: {
  expanded: boolean;
  className?: string;
}) {
  return (
    <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
      <path
        d={expanded ? "M4 10l4-4 4 4" : "M4 6l4 4 4-4"}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
