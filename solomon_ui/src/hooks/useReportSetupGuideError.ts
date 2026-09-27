/**
 * TreePane 等で HTTP 503 (設定不足) を ChatPane の SetupGuide カードへ送る。
 */
import { useEffect } from "react";
import { isSetupGuideError } from "../api/client";
import { useChatStore } from "../stores/chatStore";

export function useReportSetupGuideError(error: unknown) {
  const setSetupError = useChatStore((s) => s.setSetupError);

  useEffect(() => {
    if (isSetupGuideError(error)) {
      setSetupError(error);
    }
  }, [error, setSetupError]);
}
