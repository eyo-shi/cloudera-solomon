import { useRightTabStore } from "../../stores/rightTabStore";

export function RightTabBar() {
  const tabs = useRightTabStore((s) => s.tabs);
  const activeId = useRightTabStore((s) => s.activeId);
  const setActive = useRightTabStore((s) => s.setActive);
  const closeTab = useRightTabStore((s) => s.closeTab);

  return (
    <div className="tab-bar tab-bar--right">
      {tabs.map((t) => {
        const isActive = t.id === activeId;
        return (
          <div
            key={t.id}
            className={"tab-chip" + (isActive ? " tab-chip--active" : "")}
            onClick={() => setActive(t.id)}
            role="tab"
            aria-selected={isActive}
          >
            {t.kind === "chat" && (
              <img
                src="/solomon_logo.svg"
                alt=""
                className="tab-chip-icon tab-chip-icon--logo"
              />
            )}
            <span className="tab-chip-title" title={t.title}>
              {t.title}
            </span>
            {!t.pinned && (
              <button
                type="button"
                className="tab-chip-close"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(t.id);
                }}
                aria-label="Close tab"
              >
                ×
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
