import { resolveSetiFileIcon } from "./setiFileIcons";

interface FileTypeIconProps {
  filename: string;
  className?: string;
}

/** Cursor (Seti UI) 風のファイル種別アイコン。 */
export function FileTypeIcon({
  filename,
  className = "tree-icon seti-file-icon",
}: FileTypeIconProps) {
  const { glyph, color } = resolveSetiFileIcon(filename);
  return (
    <span className={className} style={{ color }} aria-hidden="true">
      {glyph}
    </span>
  );
}
