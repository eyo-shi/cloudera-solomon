/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SOLOMON_S3_BUCKETS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
