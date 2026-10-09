/**
 * ChatPane のメッセージ履歴。user/solomon バブル、artifact ジャンプ、error 色分け。
 */
import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChatStore } from "../../stores/chatStore";
import { useTabStore } from "../../stores/tabStore";
import { ActivityTimeline } from "./ActivityTimeline";

export function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const liveSteps = useChatStore((s) => s.steps);
  const liveNarratives = useChatStore((s) => s.narratives);
  const streaming = useChatStore((s) => s.streaming);
  const setActive = useTabStore((s) => s.setActive);
  const tabs = useTabStore((s) => s.tabs);
  const bottomRef = useRef<HTMLDivElement>(null);

  const lastSolomonId = [...messages].reverse().find((m) => m.role === "solomon")?.id;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, liveSteps.length, liveNarratives.length, streaming]);

  if (messages.length === 0) {
    return (
      <div className="chat-empty">
        <p className="chat-empty__title">Solomon</p>
        <p className="chat-empty__hint">
          自然言語でデータ操作を依頼できます。
        </p>
      </div>
    );
  }

  return (
    <div className="chat-messages">
      {messages.map((m) => {
        const isLiveTurn = streaming && m.id === lastSolomonId && m.role === "solomon";
        const steps =
          isLiveTurn && liveSteps.length > 0
            ? liveSteps
            : (m.activitySteps ?? []);
        const narratives =
          isLiveTurn && liveNarratives.length > 0
            ? liveNarratives
            : (m.activityNarratives ?? []);
        const showTimeline = steps.length > 0 || narratives.length > 0;
        const allSettled =
          steps.length > 0 &&
          steps.every((s) => s.status === "done" || s.status === "skipped");
        const text = m.text?.trim() ?? "";
        const collapseThinking = Boolean(text) && (isLiveTurn || allSettled);

        return (
          <div
            key={m.id}
            className={
              "chat-turn chat-turn--" +
              m.role +
              (m.errorCode ? " chat-turn--error" : "")
            }
          >
            {m.role === "solomon" ? (
              <div className="chat-turn__assistant">
                {showTimeline && (
                  <ActivityTimeline
                    steps={steps}
                    narratives={narratives}
                    live={isLiveTurn}
                    defaultCollapsed={collapseThinking || (!isLiveTurn && allSettled)}
                    collapseWhenResult={isLiveTurn && Boolean(text)}
                  />
                )}
                {m.errorCode && (
                  <div className="chat-error-banner" role="alert">
                    <span className="chat-error-banner__code">{m.errorCode}</span>
                    <span className="chat-error-banner__text">
                      {m.errorMessage ?? text}
                    </span>
                  </div>
                )}
                {text && !m.errorCode && (
                  <div className="markdown-body chat-md">
                    <Markdown remarkPlugins={[remarkGfm]}>{m.text}</Markdown>
                  </div>
                )}
                {text && m.errorCode && m.errorMessage && text !== m.errorMessage && (
                  <div className="markdown-body chat-md chat-md--after-error">
                    <Markdown remarkPlugins={[remarkGfm]}>{m.text}</Markdown>
                  </div>
                )}
                {m.artifactIds && m.artifactIds.length > 0 && (
                  <div className="chat-artifacts">
                    {m.artifactIds.map((aid) => {
                      const tab = tabs.find(
                        (t) => t.ref && (t.ref as { artifact_id?: string }).artifact_id === aid,
                      );
                      if (!tab) return null;
                      return (
                        <button
                          key={aid}
                          type="button"
                          className="chat-artifact-link"
                          onClick={() => setActive(tab.id)}
                        >
                          中央ペインで開く: {tab.title}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
              <div className="chat-turn__user-bubble">
                {m.text && <p>{m.text}</p>}
                {m.attachments && m.attachments.length > 0 && (
                  <ul className="chat-turn__attachments">
                    {m.attachments.map((a) => (
                      <li key={`${a.name}-${a.s3Uri ?? "local"}`}>
                        📎 {a.name}
                        {a.s3Uri && (
                          <span className="chat-turn__attachment-uri">{a.s3Uri}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
