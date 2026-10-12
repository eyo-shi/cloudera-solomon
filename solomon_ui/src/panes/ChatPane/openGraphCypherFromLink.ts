import { useGraphStore } from "../../stores/graphStore";

const SCHEME = "solomon://graph-cypher";

export function isGraphCypherLink(href: string | undefined): boolean {
  return Boolean(href?.startsWith(SCHEME));
}

export interface GraphCypherLinkPayload {
  cypher: string;
  params: Record<string, string | number | boolean>;
}

export function parseGraphCypherLink(href: string): GraphCypherLinkPayload | null {
  if (!href.startsWith(SCHEME)) return null;
  const query = href.includes("?") ? href.slice(href.indexOf("?") + 1) : "";
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
      /* ignore malformed params */
    }
  }
  return { cypher, params };
}

export function openGraphCypherFromLink(href: string): void {
  const payload = parseGraphCypherLink(href);
  if (!payload) return;
  useGraphStore.getState().appendCypherQuery(payload.cypher, payload.params);
}
