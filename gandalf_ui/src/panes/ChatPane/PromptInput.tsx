/**
 * multiline prompt 入力。Ctrl+Enter (Mac は Cmd+Enter) で Send。
 * streaming 中は Send が Cancel に切り替わる。
 */
import { useEffect, useState } from "react";
import { useChatStore } from "../../stores/chatStore";
import type { UseWishStream } from "./useWishStream";

interface Props {
  wish: UseWishStream;
}

export function PromptInput({ wish }: Props) {
  const [text, setText] = useState("");
  const streaming = useChatStore((s) => s.streaming);
  const pendingPrompt = useChatStore((s) => s.pendingPrompt);
  const setPendingPrompt = useChatStore((s) => s.setPendingPrompt);

  // TreePane 等からの予約プロンプトを textarea に反映する
  useEffect(() => {
    if (pendingPrompt != null) {
      setText(pendingPrompt);
      setPendingPrompt(null);
    }
  }, [pendingPrompt, setPendingPrompt]);

  async function submit() {
    const t = text.trim();
    if (!t) return;
    setText("");
    await wish.send(t);
  }

  return (
    <div className="chat-composer">
      <div className="chat-composer__box">
        <textarea
          className="chat-composer__input"
          placeholder="Plan, @ for context, / for commands"
          rows={3}
          value={text}
          disabled={streaming}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <div className="chat-composer__toolbar">
          <span className="chat-composer__hint">
            {streaming ? "Generating…" : "Enter で送信 · Shift+Enter で改行"}
          </span>
          {streaming ? (
            <button
              type="button"
              className="chat-composer__btn chat-composer__btn--cancel"
              aria-label="停止"
              title="停止"
              onClick={() => wish.cancel()}
            >
              <IconStop />
            </button>
          ) : (
            <button
              type="button"
              className="chat-composer__btn chat-composer__btn--send"
              aria-label="送信"
              title="送信"
              onClick={() => void submit()}
              disabled={!text.trim()}
            >
              <IconSend />
            </button>
          )}
        </div>
      </div>
      <p className="chat-composer__disclaimer">
        AI-generated results may be incorrect. Please exercise caution.
      </p>
    </div>
  );
}

function IconSend() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="chat-composer__icon">
      <path
        d="M12 19V5M5 12l7-7 7 7"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconStop() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="chat-composer__icon">
      <rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor" />
    </svg>
  );
}
