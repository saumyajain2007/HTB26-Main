# Offline resistance demo (#43)

The fallback uses the committed MRSA profile, candidate explanations, evidence
statements and recorded property/Lean results. It needs no database, credentials,
CARD download, docking executable or internet connection at runtime. It opens a
saved profile; it does not compute a new ranking from typed genes. Scores, MICs
and ranks are fixtures, labelled on screen. Certificates confirm encoded property
rules, not antibiotic activity or safety. The model jury is shown as pending.

## Prepare once while online

From the repository root, with Python 3.12, uv and Node >=22.22 installed:

```sh
uv sync --all-packages --frozen --python 3.12
npm ci --prefix app/web
VITE_DISEASE_FLOW=0 npm run build --prefix app/web
```

Keep `.venv`, `app/web/node_modules`, `app/web/dist` and the repository's fixture
files on the demo machine. Rebuild after changing the frontend. Preparation is
separate from launch so losing the network cannot trigger dependency downloads.

## Launch with the network disconnected

```sh
./deploy/offline-demo.sh
```

Open <http://127.0.0.1:4173/resistance>. The launcher forces fixture services and
in-memory storage even if live settings are exported in the shell; it does not
read `.env`. Ctrl-C stops both servers. `OFFLINE_API_PORT` and `OFFLINE_WEB_PORT`
can change the default ports (8000 and 4173). A server failure stops its companion.
Restarting resets in-memory state.

## Walkthrough

1. Choose **MRSA (S. aureus)** under Pathogens. The other two saved presets are
   unavailable and say why. Avoid typed genes in this fallback: they require a
   separately prepared CARD release.
2. Read the resistance map: mecA, the linked mechanism and defeated drug classes.
3. Press **Next** to open the shortlist. Read the selected drug's explanation,
   separate features, property rules, certificate details and cited evidence.
4. Select **VANCOMYCIN** to show a property-rule failure and its explanation.
   A failure is a descriptive outlier flag, not a safety verdict.
5. Open **Show reference structure** to inspect the named co-crystal ligand in a
   prepared bacterial protein. Switch the prepared structure to explore another
   reference. This is not a computed pose of the selected candidate.
6. Show the fixture notice and caveats. Refresh the page to demonstrate that the
   saved profile and shortlist can be reopened directly.

Citations are recorded statements and source metadata available locally; following
external source links requires a network. This path does not include fresh browser
verification (#95), live jury calls or newly computed rankings (#34). Recheck the
walkthrough after those integrations land; their absence does not block this fallback.

## Verify

After preparation, install Chromium once while online, then run the browser check:

```sh
cd app/web
npx playwright install chromium
npm run e2e -- offline-resistance.spec.ts
```

The test uses the real local API and built frontend, blocks and fails on any
nonlocal browser request, and checks preset input, map, explained candidates,
property/certificate panels, evidence, fixture labelling and page reload. It also
opens the reference viewer, waits for a rendered WebGL canvas, switches structures
and closes the viewer after a direct-route reload. It never
substitutes mocked API responses. The API uses the installed virtual environment
directly, with explicit fixture settings. To check the entire machine's network
independence, also rehearse the launcher after disconnecting Wi-Fi/Ethernet.

## Saved real rankings (all three pathogens)

After the same preparation, launch the #34 saved outputs instead of the fixtures:

```sh
OFFLINE_RESISTANCE=saved ./deploy/offline-demo.sh
```

All three preset buttons are available. Each opens its own CARD-derived profile
and 126 ranked drugs from the committed ChEMBL/CARD run. No data downloads or
ranking computation occur at runtime. The loader checks file hashes against the
bundle summary and validates the profile/ranking joins; missing or corrupt data
fails startup. These are draft presets, not measured isolates, and efficacy has
not been validated. Lean was not requested in this run, so candidates correctly
show that it did not run. The fixture-only vancomycin proof demonstration above
applies to the default fallback, not this saved-data mode.

Run its browser regression check with:

```sh
E2E_RESISTANCE=saved npm run e2e --prefix app/web -- saved-resistance.spec.ts
```

For a standalone API use `HTB_RESISTANCE=saved`; `HTB_RESISTANCE_RESULTS_DIR`
selects another compatible bundle (default: `results/pathogen-integration`).
`HTB_RESISTANCE=fixture` keeps the original fallback. This setting is independent
of `HTB_SOURCE`, which controls the older disease experiments. Typed genes still
need a prepared CARD release and do not compute a new candidate ranking.
