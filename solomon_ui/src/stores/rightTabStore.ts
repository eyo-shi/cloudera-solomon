/**
 * 右ペイン (Agent / Chat) のタブ。中央 ResultPane の tabStore とは独立。
 */
import { create } from "zustand";
import type { RightTabDescriptor } from "../types";

const DEFAULT_CHAT_TAB: RightTabDescriptor = {
  id: "chat-main",
  title: "Solomon",
  kind: "chat",
  pinned: true,
};

interface RightTabState {
  tabs: RightTabDescriptor[];
  activeId: string;
  setActive: (id: string) => void;
  closeTab: (id: string) => void;
  ensureDefaults: () => void;
}

export const useRightTabStore = create<RightTabState>((set, get) => ({
  tabs: [DEFAULT_CHAT_TAB],
  activeId: DEFAULT_CHAT_TAB.id,
  setActive: (id) => {
    if (get().tabs.some((t) => t.id === id)) {
      set({ activeId: id });
    }
  },
  closeTab: (id) => {
    set((s) => {
      const target = s.tabs.find((t) => t.id === id);
      if (!target || target.pinned || s.tabs.length <= 1) return s;
      const nextTabs = s.tabs.filter((t) => t.id !== id);
      let nextActive = s.activeId;
      if (s.activeId === id) {
        const idx = s.tabs.findIndex((t) => t.id === id);
        nextActive =
          nextTabs[idx]?.id ?? nextTabs[idx - 1]?.id ?? nextTabs[0]?.id ?? s.activeId;
      }
      return { tabs: nextTabs, activeId: nextActive };
    });
  },
  ensureDefaults: () => {
    const { tabs } = get();
    if (tabs.length === 0) {
      set({ tabs: [DEFAULT_CHAT_TAB], activeId: DEFAULT_CHAT_TAB.id });
    }
  },
}));
