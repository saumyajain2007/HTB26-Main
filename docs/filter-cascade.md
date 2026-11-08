# The filter cascade and the oracle ledger (issues #87 and #88)

## Filter cascade (#87)

[filters.py](../core/wholecell/htb_wholecell/filters.py). Six stages, cheapest first; a molecule is rejected at the first one it fails, with a reason. Run: `uv run python -m htb_wholecell filter candidates.tsv --out dir` (columns `id`, `smiles`); it writes `survivors.tsv`, `rejections.tsv` (stage and reason for every rejected molecule), `funnel.json` and `funnel.svg`.

| Stage | Rule |
|---|---|
| validity | parses, sanitises, has atoms |
| heavy_atoms | at most 50 (the affinity model degrades above about 50) |
| synthetic_accessibility | SA score at most 6 |
| structural_alerts | no PAINS or Brenk alert (the same catalogues and SA scorer as `core/verify`; a test checks they agree) |
| gram_negative_entry_2d | primary amine and at most 5 rotatable bonds |
| conformer | a 3D conformer embeds; globularity at most 0.25 is checked here because it needs the conformer |

### Decisions the spec did not make

- **The entry rules are flag-only by default.** Values are recorded and counted, nothing is rejected for them. With `--entry reject` they are enforced as the spec describes. Reason: abaucin, a real *A. baumannii* antibiotic, has no primary amine and is rejected by the strict rule. Of 501 Hub survivors in the sample below, 479 (96%) would fail the entry rules, so enforcing them removes almost everything.
- **Structural alerts reject real antibiotics too.** Halicin is rejected at this stage (nitro group, thiazole alerts). **The cascade is for generated candidates. Do not run it on the library compounds in the hidden-drug test** (#91), or it removes the compound being searched for.

### Definitions, and what is not verified

- *Primary amine*: an aliphatic NH2 that is not an amide, sulfonamide or aniline. This is my reading of the rule, not the paper's.
- *Rotatable bonds*: RDKit's strict count.
- *Globularity*: smallest over largest eigenvalue of the covariance of heavy-atom coordinates, averaged over 10 ETKDG conformers, cut at 0.25. This comes from patent text that describes the method; **the Nature paper (Richter et al. 2017) was not read**, so the exact definition and whether 0.25 applies to it are unverified.
- The entry rules are heuristics for *E. coli* accumulation, not a model of cell entry in *A. baumannii*.

### Measured on a sample

1,000 randomly chosen Drug Repurposing Hub compounds (seed 0). These are approved and investigational drugs, not generated molecules, so the survival rate is not the figure to expect for generated candidates (the spec guesses 60 to 75%; not measured here because no generated batch exists yet). Raw: [results/whole_cell/](../results/whole_cell/).

| Stage | Reached | Rejected |
|---|---|---|
| validity | 1,000 | 0 |
| heavy atoms | 1,000 | 28 |
| synthetic accessibility | 972 | 9 |
| structural alerts | 963 | 461 |
| entry rules (flag-only) | 502 | 0 |
| conformer | 502 | 1 |
| **Survive** | **501 (50.1%)** | |

Alerts do almost all the rejecting (the commonest: long aliphatic chain, nitro group, aniline, isolated alkene, Michael acceptor). **Speed:** the conformer stage costs about 0.15 s per molecule on one core. With `--jobs` (default: every core) the same 300 molecules took 17.4 s on one process, 5.6 s on four and 4.1 s on ten, on a ten-core Mac with Docker running; so 50,000 candidates would take roughly 30 to 40 minutes, not two hours. Output is identical whatever `--jobs` is.

## Oracle interface and cost ledger (#88)

[oracles.py](../core/wholecell/htb_wholecell/oracles.py). Every scorer implements `score(smiles) -> OracleResult` (higher is better). `CostedOracle` wraps one: each call is timed with a monotonic clock and appended to the ledger, whether it succeeds, fails or is served from the cache. The ledger holds measured seconds only.

| Fidelity | Oracle | State |
|---|---|---|
| 0 | `FilterOracle`: the cascade as a gate | built |
| 1 | `DockingOracle`: AutoDock Vina through `htb_worker.dock` | built, tested with a fake runner, **not run against real Vina** |
| 2 | Boltz-2 affinity | not built (#93, out at the 10-hour budget) |
| 3 | OpenMM stability | not built (#94, out at the 10-hour budget) |

- **Engine.** The spec says QuickVina2; the repository's worker runs AutoDock Vina 1.2.7, which is what is wrapped. The ledger records the engine version in every row.
- **Where docking runs.** Vina publishes Linux x86_64 wheels only, so `DockingOracle` needs the docking environment's interpreter (the amd64 container, or an x86_64 Vultr VM). On this Mac it has not been exercised end to end, and its score is `-best Vina score` so that higher is better.
- **Ledger.** JSON lines; each row has the hash of the row before it, so an edited, removed or reordered row is detected by `Ledger.verify` (`uv run python -m htb_wholecell ledger <path>`). It is opened for append only and is safe for concurrent writers (file lock). Rows record candidate, InChIKey, oracle and its version, fidelity, seconds, cache hit, success, error, score, uncertainty, hardware.
- **Cache.** Keyed by InChIKey, oracle name and oracle version, rebuilt from the ledger on start, so a rerun in a new process does not pay again. Cache hits are logged as their own rows and excluded from cost totals. Failures are never cached.
- **A hash chain is tamper-evident, not tamper-proof.** Someone who rewrites the whole file consistently defeats it. It protects against accidents and casual edits.
