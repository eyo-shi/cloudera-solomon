/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GANDALF_S3_BUCKETS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
