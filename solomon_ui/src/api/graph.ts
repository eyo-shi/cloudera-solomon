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

export async function fetchGraphQuery(
  queryType: GraphQueryType,
  params: Record<string, string | number | undefined>,
): Promise<GraphQueryResponse> {
  switch (queryType) {
    case "label":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/nodes?label=${encodeURIComponent(String(params.label ?? ""))}`,
      );
    case "relationship":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/relationships?type=${encodeURIComponent(String(params.rel_type ?? ""))}`,
      );
    case "property":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/properties?key=${encodeURIComponent(String(params.property_key ?? ""))}`,
      );
    case "neighborhood":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/neighborhood/${encodeURIComponent(String(params.node_id ?? ""))}?depth=${params.depth ?? 1}`,
      );
    case "entity":
      return apiFetch<GraphQueryResponse>(
        `/api/graph/entity?hint=${encodeURIComponent(String(params.entity_hint ?? ""))}`,
      );
    default:
      throw new Error(`Unsupported graph query type: ${queryType}`);
  }
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
