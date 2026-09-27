/**
 * ChatPane のメッセージ履歴。user/solomon バブル、artifact ジャンプ、error 色分け。
 */
import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChatStore } from "../../stores/chatStore";
import { useTabStore } from "../../stores/tabStore";

export function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const setActive = useTabStore((s) => s.setActive);
  const tabs = useTabStore((s) => s.tabs);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

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
      {messages.map((m) => (
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
              <div className="markdown-body chat-md">
                <Markdown remarkPlugins={[remarkGfm]}>{m.text || " "}</Markdown>
              </div>
              {m.artifactIds && m.artifactIds.length > 0 && (
                <div className="chat-artifacts">
                  {m.artifactIds.map((aid) => {
                    const tab = tabs.find(
                      (t) => t.ref && (t.ref as any).artifact_id === aid,
                    );
                    if (!tab) return null;
                    return (
                      <button
                        key={aid}
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
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
