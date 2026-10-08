/**
 * タブバー。× でタブを閉じる。ドラッグ並び替えは v2 で。
 * radix-ui/react-tabs は使わず素直に div + button で作る (背景が動的で軽量なため)。
 */
import { useTabStore } from "../../stores/tabStore";
import { IconGraph, IconTables } from "../TreePane/ExplorerIcons";
import { FileTypeIcon } from "../TreePane/FileTypeIcon";
import { fileExtension } from "../TreePane/setiFileIcons";

const KIND_ICON: Record<string, string> = {
  table_preview: "▤",
  dashboard: "📊",
  summary: "📝",
  sql: "≡",
};

function filePreviewFilename(ref: Record<string, unknown>, title: string): string {
  const key = ref.key;
  if (typeof key === "string" && key.trim()) {
    const parts = key.split("/").filter(Boolean);
    return parts[parts.length - 1] ?? key;
  }
  return title;
}

function tabIcon(kind: string): string | null {
  if (kind in KIND_ICON) return KIND_ICON[kind];
  return "•";
}

export function TabBar() {
  const tabs = useTabStore((s) => s.tabs);
  const activeId = useTabStore((s) => s.activeId);
  const setActive = useTabStore((s) => s.setActive);
  const closeTab = useTabStore((s) => s.closeTab);

  if (tabs.length === 0) {
    return <div className="tab-bar tab-bar--empty" aria-hidden="true" />;
  }
  return (
    <div className="tab-bar">
      {tabs.map((t) => {
        const icon = tabIcon(t.kind);
        const isActive = t.id === activeId;
        const isFilePreview = t.kind === "file_preview";
        const label = isFilePreview
          ? filePreviewFilename(t.ref, t.title)
          : t.title;
        return (
          <div
            key={t.id}
            className={
              "tab-chip" +
              (isActive ? " tab-chip--active" : "") +
              (isFilePreview ? " tab-chip--file-preview" : "")
            }
            onClick={() => setActive(t.id)}
          >
            {t.kind === "graph" ? (
              <span className="tab-chip-icon tab-chip-icon--svg">
                <IconGraph active={isActive} />
              </span>
            ) : t.kind === "tables" ? (
              <span className="tab-chip-icon tab-chip-icon--svg">
                <IconTables active={isActive} />
              </span>
            ) : t.kind === "file_preview" ? (
              <span className="tab-chip-icon tab-chip-icon--seti">
                <FileTypeIcon
                  filename={label}
                  variant={
                    fileExtension(label) === "md" &&
                    t.ref.markdownView === "preview"
                      ? "markdown-preview"
                      : "default"
                  }
                  className="seti-file-icon tab-seti-file-icon"
                />
              </span>
            ) : icon ? (
              <span className="tab-chip-icon">{icon}</span>
            ) : null}
            <span className="tab-chip-title" title={label}>
              {label}
            </span>
            <button
              className="tab-chip-close"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(t.id);
              }}
              aria-label="Close tab"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
