import {
  type FileIconVariant,
  resolveSetiFileIcon,
} from "./setiFileIcons";

interface FileTypeIconProps {
  filename: string;
  className?: string;
  variant?: FileIconVariant;
}

/** Cursor (Seti UI) 風のファイル種別アイコン。 */
export function FileTypeIcon({
  filename,
  className = "tree-icon seti-file-icon",
  variant = "default",
}: FileTypeIconProps) {
  const { glyph, color } = resolveSetiFileIcon(filename, variant);
  return (
    <span className={className} style={{ color }} aria-hidden="true">
      {glyph}
    </span>
  );
}
