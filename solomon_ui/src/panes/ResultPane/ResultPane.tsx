/**
 * 中央ペイン: タブバー + タブ内容 (Table / Dashboard / Summary / SQL / File)。
 * タブ状態は zustand の useTabStore に集約。
 */
import { useTabStore } from "../../stores/tabStore";
import { TabBar } from "./TabBar";
import { DashboardTab } from "./tabs/DashboardTab";
import { FilePreviewTab } from "./tabs/FilePreviewTab";
import { SQLTab } from "./tabs/SQLTab";
import { SummaryTab } from "./tabs/SummaryTab";
import { GraphTab } from "./tabs/GraphTab";
import { TablePreviewTab } from "./tabs/TablePreviewTab";
import { TablesTab } from "./tabs/TablesTab";
import { WelcomeTab } from "./tabs/WelcomeTab";

export function ResultPane() {
  const tabs = useTabStore((s) => s.tabs);
  const activeId = useTabStore((s) => s.activeId);
  const active = tabs.find((t) => t.id === activeId) ?? null;
  const isEmpty = tabs.length === 0;

  return (
    <div className={"result-pane" + (isEmpty ? " result-pane--empty" : "")}>
      <TabBar />
      <div className="pane-body result-body">
        {!active && <WelcomeTab />}
        {active && <TabRenderer tabId={active.id} />}
      </div>
    </div>
  );
}

function TabRenderer({ tabId }: { tabId: string }) {
  const tab = useTabStore((s) => s.tabs.find((t) => t.id === tabId));
  if (!tab) return null;
  switch (tab.kind) {
    case "welcome":
      return <WelcomeTab />;
    case "table_preview":
      return <TablePreviewTab tab={tab} />;
    case "dashboard":
      return <DashboardTab tab={tab} />;
    case "summary":
      return <SummaryTab tab={tab} />;
    case "sql":
      return <SQLTab tab={tab} />;
    case "file_preview":
      return <FilePreviewTab tab={tab} />;
    case "graph":
      return <GraphTab />;
    case "tables":
      return <TablesTab />;
    default:
      return <p className="placeholder">未対応のタブ種別</p>;
  }
}
