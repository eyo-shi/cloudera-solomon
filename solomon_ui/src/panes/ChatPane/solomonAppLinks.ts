import { defaultUrlTransform } from "react-markdown";

export const SOLOMON_SCHEME = "solomon://";

/** react-markdown 9 の defaultUrlTransform は solomon:// を空文字にする。 */
export function preserveSolomonUrlTransform(url: string): string {
  const trimmed = url.trim();
  if (trimmed.startsWith(SOLOMON_SCHEME)) {
    return trimmed;
  }
  return defaultUrlTransform(url);
}

export function normalizeSolomonHref(
  href: string | undefined,
): string | undefined {
  if (!href) return href;
  const trimmed = href.trim();
  if (!trimmed.startsWith(SOLOMON_SCHEME)) {
    return trimmed;
  }
  try {
    return decodeURI(trimmed);
  } catch {
    return trimmed;
  }
}

export function isSolomonAppLink(href: string | undefined): boolean {
  return Boolean(normalizeSolomonHref(href)?.startsWith(SOLOMON_SCHEME));
}
