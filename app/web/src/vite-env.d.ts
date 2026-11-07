/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Where the API lives. Defaults to `/api`, which Vite proxies to FastAPI in development. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
