/**
 * ChatPane から SSE `/api/wish` を叩き、Store を更新する hook。
 *
 * - Store 経由で MessageList / StepIndicator / TabBar が反応する
 * - 送信中は AbortController を保持して cancel() を露出
 * - artifact イベントが来たら zustand tabStore に自動でタブを追加
 *   (title / kind / ref はサーバから来た値を使う)
 */
import { useCallback, useRef } from "react";
import { SetupGuideError } from "../../api/client";
import { uploadChatFile } from "../../api/files";
import { streamWish } from "../../api/wish";
import { useChatStore, type ChatAttachment } from "../../stores/chatStore";
import { useSessionStore } from "../../stores/sessionStore";
import { useTabStore } from "../../stores/tabStore";
import type { ArtifactType, WishEvent } from "../../types";

export interface UseWishStream {
  send: (prompt: string, files?: File[]) => Promise<void>;
  cancel: () => void;
}

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return true;
  return err instanceof Error && err.name === "AbortError";
}

export function useWishStream(): UseWishStream {
  const controllerRef = useRef<AbortController | null>(null);
  const userCancelledRef = useRef(false);
  const appendUser = useChatStore((s) => s.appendUser);
  const appendSolomon = useChatStore((s) => s.appendSolomon);
  const appendToLastSolomon = useChatStore((s) => s.appendToLastSolomon);
  const removeLastEmptySolomon = useChatStore((s) => s.removeLastEmptySolomon);
  const addStep = useChatStore((s) => s.addStep);
  const clearSteps = useChatStore((s) => s.clearSteps);
  const setStreaming = useChatStore((s) => s.setStreaming);
  const addArtifactToLastSolomon = useChatStore((s) => s.addArtifactToLastSolomon);
  const addSetupError = useChatStore((s) => s.addSetupError);
  const openTab = useTabStore((s) => s.openTab);
  const sessionId = useSessionStore((s) => s.sessionId);

  const cancel = useCallback(() => {
    userCancelledRef.current = true;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setStreaming(false);
    clearSteps();
  }, [clearSteps, setStreaming]);

  const send = useCallback(
    async (prompt: string, files: File[] = []) => {
      const trimmed = prompt.trim();
      if (!trimmed && files.length === 0) return;

      clearSteps();
      setStreaming(true);
      userCancelledRef.current = false;

      const controller = new AbortController();
      controllerRef.current = controller;

      let uploaded: ChatAttachment[] = [];
      if (files.length > 0) {
        try {
          const results = await Promise.all(
            files.map((file) => uploadChatFile(file)),
          );
          uploaded = results.map((r) => ({
            name: r.name,
            s3Uri: r.s3_uri,
            size: r.size,
          }));
        } catch (e) {
          setStreaming(false);
          controllerRef.current = null;
          const msg = e instanceof Error ? e.message : String(e);
          appendUser(trimmed || "(ファイル添付)", []);
          appendSolomon(`ファイルのアップロードに失敗しました。\n\n${msg}`);
          return;
        }
      }

      const finalPrompt = buildPromptWithAttachments(trimmed, uploaded);
      appendUser(finalPrompt, uploaded);
      appendSolomon("");

      await streamWish(
        { prompt: finalPrompt, session_id: sessionId ?? undefined },
        {
          signal: controller.signal,
          onEvent: (evt: WishEvent) => {
            switch (evt.event) {
              case "step":
                addStep({
                  agent: evt.data.agent,
                  status: evt.data.status,
                  message: evt.data.message,
                  at: Date.now(),
                });
                break;
              case "token":
                appendToLastSolomon(evt.data.delta);
                break;
              case "artifact":
                addArtifactToLastSolomon(evt.data.id);
                openTab({
                  title: titleFor(evt.data.type, evt.data.ref),
                  kind: evt.data.type,
                  ref: { ...evt.data.ref, artifact_id: evt.data.id },
                  dedupeKey: `art:${evt.data.id}`,
                });
                break;
              case "error":
                appendToLastSolomon(
                  `\n\n[${evt.data.error_code}] ${evt.data.message}`,
                );
                break;
              case "done":
                // タブは既に開いているので特に何もしない
                break;
            }
          },
          onSetupGuide: (e) => {
            // LLM / Trino 未設定などの 503 は SetupGuide カードで表示する。
            // 中身の空 Solomon バブルは残ってしまうと違和感が強いので、
            // このバブルにも短い案内を書いて紐付けを分かりやすくする。
            addSetupError(e);
            appendToLastSolomon(
              `\n\n[${e.errorCode}] ${e.message}\n\n(設定手順は下のカードを参照)`,
            );
          },
          onError: (e) => {
            if (isAbortError(e) || userCancelledRef.current) {
              return;
            }
            if (e instanceof SetupGuideError) {
              addSetupError(e);
              appendToLastSolomon(
                `\n\n[${e.errorCode}] ${e.message}\n\n(設定手順は下のカードを参照)`,
              );
              return;
            }
            appendToLastSolomon(`\n\n[STREAM_ERROR] ${String(e)}`);
          },
          onClose: () => {
            setStreaming(false);
            controllerRef.current = null;
            if (userCancelledRef.current) {
              removeLastEmptySolomon();
              userCancelledRef.current = false;
              return;
            }
            // token / error が 1 件も来ず空バブルのまま終わった場合のフォールバック
            const lastSolomon = [...useChatStore.getState().messages]
              .reverse()
              .find((m) => m.role === "solomon");
            if (lastSolomon && !lastSolomon.text.trim()) {
              appendToLastSolomon(
                "応答を表示できませんでした。ページを再読み込みするか、Application を再起動してください。",
              );
            }
          },
        },
      );
    },
    [
      appendUser,
      appendSolomon,
      appendToLastSolomon,
      removeLastEmptySolomon,
      addStep,
      addArtifactToLastSolomon,
      clearSteps,
      setStreaming,
      addSetupError,
      sessionId,
      openTab,
    ],
  );

  return { send, cancel };
}

function buildPromptWithAttachments(
  prompt: string,
  attachments: ChatAttachment[],
): string {
  const uris = attachments
    .map((a) => a.s3Uri)
    .filter((uri): uri is string => Boolean(uri));
  if (!uris.length) return prompt;

  const uriBlock = uris.map((uri) => `- ${uri}`).join("\n");
  if (prompt) {
    return `${prompt}\n\n添付ファイル:\n${uriBlock}`;
  }
  if (uris.length === 1) {
    return `${uris[0]} を取り込んでナレッジグラフに追加して`;
  }
  return `以下のファイルを取り込んでテーブルを作って:\n${uriBlock}`;
}

function titleFor(kind: ArtifactType, ref: Record<string, unknown>): string {
  switch (kind) {
    case "table_preview":
      return String(ref.fq ?? "Table").split(".").slice(-1)[0] || "Table";
    case "dashboard":
      return String(ref.title ?? "Dashboard");
    case "summary":
      return String(ref.title ?? "Summary");
    case "sql":
      return "SQL";
    case "file_preview":
      return String(ref.key ?? "File").split("/").slice(-1)[0] || "File";
    case "graph":
      return String(ref.title ?? "Graph");
    default:
      return "Result";
  }
}
