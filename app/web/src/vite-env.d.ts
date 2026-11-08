/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH0_DOMAIN?: string;
  readonly VITE_AUTH0_CLIENT_ID?: string;
  /** Where the API lives. Defaults to `/api`, which Vite proxies to FastAPI in development. */
  readonly VITE_API_BASE?: string;
  /** `1` turns the gated COVID-19 disease flow back on (`src/app/flags.ts`). */
  readonly VITE_DISEASE_FLOW?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
