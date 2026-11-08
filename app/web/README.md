# web

The React app: Vite, React 19 and TypeScript (strict). Its Figure layout and design
tokens live in [`src/app/Figure.tsx`](src/app/Figure.tsx) and
[`src/styles/tokens.css`](src/styles/tokens.css).

## Run it

Needs Node 22.22 or later.

```sh
npm ci
npm run dev        # http://localhost:5173, with /api proxied to FastAPI on 127.0.0.1:8000
```

| Script                    | What it does                                                            |
| ------------------------- | ----------------------------------------------------------------------- |
| `dev`                     | Vite dev server with the `/api` proxy                                   |
| `build`                   | Type-checks, then builds to `dist/`                                     |
| `preview`                 | Serves `dist/` (also proxies `/api`)                                    |
| `typecheck`               | `tsc -b`                                                                |
| `lint`                    | ESLint (typescript-eslint, react-hooks, jsx-a11y), no warnings allowed  |
| `format` / `format:check` | Prettier                                                                |
| `test`                    | Vitest with jsdom, Testing Library and MSW                              |
| `e2e`                     | Playwright: starts the fixture API and `vite preview`, walks every step |
| `gen:api`                 | Regenerates `src/api/schema.d.ts` from `../api/openapi.json`            |

`VITE_API_BASE` sets the API's origin (default: the page's own origin, whose `/api` Vite proxies).
`HTB_API_ORIGIN` points the dev and preview proxies at an API other than
`http://127.0.0.1:8000`.

## Sign in with Auth0

The official `@auth0/auth0-react` 2.x SDK is configured for the project's SPA:
`dev-kt7rl83e2qb1qb6t.us.auth0.com`, client ID `IQjKLlPrAbcbA6emWspXyMXArwBFFPmM`.
These are public identifiers. To use another application, copy `.env.example`
to `.env.local` and change `VITE_AUTH0_DOMAIN` and `VITE_AUTH0_CLIENT_ID`.
Never put a client secret in the frontend.

Before testing a real login, open that application's **Settings** in the
[Auth0 dashboard](https://manage.auth0.com/) and save these values:

| Application setting                  | Local value             |
| ------------------------------------ | ----------------------- |
| Application type                     | Single Page Application |
| Token Endpoint Authentication Method | None                    |
| Allowed Callback URLs                | `http://localhost:5173` |
| Allowed Logout URLs                  | `http://localhost:5173` |
| Allowed Web Origins                  | `http://localhost:5173` |

`npm run dev` fixes port 5173 with `--strictPort`; it fails instead of silently
choosing another port and breaking the callback. Open **http://localhost:5173**,
not the IP-address origin. For a deployed build, add its exact HTTPS origin to
all three URL lists as well. A preview on port 4173 needs its own entries.

The header opens `/login`; sign-in and account creation redirect to Auth0 Universal
Login. Passwords, reset-password screens and any enabled social connections are
handled there. The SDK processes the callback at the app's origin and restores
the requested local route. External return URLs and login loops are rejected.
`/account` displays name, email and verification status, and signs out through
the SDK back to the app's origin. Tokens use the SDK's default in-memory cache.
Loading, callback errors and rejected sign-in/sign-out calls have explicit UI states.

This change adds client-side account login, as in the supplied quickstart. The
public guest research flow remains available. It does **not** change FastAPI's
anonymous browser-session ownership or make experiments account-synced across
devices. Protecting API data with Auth0 would also require an API audience and
server-side access-token validation; an ID token must not be used as an API token.

Tests mock the SDK context, not OAuth. `npm test` covers sign-in, sign-up, logout,
loading/errors, guest access, account details and safe return locations. To check
a real round trip after saving the dashboard settings: sign in from a research
page, confirm that it returns there, visit Your account, then sign out. Real
credentials are deliberately not part of the automated tests.

References: [Auth0 React quickstart](https://auth0.com/docs/quickstart/spa/react)
and [official React SDK](https://auth0.github.io/auth0-react/).

### The two flows

The default app is the antibiotic resistance flow. The earlier human-disease flow
remains available behind a build flag:

- The **antibiotic resistance flow** is always mounted, at `/resistance` and
  `/resistance/:profileId/:step`, and `/` leads to it.
- The **COVID-19 disease flow** (`/`, `/explore`, `/e/:experimentId/:step`, `/evaluation`) is
  gated off: it answers only when `VITE_DISEASE_FLOW=1` at build time. It is backed entirely by
  COVID fixtures for the historical demonstration and regression tests. The resistance
  flow has its own offline demo and tests. Set the flag in the environment to walk it:
  `VITE_DISEASE_FLOW=1 npm run dev`.

`src/app/flags.ts` reads the flag once and `src/app/routes.tsx` is the only place that branches
on it. The Vitest suite turns it on through `test.env` in `vite.config.ts`, and the Playwright
suite through the preview server's `env` in `playwright.config.ts`, because both suites drive the
old flow on purpose.

`npm run e2e` needs the prepared root `.venv`, installed frontend dependencies and
Playwright's Chromium (`npx playwright install chromium`). It starts the real local
fixture API directly from `.venv` and builds/previews the frontend. Default ports
are 18001 and 14174; `E2E_API_PORT` and `E2E_WEB_PORT` move them. Server reuse is
explicit (`E2E_REUSE_SERVER=1`). `E2E_RESISTANCE=saved` selects the saved real-data
checks. See [offline setup and walkthrough](../../docs/offline-demo.md).

## Layout

- `src/styles/tokens.css`: shared colour, type and spacing tokens plus a small
  reset. Components use CSS Modules and read only these custom properties.
- `src/copy/en.ts`: the copy deck. Every interface sentence lives here. Text that depends on the
  Disease (evidence, objections, model names) comes from the API instead.
- `src/app/Shell.tsx`: header (product, Disease, step navigation, Back and Next), step title and
  intro, then the figure. `PageFrame.tsx` renders the footer link to the evaluation once on every screen.
- `src/app/routes.tsx`: `createRoutes(diseaseFlow)` builds every address. The resistance flow's
  `/resistance` is step 1 before any profile and `/resistance/:profileId/:step` uses the resistance
  step slugs from the copy deck; the disease flow's `/explore` and `/e/:experimentId/:step` are
  mounted only behind the flag. Anything else is not found.
- `src/lib/resistance.ts`: the TanStack Query hooks for the resistance routes (pathogen presets,
  a profile, a profile's candidates, the certificates), typed from the generated contract.
  `src/test/resistance.ts` holds the matching fixtures and MSW handlers, read from the API's own
  fixture files, and is wired into `src/test/server.ts`.
- `src/api/client.ts`: the `openapi-fetch` client, typed by the generated `schema.d.ts`. Don't
  edit `schema.d.ts` by hand; run `npm run gen:api` after the API contract changes.
  `src/api/queries.ts` holds the TanStack Query hooks: debounced disease search, creating an
  Experiment, the Experiment (polled every second while it builds, every two while its jury or a
  docking job works), asking the jury, history with archive and restore, the prepared structures
  and molecule conformers.
- `src/app/routes/ExperimentLayout.tsx`: `/e/:experimentId/:step` loads the Experiment once,
  shows its build progress or failure, and owns the figure grid and the persistent protein
  network, so the network is mounted once and survives step changes. Each step
  (`src/steps/`) only adds its own panels and points the network at what it is about.
- `src/three/`: the print-style WebGL plates (`NetworkFigure`, `MoleculeFigure`), loaded lazily.
  Drag rotates; ambient rotation and easing stop under `prefers-reduced-motion`. `MoleculeStrip`
  draws Compare's molecules side by side on one shared canvas, so a step never needs more than
  three WebGL contexts (the hidden network keeps its own).
- `src/charts/SlopeChart.tsx`: closeness, network rank and evidence rank on one row per drug.
- `src/steps/JuryStep.tsx`: the Model jury's ballot board, one row per drug in consensus order
  and one column per model (marked by its `Marker.tsx` shape), each tile the model's rank styled
  by its decision, with a reading pane for the picked drug. `src/lib/jury.ts` builds the rows
  (consensus place, votes, split decision, rank spread) and the counted models.
- `src/lib/format.ts`: `drugName()` and the other display formatters; use them everywhere.
- Tests: `src/test/` has the MSW server (handlers typed by the contract via `openapi-msw`), the
  WebGL and layout stand-ins for jsdom, and fixtures read straight from
  `../api/htb_api/fixtures` through the `@api-fixtures` alias, so both sides share one copy.
  `e2e/` holds the Playwright tests.

ArrowUp and ArrowDown move between steps, except while typing in a field or moving through the
jury's ballot board.

`3dmol` is installed for the binding pose (phase 7) but not used yet.
