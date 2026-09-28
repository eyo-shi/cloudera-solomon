/**
 * Cursor (Seti UI) ファイルアイコン — theme-seti の glyph / 色を再現。
 * @see /Applications/Cursor.app/.../theme-seti/icons/vs-seti-icon-theme.json
 */

interface SetiIconDef {
  glyph: string;
  color: string;
}

function glyph(codePoint: number): string {
  return String.fromCharCode(codePoint);
}

/** Seti UI icon definitions (light theme colors). */
const SETI: Record<string, SetiIconDef> = {
  csv: { glyph: glyph(0xe01e), color: "#7fae42" },
  json: { glyph: glyph(0xe055), color: "#b7b73b" },
  xls: { glyph: glyph(0xe0a4), color: "#7fae42" },
  db: { glyph: glyph(0xe022), color: "#dd4b78" },
  zip: { glyph: glyph(0xe0a9), color: "#b8383d" },
  markdown: { glyph: glyph(0xe060), color: "#498ba7" },
  pdf: { glyph: glyph(0xe06d), color: "#b8383d" },
  image: { glyph: glyph(0xe04c), color: "#9068b0" },
  default: { glyph: glyph(0xe023), color: "#bfc2c1" },
};

/** 拡張子 → Seti アイコン種別 (Cursor fileExtensions に準拠)。 */
const EXT_ICON: Record<string, keyof typeof SETI> = {
  csv: "csv",
  tsv: "csv",
  json: "json",
  jsonl: "json",
  xls: "xls",
  xlsx: "xls",
  parquet: "db",
  orc: "db",
  avro: "json",
  txt: "default",
  md: "markdown",
  pdf: "pdf",
  zip: "zip",
  gz: "zip",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
};

export function fileExtension(filename: string): string {
  const base = filename.split("/").pop() ?? filename;
  const dot = base.lastIndexOf(".");
  if (dot <= 0) return "";
  return base.slice(dot + 1).toLowerCase();
}

export function resolveSetiFileIcon(filename: string): SetiIconDef {
  const ext = fileExtension(filename);
  const key = ext ? EXT_ICON[ext] : undefined;
  return SETI[key ?? "default"];
}
