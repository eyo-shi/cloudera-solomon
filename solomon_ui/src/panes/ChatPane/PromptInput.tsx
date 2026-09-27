/**
 * multiline prompt 入力。Enter で Send、Shift+Enter で改行。
 * クリップアイコン / ドラッグ&ドロップでファイル添付。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useChatStore } from "../../stores/chatStore";
import type { UseWishStream } from "./useWishStream";

const MAX_ATTACHMENTS = 5;
const ACCEPTED_FILE_TYPES =
  ".csv,.tsv,.txt,.json,.jsonl,.xlsx,.xls,.parquet,.orc,.avro,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv";

interface LocalAttachment {
  id: string;
  file: File;
}

interface Props {
  wish: UseWishStream;
}

export function PromptInput({ wish }: Props) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<LocalAttachment[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const streaming = useChatStore((s) => s.streaming);
  const pendingPrompt = useChatStore((s) => s.pendingPrompt);
  const setPendingPrompt = useChatStore((s) => s.setPendingPrompt);

  useEffect(() => {
    if (pendingPrompt != null) {
      setText(pendingPrompt);
      setPendingPrompt(null);
    }
  }, [pendingPrompt, setPendingPrompt]);

  const addFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files).filter((f) => f.size > 0);
    if (!incoming.length) return;
    setAttachments((prev) => {
      const seen = new Set(prev.map((a) => `${a.file.name}:${a.file.size}`));
      const next = [...prev];
      for (const file of incoming) {
        if (next.length >= MAX_ATTACHMENTS) break;
        const key = `${file.name}:${file.size}`;
        if (seen.has(key)) continue;
        seen.add(key);
        next.push({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          file,
        });
      }
      return next;
    });
  }, []);

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  async function submit() {
    const t = text.trim();
    if (!t && attachments.length === 0) return;
    const files = attachments.map((a) => a.file);
    setText("");
    setAttachments([]);
    await wish.send(t, files);
  }

  const canSend = Boolean(text.trim() || attachments.length) && !streaming;

  return (
    <div className="chat-composer">
      <div
        className={
          "chat-composer__box" +
          (dragOver ? " chat-composer__box--dragover" : "")
        }
        onDragEnter={(e) => {
          e.preventDefault();
          if (!streaming) setDragOver(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!streaming) setDragOver(true);
        }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node)) return;
          setDragOver(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (streaming) return;
          addFiles(e.dataTransfer.files);
        }}
      >
        {dragOver && (
          <div className="chat-composer__drop-overlay" aria-hidden="true">
            ファイルをドロップして添付
          </div>
        )}
        {attachments.length > 0 && (
          <ul className="chat-composer__attachments">
            {attachments.map((a) => (
              <li key={a.id} className="chat-composer__attachment">
                <span className="chat-composer__attachment-name" title={a.file.name}>
                  {a.file.name}
                </span>
                <span className="chat-composer__attachment-size">
                  {formatBytes(a.file.size)}
                </span>
                <button
                  type="button"
                  className="chat-composer__attachment-remove"
                  aria-label={`${a.file.name} を削除`}
                  disabled={streaming}
                  onClick={() => removeAttachment(a.id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
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
              if (canSend) void submit();
            }
          }}
        />
        <div className="chat-composer__toolbar">
          <span className="chat-composer__hint">
            {streaming
              ? "Generating…"
              : "Enter で送信 · Shift+Enter で改行 · ファイル D&D 可"}
          </span>
          <div className="chat-composer__actions">
            <input
              ref={fileInputRef}
              type="file"
              className="chat-composer__file-input"
              accept={ACCEPTED_FILE_TYPES}
              multiple
              disabled={streaming}
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              className="chat-composer__btn chat-composer__btn--attach"
              aria-label="ファイルを添付"
              title="ファイルを添付"
              disabled={streaming || attachments.length >= MAX_ATTACHMENTS}
              onClick={() => fileInputRef.current?.click()}
            >
              <img
                src="/chat/paperclip.png"
                alt=""
                className="chat-composer__attach-icon"
                aria-hidden="true"
              />
            </button>
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
                disabled={!canSend}
              >
                <IconSend />
              </button>
            )}
          </div>
        </div>
      </div>
      <p className="chat-composer__disclaimer">
        AI-generated results may be incorrect. Please exercise caution.
      </p>
    </div>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
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
