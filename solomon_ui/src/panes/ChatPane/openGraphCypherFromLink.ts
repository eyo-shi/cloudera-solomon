import { useGraphStore } from "../../stores/graphStore";
import { normalizeSolomonHref } from "./solomonAppLinks";

const SCHEME = "solomon://graph-cypher";

const RESERVED_QUERY_KEYS = new Set(["cypher", "params", "run"]);

export function isGraphCypherLink(href: string | undefined): boolean {
  return Boolean(normalizeSolomonHref(href)?.startsWith(SCHEME));
}

export interface GraphCypherLinkPayload {
  cypher: string;
  runCypher?: string;
  params: Record<string, string | number | boolean>;
}

function mergeFlatParams(
  sp: URLSearchParams,
  params: Record<string, string | number | boolean>,
): Record<string, string | number | boolean> {
  const merged = { ...params };
  for (const [key, value] of sp.entries()) {
    if (RESERVED_QUERY_KEYS.has(key)) continue;
    merged[key] = value;
  }
  return merged;
}

export function parseGraphCypherLink(href: string): GraphCypherLinkPayload | null {
  const normalized = normalizeSolomonHref(href) ?? href;
  if (!normalized.startsWith(SCHEME)) return null;
  const query = normalized.includes("?")
    ? normalized.slice(normalized.indexOf("?") + 1)
    : "";
  const sp = new URLSearchParams(query);
  const cypher = sp.get("cypher");
  if (!cypher) return null;

  let params: Record<string, string | number | boolean> = {};
  const rawParams = sp.get("params");
  if (rawParams) {
    try {
      const parsed = JSON.parse(rawParams) as Record<string, unknown>;
      if (parsed && typeof parsed === "object") {
        params = Object.fromEntries(
          Object.entries(parsed).filter(
            ([, v]) =>
              typeof v === "string" ||
              typeof v === "number" ||
              typeof v === "boolean",
          ),
        ) as Record<string, string | number | boolean>;
      }
    } catch {
      /* JSON 破損時はフラットキーへフォールバック */
    }
  }
  params = mergeFlatParams(sp, params);

  const run = sp.get("run")?.trim();
  const runCypher =
    run && run !== cypher.trim() ? run : undefined;

  return { cypher, runCypher, params };
}

export function openGraphCypherFromLink(href: string): void {
  const payload = parseGraphCypherLink(href);
  if (!payload) return;
  useGraphStore
    .getState()
    .appendCypherQuery(payload.cypher, payload.params, payload.runCypher);
}
