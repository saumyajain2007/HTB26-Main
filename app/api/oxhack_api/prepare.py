"""Prepare the source data the live source reads: `uv run python -m oxhack_api.prepare`.

Runs stream A's offline steps into the data folder (`OXHACK_DATA_DIR`, by default
the repository's git-ignored `data/`):

1. the Open Targets 26.09 disease listing (`ot/26.09/disease/00000000.parquet`),
   which Disease search and resolution read;
2. the Open Targets 26.09 Parquet datasets stream A's drug universe and evidence
   packets read (`ot/<dataset>/`): drug_molecule, clinical_indication,
   clinical_report, drug_mechanism_of_action, target and drug_warning;
3. the approved drug universe, `drug_targets.json`, with `pipeline.drugs` (A2).
   It reads ChEMBL 37 mechanisms, molecules, targets and bioactivity through
   ChEMBL's API and keeps every response under `chembl-37/`.

4. Reactome's lowest-level human pathway mapping (`reactome/<version>/`), with
   stream A's `pipeline.pathways`, for the pathway evidence.
5. The protein network, stream B's artefact bundle
   (`ranking/string-12.5-c700-e400/`), for the network ranking:
   - STRING 12.5's human protein list and physical links, full detail
     (`string/12.5/`, about 12 MB);
   - stream A's STRING-to-gene mapping, `string_id_map.json` (A3,
     `pipeline.string_map`), from that protein list and the Open Targets target
     table of step 2;
   - stream B's `build_artifacts` (`ranking/README.md`): the graph of links with
     combined score at least 700 and direct experiments at least 400, and the
     shortest-path distance between every pair of proteins in its largest
     component (a memory-mapped matrix of about 165 MB). This takes a few
     minutes; stream B publishes the folder only once it is complete.

Each step is cached and resumable: a complete file is never downloaded again, an
interrupted download restarts that file only, A2 reuses every ChEMBL response it
saved before, and a published bundle is never built again. Run it again to finish
an interrupted run; pass `--rebuild-drugs` to recompute `drug_targets.json` from
the saved responses. Without the bundle, live Experiments fall back to the
evidence ranking.

Experiment builds then fetch only per-Disease records (associations, a few ChEMBL
and PubChem lookups), which they also keep in `packets/http/`.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
from pathlib import Path

import httpx

from . import stream_a, stream_b
from .settings import Settings

log = logging.getLogger("oxhack_api.prepare")


def folder_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def megabytes(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB"


def get_with_retries(client: httpx.Client, url: str, attempts: int = 3) -> httpx.Response:
    """GET, retrying connection resets and server errors (Open Targets' S3 bucket)."""
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = (
                not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
            )
            if attempt == attempts or not retryable:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def download_disease_listing(data_dir: Path, client: httpx.Client) -> Path:
    """Stream A's pinned disease listing (A1's `DISEASE_URL`), unless already present."""
    path = data_dir / stream_a.DISEASE_PARQUET
    if path.is_file() and path.stat().st_size > 0:
        return path
    log.info("Downloading %s", stream_a.DISEASE_URL)
    path.parent.mkdir(parents=True, exist_ok=True)
    response = get_with_retries(client, stream_a.DISEASE_URL)
    expected = response.headers.get("content-length")
    if expected is not None and int(expected) != len(response.content):
        raise ValueError(f"Incomplete download of {stream_a.DISEASE_URL}")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        output.write(response.content)
    Path(output.name).replace(path)
    return path


STRING_DOWNLOADS = "https://stringdb-downloads.org/download"
STRING_FILES = ("protein.info", "protein.physical.links.full")
"""STRING 12.5's human files the network needs: the protein list (for the mapping) and the
physical links with every evidence channel (stream B filters on `experiments`)."""


def string_path(data_dir: Path, name: str) -> Path:
    version = stream_a.STRING_VERSION
    return data_dir / "string" / version / f"9606.{name}.v{version}.txt.gz"


def download_file(client: httpx.Client, url: str, path: Path) -> Path:
    """Stream a download to `path`, unless it is there; a partial file is never kept."""
    if path.is_file() and path.stat().st_size > 0:
        return path
    log.info("Downloading %s", url)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    for attempt in range(1, 4):
        try:
            with client.stream("GET", url) as response, partial.open("wb") as output:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    output.write(chunk)
            expected = response.headers.get("content-length")
            if expected is not None and int(expected) != partial.stat().st_size:
                raise ValueError(f"Incomplete download of {url}")
            partial.replace(path)
            return path
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            partial.unlink(missing_ok=True)
            retryable = (
                not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
            )
            if attempt == 3 or not retryable:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def build_network(data_dir: Path, client: httpx.Client, target_parts: list[Path]) -> Path:
    """Step 5: stream B's artefact bundle, from STRING 12.5 and stream A's mapping."""
    bundle = data_dir / "ranking" / stream_b.BUNDLE_NAME
    if stream_b.bundle_ready(bundle):
        return bundle
    version = stream_a.STRING_VERSION
    for name in STRING_FILES:
        download_file(
            client,
            f"{STRING_DOWNLOADS}/{name}.v{version}/{string_path(data_dir, name).name}",
            string_path(data_dir, name),
        )
    mapping = data_dir / "string_id_map.json"
    if not mapping.is_file():
        log.info("Mapping STRING proteins to Open Targets genes (A3)")
        stream_a.write_json(
            mapping, stream_a.string_mapping(string_path(data_dir, "protein.info"), target_parts)
        )
    started = time.monotonic()
    log.info("Building the protein network and its distance matrix (stream B); minutes")

    def progress(done: int, total: int) -> None:
        if done == total or done % 2048 < 128:
            log.info("Distances: %d of %d rows", done, total)

    stream_b.build_bundle(
        mapping,
        string_path(data_dir, "protein.physical.links.full"),
        bundle,
        progress=progress,
    )
    log.info("Protein network ready (%.0f s)", time.monotonic() - started)
    return bundle


def prepare(data_dir: Path, *, rebuild_drugs: bool = False) -> dict[str, int]:
    """Run every step; returns each output's size in bytes."""
    data_dir.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        started = time.monotonic()
        disease = download_disease_listing(data_dir, client)
        sizes["disease listing"] = folder_size(disease)
        log.info("Disease listing ready (%.0f s)", time.monotonic() - started)

        cache = stream_a.chembl_cache(data_dir, client)
        parts: dict[str, list[Path]] = {}
        for dataset in stream_a.OT_DATASETS:
            started = time.monotonic()
            parts[dataset] = stream_a.download_dataset(cache, dataset)
            sizes[f"ot/{dataset}"] = folder_size(data_dir / "ot" / dataset)
            log.info("Open Targets %s ready (%.0f s)", dataset, time.monotonic() - started)

        universe = data_dir / "drug_targets.json"
        if rebuild_drugs or not universe.is_file():
            started = time.monotonic()
            log.info("Building the approved drug universe (A2); ChEMBL responses are cached")
            stream_a.write_json(universe, stream_a.build_drug_universe(cache))
            log.info("drug_targets.json written (%.0f s)", time.monotonic() - started)
        sizes["drug_targets.json"] = folder_size(universe)
        sizes["chembl-37 cache"] = folder_size(data_dir / "chembl-37")

        started = time.monotonic()
        reactome, _ = stream_a.download_reactome(data_dir)
        sizes["reactome"] = folder_size(reactome.parent)
        log.info("Reactome pathways ready (%.0f s)", time.monotonic() - started)

        bundle = build_network(data_dir, client, parts["target"])
        sizes["string 12.5"] = folder_size(string_path(data_dir, "protein.info").parent)
        sizes["string_id_map.json"] = folder_size(data_dir / "string_id_map.json")
        sizes["protein network"] = folder_size(bundle)
    return sizes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m oxhack_api.prepare", description=(__doc__ or "").split("\n\n")[0]
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Data folder (default: OXHACK_DATA_DIR, else the repository's data/).",
    )
    parser.add_argument(
        "--rebuild-drugs",
        action="store_true",
        help="Recompute drug_targets.json even when it exists (reuses saved ChEMBL responses).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    data_dir: Path = (args.data_dir or Settings().data_dir).resolve()
    started = time.monotonic()
    sizes = prepare(data_dir, rebuild_drugs=args.rebuild_drugs)
    for name, size in sizes.items():
        print(f"{name:32} {megabytes(size):>10}")
    print(f"{'total in ' + str(data_dir):32} {megabytes(folder_size(data_dir)):>10}")
    print(f"done in {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
