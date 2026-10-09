/** Storage / タブ用 — PDF と一目で分かるアイコン (Seti フォントに依存しない)。 */
export function PdfFileIcon({ className = "tree-icon pdf-file-icon" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M4.5 1.75h4.25L12.5 5.5V13a1.25 1.25 0 0 1-1.25 1.25H4.5A1.25 1.25 0 0 1 3.25 13V3A1.25 1.25 0 0 1 4.5 1.75Z"
        fill="#fef2f2"
        stroke="#dc2626"
        strokeWidth="1"
        strokeLinejoin="round"
      />
      <path
        d="M8.75 1.75V5.5H12.5"
        fill="none"
        stroke="#dc2626"
        strokeWidth="1"
        strokeLinejoin="round"
      />
      <text
        x="8"
        y="11.25"
        textAnchor="middle"
        fontSize="4.5"
        fontWeight="700"
        fontFamily="system-ui, sans-serif"
        fill="#b91c1c"
      >
        PDF
      </text>
    </svg>
  );
}
