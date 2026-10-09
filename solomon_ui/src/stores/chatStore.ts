/**
 * ChatPane のメッセージ / ステップ状態。
 * - messages: ユーザー / Solomon のバブル
 * - steps: 現在ターンのサブステップ (Router → 子 Crew の進捗)
 * - streaming: 送信中かどうか (Send ボタンの二重押し防止)
 */
import { create } from "zustand";
import type { SetupGuideError } from "../api/client";

export interface ChatAttachment {
  name: string;
  s3Uri?: string;
  size?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "solomon";
  text: string;
  attachments?: ChatAttachment[];
  /** Solomon 応答に artifact が付いていたときのタブへのジャンプ用 */
  artifactIds?: string[];
  /** エラーコード (Solomon 側) */
  errorCode?: string;
  errorMessage?: string;
  /** このターンの Router / Crew 実行ログ (SSE step) */
  activitySteps?: StepEntry[];
  createdAt: number;
}

export interface StepEntry {
  agent: string;
  status: "running" | "done" | "skipped" | "error";
  message: string;
  at: number;
}

interface ChatState {
  messages: ChatMessage[];
  steps: StepEntry[];
  streaming: boolean;
  /** TreePane 等から prompt を予約する。PromptInput が読み取って textarea に反映。 */
  pendingPrompt: string | null;
  /** Deploy 後の設定不足 (LLM / Trino / CDV 等) — ユーザーが ✕ するまで保持。 */
  setupErrors: SetupGuideError[];
  setPendingPrompt: (t: string | null) => void;
  appendUser: (text: string, attachments?: ChatAttachment[]) => string;
  appendSolomon: (text: string, opts?: { artifactIds?: string[]; errorCode?: string }) => string;
  appendToLastSolomon: (delta: string) => void;
  removeLastEmptySolomon: () => void;
  addStep: (step: StepEntry) => void;
  markLastRunningStepError: (message: string) => void;
  attachStepsToLastSolomon: () => void;
  setLastSolomonError: (errorCode: string, message: string) => void;
  clearSteps: () => void;
  setStreaming: (v: boolean) => void;
  addArtifactToLastSolomon: (artifactId: string) => void;
  addSetupError: (e: SetupGuideError) => void;
  removeSetupError: (errorCode: string) => void;
}

let _seq = 0;
const mid = () => {
  _seq += 1;
  return `m${_seq}-${Math.random().toString(36).slice(2, 6)}`;
};

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  steps: [],
  streaming: false,
  pendingPrompt: null,
  setupErrors: [],
  setPendingPrompt: (t) => set({ pendingPrompt: t }),
  addSetupError: (e) =>
    set((s) => {
      if (s.setupErrors.some((x) => x.errorCode === e.errorCode)) return s;
      return { setupErrors: [...s.setupErrors, e] };
    }),
  removeSetupError: (errorCode) =>
    set((s) => ({
      setupErrors: s.setupErrors.filter((x) => x.errorCode !== errorCode),
    })),
  appendUser: (text, attachments) => {
    const id = mid();
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id,
          role: "user",
          text,
          attachments: attachments?.length ? attachments : undefined,
          createdAt: Date.now(),
        },
      ],
    }));
    return id;
  },
  appendSolomon: (text, opts) => {
    const id = mid();
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id,
          role: "solomon",
          text,
          artifactIds: opts?.artifactIds ?? [],
          errorCode: opts?.errorCode,
          createdAt: Date.now(),
        },
      ],
    }));
    return id;
  },
  appendToLastSolomon: (delta) => {
    set((s) => {
      const idx = [...s.messages].reverse().findIndex((m) => m.role === "solomon");
      if (idx < 0) {
        const id = mid();
        return {
          messages: [
            ...s.messages,
            { id, role: "solomon", text: delta, createdAt: Date.now() },
          ],
        };
      }
      const realIdx = s.messages.length - 1 - idx;
      const next = [...s.messages];
      next[realIdx] = { ...next[realIdx], text: next[realIdx].text + delta };
      return { messages: next };
    });
  },
  removeLastEmptySolomon: () => {
    set((s) => {
      const idx = [...s.messages].reverse().findIndex((m) => m.role === "solomon");
      if (idx < 0) return s;
      const realIdx = s.messages.length - 1 - idx;
      if (s.messages[realIdx].text.trim()) return s;
      return { messages: s.messages.filter((_, i) => i !== realIdx) };
    });
  },
  addStep: (step) =>
    set((s) => {
      const idx = s.steps.findIndex((x) => x.agent === step.agent);
      if (idx >= 0) {
        const next = [...s.steps];
        next[idx] = step;
        return { steps: next };
      }
      return { steps: [...s.steps, step] };
    }),
  markLastRunningStepError: (message) =>
    set((s) => {
      let targetIdx = -1;
      for (let i = s.steps.length - 1; i >= 0; i -= 1) {
        if (s.steps[i].status === "running") {
          targetIdx = i;
          break;
        }
      }
      if (targetIdx < 0) return s;
      const next = [...s.steps];
      next[targetIdx] = {
        ...next[targetIdx],
        status: "error",
        message,
        at: Date.now(),
      };
      return { steps: next };
    }),
  attachStepsToLastSolomon: () =>
    set((s) => {
      if (s.steps.length === 0) return s;
      const idx = [...s.messages].reverse().findIndex((m) => m.role === "solomon");
      if (idx < 0) return { steps: [] };
      const realIdx = s.messages.length - 1 - idx;
      const nextMessages = [...s.messages];
      nextMessages[realIdx] = {
        ...nextMessages[realIdx],
        activitySteps: [...s.steps],
      };
      return { messages: nextMessages, steps: [] };
    }),
  setLastSolomonError: (errorCode, message) =>
    set((s) => {
      const idx = [...s.messages].reverse().findIndex((m) => m.role === "solomon");
      if (idx < 0) return s;
      const realIdx = s.messages.length - 1 - idx;
      const next = [...s.messages];
      next[realIdx] = {
        ...next[realIdx],
        errorCode,
        errorMessage: message,
      };
      return { messages: next };
    }),
  clearSteps: () => set({ steps: [] }),
  setStreaming: (v) => set({ streaming: v }),
  addArtifactToLastSolomon: (artifactId) => {
    set((s) => {
      const idx = [...s.messages].reverse().findIndex((m) => m.role === "solomon");
      if (idx < 0) return s;
      const realIdx = s.messages.length - 1 - idx;
      const target = s.messages[realIdx];
      const existing = target.artifactIds ?? [];
      if (existing.includes(artifactId)) return s;
      const next = [...s.messages];
      next[realIdx] = { ...target, artifactIds: [...existing, artifactId] };
      return { messages: next };
    });
  },
}));
