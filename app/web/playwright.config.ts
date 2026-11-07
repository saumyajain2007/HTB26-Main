import { defineConfig, devices } from "@playwright/test";

/*
 * End-to-end tests against the real API in fixture mode and the built app (`vite preview`), as a
 * student would use them. Both servers start on their own; E2E_REUSE_SERVER=1 opts into reuse.
 * E2E_API_PORT and E2E_WEB_PORT move them off the defaults when those ports are busy.
 */
const apiPort = process.env.E2E_API_PORT ?? "18001";
const webPort = process.env.E2E_WEB_PORT ?? "14174";
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const ci = process.env.CI !== undefined;
const reuse = !ci && process.env.E2E_REUSE_SERVER === "1";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // Software WebGL is CPU intensive; keep local and CI runs within a predictable budget.
  workers: 2,
  forbidOnly: ci,
  retries: ci ? 1 : 0,
  reporter: ci ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        // Headless Chromium draws WebGL in software.
        launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
      },
    },
  ],
  webServer: [
    {
      command: `uv run uvicorn oxhack_api.app:app --port ${apiPort}`,
      cwd: "../api",
      url: `${apiOrigin}/api/health`,
      // Slow enough to see each build stage, quick enough for a test.
      env: { OXHACK_FIXTURE_DELAY_MS: "300" },
      reuseExistingServer: reuse,
      timeout: 120_000,
    },
    {
      command: `npm run build && npx vite preview --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: `http://127.0.0.1:${webPort}`,
      env: { OXHACK_API_ORIGIN: apiOrigin },
      reuseExistingServer: reuse,
      timeout: 120_000,
    },
  ],
});
