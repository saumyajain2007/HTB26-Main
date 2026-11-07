# Stream B — protein network and Candidate ranking

Stage 1 builds a disease-independent, undirected, unweighted Ensembl-gene
network and reusable shortest-path distances. Stage 2 reuses those artifacts for
raw proximity, conditional degree-matched scoring, baselines and shortlisting.

See [Stage 2 usage and output contract](../../docs/method/ranking/STAGE2.md) and
[measured Stage 2 results](../../docs/method/ranking/STAGE2_RESULTS.md). The sections below describe the
Stage 1 foundation; its saved graph and distance matrix remain reusable.

Stage 3 adds [retrospective evaluation and API adaptation](../../docs/method/ranking/STAGE3.md), with
[the measured two-Disease smoke test](../../docs/method/ranking/STAGE3_RESULTS.md). It reads frozen
Stage 2 rankings and separate reference labels without rerunning scoring.

## Inputs inspected in this checkout

`fixtures/README.md` is absent. The actual full Stream A release is under
`data/stream_a/`; the loader uses `string_id_map.json`, whose root fields are
`releases`, `coverage`, and `mappings`. Each mapping row has `string_id`,
`target_id`, `status`, and `reason`. The other release files contain drug Targets
and two Disease Target sets; Stage 1 does not depend on them.

The downloaded physical interaction file is
`data/string/9606.protein.physical.links.full.v12.5.txt.gz`. Its header is:

```text
protein1 protein2 homology experiments experiments_transferred database database_transferred textmining textmining_transferred combined_score
```

The defaults require `combined_score >= 700` **and** `experiments >= 400`.
`experiments_transferred` is never substituted for direct experimental support.
These thresholds are initial engineering choices, not validated optimal values.
The input must be the physical-links dataset; column names alone cannot
distinguish physical from functional STRING downloads. Explicit file paths and
SHA-256 hashes identify the selected inputs in every bundle.

## Install and run

Python 3.11+ is required. From the repository root:

```powershell
python -m venv .venv-ranking
.\.venv-ranking\Scripts\python.exe -m pip install -e ./ranking
.\.venv-ranking\Scripts\python.exe -m unittest discover -s ranking/tests -v
.\.venv-ranking\Scripts\python.exe -m ranking build --mapping data/stream_a/string_id_map.json --links data/string/9606.protein.physical.links.full.v12.5.txt.gz --output data/ranking/string-12.5-c700-e400
.\.venv-ranking\Scripts\python.exe -m ranking inspect data/ranking/string-12.5-c700-e400
```

On macOS/Linux, use `.venv-ranking/bin/python`. If `python` is unavailable on
PATH, use the installed interpreter's absolute path for the first command.
Filters are configurable with `--min-combined-score` and `--min-experiments`;
use a new output directory for every configuration. Existing bundles are never
overwritten. A failed build does not publish its staging directory.

## Graph and distance policy

- Identical mapping rows are deduplicated. Conflicting genes or statuses for
  one STRING protein exclude that protein. Invalid/nonhuman STRING IDs and
  invalid Ensembl IDs are excluded and counted. Several proteins mapping to
  the same gene are valid: merge their edges, remove self-loops, and deduplicate
  unordered edges. No name or symbol joins are used.
- The full graph includes **all valid mapped genes**, including isolates after
  filtering. Reports separately count nodes with edges, isolated genes,
  components, and the largest component. An edge row belongs to exactly one
  discard category: score filtering, mapping exclusion, self-loop, or duplicate.
- Distance rows/columns use only the largest connected component. Equal-size
  component ties choose the component with the first lexicographic gene ID.
  Genes outside it remain in the full graph/index for coverage reporting.
- SciPy computes unweighted shortest paths in chunks (default 128 rows).
  Each floating-point block uses about `8 * chunk_size * LCC_nodes` bytes;
  the final `uint8` matrix uses about `LCC_nodes²` bytes and is memory-mapped.
  Computation uses one process; no GPU or multiprocessing is needed.
- `uint8` reserves `255` for unreachable pairs, and finite values must be in
  `0..254`. Overflow raises an error before casting; rerun with `--dtype uint16`
  to reserve `65535` instead. Infinity is never cast directly. The distance
  function also supports disconnected artificial graphs; the production LCC
  matrix should have no unreachable pairs. Sentinel values must never be
  included in later distance averages.

## Saved bundle and Python reuse

| File | Meaning |
|---|---|
| `graph.npz` | Symmetric sparse adjacency, including mapped isolates |
| `index.json` | Sorted full-graph IDs, distance IDs, and component labels |
| `distances.npy` | Read-only memory-mappable LCC distances in index order |
| `mapping_exclusions.json` | Excluded valid human STRING IDs and reasons |
| `manifest.json` | Input hashes/sizes, releases, exact columns, filters, coverage, software versions, timings, and output hashes/sizes |

```python
from ranking.artifacts import load_artifacts

with load_artifacts("data/ranking/string-12.5-c700-e400") as saved:
    gene_to_row = {gene: i for i, gene in enumerate(saved.distance_gene_ids)}
    # saved.distances[i, j] is a hop count, not an efficacy score.
```

Reload verifies artifact hashes, shapes and encoding without requiring the
downloaded input files. Preserve `index.json` alongside the distance matrix.
The supplied release has no download-URL, extraction-date or licence manifest;
these missing fields are recorded explicitly, not invented. Review source
licences and add the original download metadata before redistributing data.

`data/`, local environments, caches, and `ranking/artifacts/` are gitignored.
Keep generated bundles under either ignored artifact directory.
