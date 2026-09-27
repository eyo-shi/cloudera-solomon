/**
 * 右ペイン: エージェント対話。
 * SSE で流れてくる step / token / artifact / error / done を Store に反映し、
 * MessageList / StepIndicator が render する。
 *
 * Deploy 後の設定不足 (LLM / Trino / CDV) を示す HTTP 503 が返った場合は、
 * chatStore.setupErrors に格納された :class:`SetupGuideError` を SetupGuide
 * カードとして表示し、Project → Settings → Environment で env を追加して
 * Application を再起動する手順を提示する。カードはユーザーが ✕ するまで残る。
 */
import { useLlmSetupProbe } from "../../api/setup";
import { useReportSetupGuideError } from "../../hooks/useReportSetupGuideError";
import { useChatStore } from "../../stores/chatStore";
import { MessageList } from "./MessageList";
import { PromptInput } from "./PromptInput";
import { SetupGuide } from "./SetupGuide";
import { StepIndicator } from "./StepIndicator";
import { useWishStream } from "./useWishStream";

export function ChatPane() {
  const wish = useWishStream();
  const { error: llmSetupError } = useLlmSetupProbe();
  useReportSetupGuideError(llmSetupError);
  const setupErrors = useChatStore((s) => s.setupErrors);
  const removeSetupError = useChatStore((s) => s.removeSetupError);
  return (
    <div className="chat-pane">
      <div className="chat-pane__header">
        <div className="chat-pane__header-brand">
          <img
            src="/solomon_logo.svg"
            alt=""
            className="chat-pane__header-icon"
          />
          <span className="chat-pane__header-title">Solomon</span>
        </div>
        <span className="chat-pane__header-hint">Agent</span>
      </div>
      <div className="chat-scroll">
        <MessageList />
        <StepIndicator />
        {setupErrors.map((error) => (
          <SetupGuide
            key={error.errorCode}
            error={error}
            onDismiss={() => removeSetupError(error.errorCode)}
          />
        ))}
      </div>
      <PromptInput wish={wish} />
    </div>
  );
}
