/**
 * TreePane 等で HTTP 503 (設定不足) を ChatPane の SetupGuide カードへ送る。
 */
import { useEffect } from "react";
import { isSetupGuideError } from "../api/client";
import { useChatStore } from "../stores/chatStore";

export function useReportSetupGuideError(error: unknown) {
  const addSetupError = useChatStore((s) => s.addSetupError);

  useEffect(() => {
    if (isSetupGuideError(error)) {
      addSetupError(error);
    }
  }, [error, addSetupError]);
}
