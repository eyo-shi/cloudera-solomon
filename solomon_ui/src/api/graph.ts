import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type {
  GraphQueryResponse,
  GraphQueryType,
  GraphSchemaResponse,
} from "../types";

export function useGraphSchema() {
  return useQuery({
    queryKey: ["graph", "schema"],
    queryFn: () => apiFetch<GraphSchemaResponse>("/api/graph/schema"),
  });
}

export function graphQueryKey(
  queryType: GraphQueryType,
  params: Record<string, string | number | undefined>,
) {
  return ["graph", "query", queryType, params] as const;
}

export function labelCypher(label: string): string {
  return `MATCH (n:\`${label}\`) RETURN n LIMIT 25;`;
}

export function relationshipCypher(relType: string): string {
  return `MATCH p=()-[:${relType}]->() RETURN p LIMIT 25;`;
}

export function propertyCypher(key: string): string {
  return `MATCH (n) WHERE n.${key} IS NOT NULL RETURN DISTINCT "node" AS entity, n.${key} AS ${key} LIMIT 25;`;
}

export async function fetchGraphQuery(
  queryType: GraphQueryType,
  params: Record<string, string | number | undefined>,
): Promise<GraphQueryResponse> {
  switch (queryType) {
    case "label":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/nodes?label=${encodeURIComponent(String(params.label ?? ""))}&limit=25`,
      );
    case "relationship":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/relationships?type=${encodeURIComponent(String(params.rel_type ?? ""))}&limit=25`,
      );
    case "property":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/properties?key=${encodeURIComponent(String(params.property_key ?? ""))}&limit=25`,
      );
    case "neighborhood":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/neighborhood/${encodeURIComponent(String(params.node_id ?? ""))}?depth=${params.depth ?? 1}&limit=25`,
      );
    case "entity":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/entity?hint=${encodeURIComponent(String(params.entity_hint ?? ""))}`,
      );
    default:
      throw new Error(`Unsupported graph query type: ${queryType}`);
  }
}

export async function executeGraphCypher(
  cypher: string,
): Promise<GraphQueryResponse> {
  return apiFetch<GraphQueryResponse>("/api/graph/cypher", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cypher, limit: 25 }),
  });
}

export function useGraphQuery(
  queryType: GraphQueryType | null,
  params: Record<string, string | number | undefined>,
  enabled = true,
) {
  return useQuery({
    queryKey: graphQueryKey(queryType ?? "label", params),
    enabled: enabled && queryType !== null,
    queryFn: () => fetchGraphQuery(queryType!, params),
  });
}
