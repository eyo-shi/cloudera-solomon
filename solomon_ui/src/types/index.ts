/**
 * FastAPI 側 (`solomon.api`) と共有する DTO の TypeScript 型。
 * 手書きだが、いずれ OpenAPI から生成する余地を残す。
 */

// ---------------- Catalog ---------------- //
export interface SchemaListResponse {
  catalog: string;
  schemas: string[];
}
export interface TableEntry {
  name: string;
  type: string;
  fq: string;
}
export interface TableListResponse {
  catalog: string;
  schema: string;
  tables: TableEntry[];
}
export interface ColumnEntry {
  name: string;
  type: string;
  nullable: boolean;
}
export interface ColumnListResponse {
  fq: string;
  columns: ColumnEntry[];
}

// ---------------- Graph ---------------- //
export interface GraphNodeDTO {
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
  caption: string;
}
export interface GraphEdgeDTO {
  id: string;
  type: string;
  source: string;
  target: string;
  properties: Record<string, unknown>;
}
export interface GraphVisualization {
  nodes: GraphNodeDTO[];
  edges: GraphEdgeDTO[];
  truncated?: boolean;
  cypher?: string;
  query_type?: GraphQueryType;
}
export type GraphQueryType =
  | "schema"
  | "label"
  | "relationship"
  | "property"
  | "neighborhood"
  | "entity";

export interface GraphSchemaResponse {
  node_labels: string[];
  relationship_types: string[];
  property_keys: string[];
  node_count?: number;
  relationship_count?: number;
}
export interface GraphQueryResponse {
  query_type: GraphQueryType;
  cypher: string;
  graph: GraphVisualization;
  node_count: number;
  edge_count: number;
}

export interface GraphTabRef {
  query_type: GraphQueryType;
  label?: string;
  rel_type?: string;
  property_key?: string;
  node_id?: string;
  entity_hint?: string;
  depth?: number;
  title?: string;
}

// ---------------- Search ---------------- //
export interface SearchDocumentEntry {
  fq_name?: string | null;
  score?: number;
  dataset?: Record<string, unknown>;
}
export interface SearchDocumentsResponse {
  index: string;
  namespace: string;
  query: string;
  documents: SearchDocumentEntry[];
}

// ---------------- Files ---------------- //
export interface S3Object {
  key: string;
  size: number;
  last_modified: string;
}
export interface S3ListResponse {
  bucket: string;
  prefix: string;
  delimiter: string;
  objects: S3Object[];
  subfolders: string[];
  is_truncated: boolean;
}

export interface FilePreviewResponse {
  status: "ok" | "error";
  bucket: string;
  key: string;
  format?: string;
  encoding?: string;
  total_size?: number;
  head_bytes?: number;
  content_type?: string;
  // CSV
  delimiter?: string;
  columns?: string[];
  header?: string[];
  has_header?: boolean;
  rows?: unknown[][];
  // Excel
  primary_sheet?: string;
  sheets?: Array<Record<string, unknown>>;
  // JSON
  json?: unknown;
  jsonl?: unknown[];
  mode?: "json" | "jsonl";
  value?: unknown;
  // Parquet
  schema?: Array<{ name: string; type: string }>;
  num_row_groups?: number;
  num_rows?: number;
  // Plain text
  text?: string;
  line_count?: number;
  truncated?: boolean;
  // Error
  error_code?: string;
  message?: string;
}

// ---------------- Query ---------------- //
export interface QueryRequest {
  sql: string;
  catalog?: string;
  schema?: string;
  max_rows?: number;
}
export interface QueryColumn {
  name: string;
  type: string;
}
export interface QueryResponse {
  columns: QueryColumn[];
  rows: unknown[][];
  truncated: boolean;
}

// ---------------- Artifacts ---------------- //
export type ArtifactType =
  | "table_preview"
  | "tables"
  | "dashboard"
  | "summary"
  | "sql"
  | "file_preview"
  | "graph";

export interface Artifact {
  id: string;
  type: ArtifactType;
  ref: Record<string, unknown>;
  title?: string;
  created_at?: string;
}

// ---------------- Wish (SSE) ---------------- //
export interface WishStepEvent {
  agent: string;
  status: "running" | "done" | "skipped" | "error";
  message: string;
}
export interface WishTokenEvent {
  delta: string;
}
export interface WishArtifactEvent {
  id: string;
  type: ArtifactType;
  ref: Record<string, unknown>;
}
export interface WishErrorEvent {
  error_code: string;
  message: string;
}
export interface WishDoneEvent {
  turn_id: string;
  session_id: string;
  artifacts: string[];
  ok: boolean;
}
export type WishEvent =
  | { event: "step"; data: WishStepEvent }
  | { event: "token"; data: WishTokenEvent }
  | { event: "artifact"; data: WishArtifactEvent }
  | { event: "error"; data: WishErrorEvent }
  | { event: "done"; data: WishDoneEvent };

// ---------------- Tabs (UI only) ---------------- //
export interface TabDescriptor {
  /** UI 内で一意 */
  id: string;
  /** タブに表示するタイトル */
  title: string;
  /** どの Tab 種別を描画するか */
  kind: ArtifactType;
  /** タブが再描画に使う参照 */
  ref: Record<string, unknown>;
  /** 重複判定用のキー (fq / bucket:key / artifact_id 等) */
  dedupeKey?: string;
}
