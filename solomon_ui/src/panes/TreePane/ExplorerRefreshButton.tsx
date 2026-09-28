/** Explorer セクションヘッダー用の更新ボタン。 */
interface Props {
  onRefresh: () => void;
  isFetching?: boolean;
  label?: string;
}

function IconRefresh() {
  return (
    <svg className="explorer-refresh-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M13.5 8A5.5 5.5 0 0 1 3.6 10.5M2.5 8A5.5 5.5 0 0 1 12.4 5.5M2.5 5.5V2.5h3M13.5 10.5v3h-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ExplorerRefreshButton({
  onRefresh,
  isFetching = false,
  label = "Refresh",
}: Props) {
  return (
    <button
      type="button"
      className={
        "explorer-action-btn" + (isFetching ? " explorer-action-btn--spinning" : "")
      }
      aria-label={label}
      title={label}
      disabled={isFetching}
      onClick={() => onRefresh()}
    >
      <IconRefresh />
    </button>
  );
}
