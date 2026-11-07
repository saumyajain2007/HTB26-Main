import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The FastAPI app (api/) listens on :8000 in development; the browser only ever talks to /api.
// OXHACK_API_ORIGIN points the dev and preview proxies elsewhere (the end-to-end tests use it).
const API_ORIGIN = process.env.OXHACK_API_ORIGIN ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // The API's fixture files, read by the web tests so both sides share one copy of the data.
      "@api-fixtures": fileURLToPath(new URL("../api/oxhack_api/fixtures", import.meta.url)),
    },
  },
  build: {
    // three.js and 3Dmol.js are each ~530-580 kB minified; each loads lazily, only when a 3D
    // figure needs it.
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      onwarn(warning, warn) {
        // 3Dmol.js evaluates its own embedded view specs; the app never calls eval.
        if (warning.code === "EVAL" && warning.id?.includes("/node_modules/3dmol/")) return;
        warn(warning);
      },
    },
  },
  server: {
    proxy: {
      "/api": { target: API_ORIGIN, changeOrigin: false },
    },
  },
  preview: {
    proxy: {
      "/api": { target: API_ORIGIN, changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    css: { modules: { classNameStrategy: "non-scoped" } },
    restoreMocks: true,
  },
});
