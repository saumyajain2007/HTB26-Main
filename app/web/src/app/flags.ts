/**
 * Build-time feature flags, read from Vite's `import.meta.env` so a disabled flow is a constant
 * the bundler can see.
 */

/**
 * The COVID-19 disease flow (issue #32): the disease search, the Experiment steps and the
 * evaluation page. It is backed entirely by COVID fixtures, and the antibiotic resistance flow
 * replaces it, so it is **off unless `VITE_DISEASE_FLOW` is `1`**. Gated rather than deleted, so
 * the offline demo and its tests keep working until the new flow is finished.
 *
 * It is on for two callers, each of which drives the old flow on purpose:
 *   - the Vitest suite, through `test.env` in `vite.config.ts`;
 *   - the Playwright suite, through the preview server's `env` in `playwright.config.ts`.
 *
 * A flag read once here, rather than a condition in each component, keeps the two flows from
 * drifting apart: `routes.tsx` is the only place that branches on it.
 */
export const diseaseFlowEnabled: boolean = import.meta.env.VITE_DISEASE_FLOW === "1";
