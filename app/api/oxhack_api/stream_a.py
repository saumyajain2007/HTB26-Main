"""The one place the API calls stream A: `pipeline/` and `jury/` at the repository root.

Stream A is untyped Python that passes JSON-shaped dicts around. This module
gives each call the API makes a typed signature, so strict type checking holds
everywhere else, and it is the only file that relaxes it. It adds no behaviour
of its own: every rule (Disease resolution, scoring, approval checks, evidence
items, jury validation) is stream A's.

Stream A owns these functions; `fixtures/README.md` and `jury/README.md` at the
repository root describe their inputs and outputs.
"""

# Stream A has no type annotations or stubs; only this boundary module sees its Unknowns.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# The casts state what each call returns, even where pyright can infer part of it.
# pyright: reportUnnecessaryCast=false

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol, cast

import duckdb
import httpx
from jury import client as _jury
from pipeline import disease_targets as _a1
from pipeline import drugs as _a2
from pipeline import experiment as _experiment
from pipeline import opentargets as _opentargets
from pipeline import packets as _packets
from pipeline import pathways as _pathways
from pipeline import string_map as _string_map

JSON = dict[str, Any]

log = logging.getLogger(__name__)

PREFETCH_THREADS = 6
"""ChEMBL requests a build makes at once while it warms the response cache."""
"""A stream A record: the JSON shapes in the repository's `fixtures/`."""

OT_RELEASE: str = _packets.OT_RELEASE
CHEMBL_RELEASE: str = _packets.CHEMBL_RELEASE
REGULATORS: tuple[str, ...] = tuple(_packets.REGULATORS)
EVIDENCE_FALLBACK_LABEL: str = _experiment.FALLBACK
""""Evidence ranking - network unavailable", stream A's label for plan section 4.4."""

OpenTargetsError = cast(type[Exception], _opentargets.OpenTargetsError)
"""An Open Targets failure or incomplete answer; stream A never turns one into a guess."""

DISEASE_URL: str = _a1.DISEASE_URL
DISEASE_PARQUET = Path("ot/26.09/disease/00000000.parquet")
"""Where the Open Targets disease listing lives under a data folder (stream A's layout)."""
STREAM_A_DISEASE_CACHE: Path = _a1.DISEASE_CACHE
"""Stream A's own copy of that listing, always under the repository's `data/`: A1
resolves Disease IDs from it whatever data folder the API uses."""

PROMPT_VERSION: str = _jury.PROMPT_VERSION
JURY_CONFIG_PATH = Path(cast(str, _jury.__file__)).with_name("config.json")
PACKET_SHUFFLE_SEED = 7
"""`build_evidence_packet`'s default seed for the packet's C labels."""

OT_DATASETS = (
    "drug_molecule",
    "clinical_indication",
    "clinical_report",
    "drug_mechanism_of_action",
    "target",
    "drug_warning",
)
"""The Open Targets 26.09 Parquet datasets the drug universe and evidence packets read."""


class ModelCall(Protocol):
    def __call__(self, model: str, prompt: str, temperature: float) -> object: ...


# ---------------------------------------------------------------------------
# Evidence sources.
# ---------------------------------------------------------------------------

_TARGET_RECORDS: dict[Path, JSON] = {}
_TARGET_RECORDS_LOCK = threading.Lock()


class _SharedSources(_experiment.ExperimentSources):
    """Stream A's `ExperimentSources`, sharing its ChEMBL target index between builds.

    `ExperimentSources` reads every saved ChEMBL target batch the first time it maps
    a target; that index only changes when the data is prepared again, so builds
    share one copy per data folder instead of each reading it again.
    """

    def chembl(self, endpoint: str) -> JSON:
        folder = cast(Path, self.inputs.data_dir)
        if self.target_records is None:
            self.target_records = _TARGET_RECORDS.get(folder)
        record = cast(JSON, super().chembl(endpoint))
        if self.target_records is not None:
            with _TARGET_RECORDS_LOCK:
                _TARGET_RECORDS.setdefault(folder, cast(JSON, self.target_records))
        return record


class EvidenceSources:
    """Stream A's evidence sources over one data folder, for one build.

    Reads the prepared inputs in `data_dir` (Parquet tables, `drug_targets.json`'s
    ChEMBL cache) and keeps every new HTTP response in the same folder's cache
    (`packets/http/<release>/`), so a second build of a Disease reads it back. With
    `offline`, a response that is not saved yet raises instead of being fetched.

    Not thread-safe: stream A queries Parquet on DuckDB's shared default connection.
    """

    def __init__(self, data_dir: Path, *, offline: bool = False) -> None:
        self._sources = _SharedSources(data_dir, data_dir, offline=offline)

    def disease_targets(self, disease_id: str, top_n: int) -> tuple[JSON, dict[str, float]]:
        """A1: the Disease's top Targets by evidence-only score, and the evidence-only
        score of every Target associated with it (the direct-evidence baseline's input)."""
        with _experiment.AssociationClient(self._sources) as client:
            targets = cast(JSON, _a1.disease_targets(client, disease_id, top_n=top_n))
            scored = _a1.rescore_associations(client.associations(targets["disease_id"]))
        scores = {
            cast(str, row["target"]["id"]): cast(float, row["scores"]["evidence_only"])
            for row in scored
        }
        # A4 reuses these checked scores instead of fetching the associations again.
        self._sources.association_scores = scores  # pyright: ignore[reportAttributeAccessIssue]
        return targets, scores

    def prefetch(self, candidate_ids: Iterable[str], drugs: Mapping[str, JSON]) -> None:
        """Fetch the records stream A reads for these drugs, several at a time, into the
        response cache: from ChEMBL each drug's molecule record and its salt forms', its
        mechanisms and its bioactivity pages, and from PubChem its compound ID. The parent
        check and the A4 evidence packet read them one request at a time, so on a first
        build they now find them saved instead.

        Only warms the cache, through stream A's own requests (so the URLs are the ones it
        reads): nothing here decides anything, and a fetch that fails is left to stream A,
        which asks again and reports it. Each URL is fetched by one thread only, as the cache
        writes a response through one temporary file per URL. The fetches go through a
        separate copy of stream A's sources over the same folder, so what they would reject
        is left to the build, which records rejections in its own order (they are saved with
        the evidence packet)."""
        warm = EvidenceSources(self._sources.data_dir, offline=self._sources.offline)
        sources = warm._sources

        def molecule(source_id: str) -> None:
            record = sources.chembl(f"molecule/{source_id}.json")
            if source_id in candidates:
                sources.pubchem_cid(record)

        def bioactivity(source_id: str) -> None:
            sources.bioactivity_target_ids([source_id])

        def mechanisms(candidate_id: str) -> None:
            warm.mechanisms(candidate_id)

        candidates = list(dict.fromkeys(candidate_ids))
        tasks: list[tuple[Callable[[str], None], str]] = []
        for candidate_id in candidates:
            source_ids = dict.fromkeys([candidate_id, *drugs[candidate_id]["source_chembl_ids"]])
            tasks += [(fetch, s) for s in source_ids for fetch in (molecule, bioactivity)]
            tasks.append((mechanisms, candidate_id))
        with ThreadPoolExecutor(PREFETCH_THREADS, thread_name_prefix="chembl-prefetch") as pool:
            for future in [pool.submit(fetch, chembl_id) for fetch, chembl_id in tasks]:
                if (error := future.exception()) is not None:
                    log.info("prefetch left a request to the build: %s", error)

    def is_parent(self, candidate_id: str) -> bool:
        """True when ChEMBL lists the molecule as its own parent (A4 requires it)."""
        molecule = cast(JSON, self._sources.chembl(f"molecule/{candidate_id}.json"))
        return molecule["molecule_hierarchy"]["parent_chembl_id"] == candidate_id

    def approval(self, source_ids: list[str]) -> JSON | None:
        """The regulator-backed approval report A4 cites, or None."""
        return cast(JSON | None, self._sources.approval(source_ids))

    def reject(self, source: str, item: str, reason: str) -> None:
        self._sources.reject(source, item, reason)

    @property
    def coverage(self) -> JSON:
        return cast(JSON, self._sources.coverage)

    def mechanisms(self, candidate_id: str) -> list[JSON]:
        """ChEMBL's mechanism records for a parent molecule (the request A4 makes)."""
        endpoint = f"mechanism.json?parent_molecule_chembl_id={candidate_id}&limit=100"
        return cast(list[JSON], list(self._sources.pages(endpoint, "mechanisms")))

    def map_target(self, target_chembl_id: str, *, single: bool = False) -> set[str]:
        """The Ensembl gene IDs of a ChEMBL target, by A4's mapping rule."""
        return cast(set[str], self._sources.map_target(target_chembl_id, single=single))

    def report_source(self, report_id: str) -> str | None:
        """The source (e.g. FDA) of an Open Targets clinical report."""
        rows = (
            self._sources.table("clinical_report")
            .filter(duckdb.ColumnExpression("id") == duckdb.ConstantExpression(report_id))
            .select("source")
            .fetchall()
        )
        return cast(str, rows[0][0]) if len(rows) == 1 else None

    def target_names(self, target_ids: Iterable[str]) -> dict[str, str]:
        """Approved full names of Ensembl genes, from the Open Targets target table."""
        ids = sorted(set(target_ids))
        if not ids:
            return {}
        rows = (
            self._sources.table("target")
            .filter(
                duckdb.ColumnExpression("id").isin(*(duckdb.ConstantExpression(i) for i in ids))
            )
            .select("id", "approvedName")
            .fetchall()
        )
        return {cast(str, gene): cast(str, name) for gene, name in rows if name}

    def target_symbols(self, target_ids: Iterable[str]) -> dict[str, str]:
        """Approved gene symbols of Ensembl genes, from the Open Targets target table."""
        ids = sorted(set(target_ids))
        if not ids:
            return {}
        rows = (
            self._sources.table("target")
            .filter(
                duckdb.ColumnExpression("id").isin(*(duckdb.ConstantExpression(i) for i in ids))
            )
            .select("id", "approvedSymbol")
            .fetchall()
        )
        return {cast(str, gene): cast(str, symbol) for gene, symbol in rows if symbol}

    def evidence_packet(
        self,
        disease: JSON,
        candidate_ids: list[str],
        disease_targets: JSON,
        drug_targets: JSON,
        *,
        experiment_id: str,
        releases: list[str],
        pathways: Pathways | None = None,
        network_paths: NetworkPaths | None = None,
    ) -> tuple[list[JSON], JSON]:
        """A4: each Candidate's evidence, warnings and PubChem ID, and the blinded jury
        packet, with stream A's HTTPS fix for legacy FDA links applied to both.

        With `pathways`, A4 adds the Reactome pathways each Candidate shares with the
        Disease Targets. With `network_paths`, stream A's `add_network_paths` adds each
        Candidate's representative routes in the protein network, and the Candidates'
        evidence lists are rebuilt from the packet, as A4 does for pathways."""
        updates, packet = _packets.build_evidence_packet(
            disease,
            candidate_ids,
            disease_targets,
            drug_targets,
            experiment_id=experiment_id,
            sources=self._sources,
            releases=releases,
            pathways=None if pathways is None else pathways.pathways,
            pathway_release=None if pathways is None else pathways.release,
        )
        if network_paths is not None:
            packet = _packets.add_network_paths(
                packet,
                [
                    {
                        "candidate_id": cid,
                        "network_paths": {"paths": network_paths.paths.get(cid, [])},
                    }
                    for cid in candidate_ids
                ],
                graph=network_paths.graph,
                target_names=network_paths.symbols,
                string_mappings=network_paths.string_mappings,
                disease_target_ids=set(network_paths.disease_target_ids),
                coverage=network_paths.coverage,
            )
            share_routes(packet)
            by_id = {c["candidate_id"]: c for c in packet["candidates"]}
            items = {e["id"]: e for e in packet["evidence"]}
            for update in updates:
                update["evidence"] = [
                    dict(items[e]) for e in by_id[update["candidate_id"]]["evidence_ids"]
                ]
        _experiment.normalize_evidence_urls(updates, packet)
        return cast(list[JSON], updates), cast(JSON, packet)

    def bioactivity_consistency(self, drug_targets: JSON, updates: list[JSON]) -> list[JSON]:
        """Where A4's bioactivity items differ from A2's measurements (empty when none)."""
        return cast(
            list[JSON],
            _experiment.bioactivity_consistency(drug_targets, updates, self._sources),
        )


class Pathways:
    """A Reactome release's lowest-level pathways (`pipeline.pathways`), by pathway ID:
    `{"name": ..., "genes": {ENSG...}}`, joined to genes by Ensembl ID only."""

    def __init__(self, path: Path, release: str) -> None:
        pathways, unmapped = _pathways.load_pathways(path)
        self.pathways = cast(dict[str, JSON], pathways)
        self.unmapped = cast(dict[str, int], unmapped)
        self.release = release

    def name(self, pathway_id: str) -> str:
        return cast(str, self.pathways[pathway_id]["name"])

    def genes(self, pathway_id: str) -> set[str]:
        return cast(set[str], self.pathways[pathway_id]["genes"])


def reactome_release(data_dir: Path) -> tuple[Path, str] | None:
    """The newest Reactome release `pipeline.pathways` saved under `data_dir/reactome/`, as
    (human mapping file, release), or None when there is none."""
    saved: list[tuple[int, Path, str]] = []
    for manifest in (data_dir / "reactome").glob("*/manifest.json"):
        record = cast(JSON, json.loads(manifest.read_text(encoding="utf-8")))
        mapping = manifest.with_name("Ensembl2Reactome.human.tsv")
        if mapping.is_file() and manifest.parent.name.isdigit():
            saved.append((int(manifest.parent.name), mapping, cast(str, record["release"])))
    if not saved:
        return None
    _, mapping, release = max(saved)
    return mapping, release


def download_reactome(data_dir: Path) -> tuple[Path, JSON]:
    """Stream A's pinned download of Reactome's current lowest-level human mapping, unless
    that release is saved already. Returns the mapping file and its manifest."""
    path, manifest = _pathways.download(str(data_dir))
    return Path(path), cast(JSON, manifest)


def share_routes(packet: JSON) -> None:
    """List each network route under every Candidate whose own Target starts it.

    Stream A attaches a route only to the Candidates it was a representative path for
    (at most three each). A route from JAK1 to TYK2 is as true for every other JAK1
    drug, and jurors cite it for them; the checker then rejects the review as citing
    another Candidate's evidence. No item is added: only who it is listed under.
    """
    routes: dict[str, list[str]] = {}
    for item in cast(list[JSON], packet["evidence"]):
        if item["kind"] == "network_path":
            start = cast(str, item["source_id"]).split("@", 1)[0].split(">", 1)[0]
            routes.setdefault(start, []).append(cast(str, item["id"]))
    for candidate in cast(list[JSON], packet["candidates"]):
        ids = cast(list[str], candidate["evidence_ids"])
        for target in cast(list[JSON], candidate["targets"]):
            ids.extend(i for i in routes.get(cast(str, target["id"]), []) if i not in ids)


class NetworkPaths:
    """What stream A's `add_network_paths` needs to cite routes in the protein network."""

    def __init__(
        self,
        *,
        paths: dict[str, list[JSON]],
        graph: JSON,
        symbols: dict[str, str],
        string_mappings: list[JSON],
        disease_target_ids: list[str],
    ) -> None:
        self.paths = paths
        """Each Candidate's representative paths (stream B's `representatives`)."""
        self.graph = graph
        self.symbols = symbols
        self.string_mappings = string_mappings
        self.disease_target_ids = disease_target_ids
        self.coverage: JSON = {}
        """Filled by the build: the routes left out for a missing symbol or STRING ID."""


# ---------------------------------------------------------------------------
# The STRING protein mapping (A3).
# ---------------------------------------------------------------------------

STRING_VERSION = "12.5"


def string_mapping(protein_info: Path, target_parts: list[Path]) -> JSON:
    """A3: every human STRING 12.5 protein mapped to an Open Targets 26.09 gene by exact
    Ensembl protein ID (`pipeline.string_map.build_mapping`), from the downloaded STRING
    protein list and the Open Targets target Parquet parts."""
    return cast(
        JSON,
        _string_map.build_mapping(
            _string_map.read_string_ids(protein_info),
            _string_map.read_targets(target_parts),
            STRING_VERSION,
        ),
    )


def direct_shortlist(drugs: list[JSON], scores: dict[str, float]) -> tuple[list[str], int]:
    """Stream A's direct-evidence baseline: the 15 regulator-approved drugs whose best
    Target has the highest evidence-only score, ties by ChEMBL ID; and how many drugs
    have any positive score. Raises ValueError on malformed IDs."""
    ids, eligible = _experiment.direct_shortlist(drugs, scores)
    return cast(list[str], ids), cast(int, eligible)


# ---------------------------------------------------------------------------
# Data preparation.
# ---------------------------------------------------------------------------


def chembl_cache(data_dir: Path, client: httpx.Client) -> Any:
    """Stream A's resumable ChEMBL and Open Targets download cache over `data_dir`."""
    return _a2.Cache(data_dir, client)


def download_dataset(cache: Any, dataset: str) -> list[Path]:
    """Download one Open Targets 26.09 Parquet dataset (skipping complete files)."""
    return cast(list[Path], cache.parquet(dataset))


def build_drug_universe(cache: Any) -> JSON:
    """A2: the regulator-approved drug universe with each drug's human Targets."""
    return cast(JSON, _a2.run(cache))


def write_json(path: Path, value: object) -> None:
    """Stream A's atomic JSON writer."""
    _a2.write_json(path, value)


# ---------------------------------------------------------------------------
# Model jury.
# ---------------------------------------------------------------------------


def jury_settings() -> JSON:
    """Stream A's shared jury settings (`jury/config.json`): temperature, attempts, seed."""
    return cast(JSON, json.loads(JURY_CONFIG_PATH.read_text(encoding="utf-8")))


def validate_packet(packet: JSON) -> None:
    _jury.validate_packet(packet)


def run_jury(
    packet: JSON,
    config: JSON,
    model_call: ModelCall,
    *,
    on_juror: Callable[[JSON], None] | None = None,
) -> JSON:
    """Ask every juror at once and combine the valid ballots. `on_juror` receives each
    juror's result as soon as that juror finishes, from the juror's own thread."""
    return cast(
        JSON, _jury.run_jury(packet, config, model_call, on_juror=on_juror, concurrent=True)
    )


mock_model = cast(ModelCall, _jury.mock_model)
"""Stream A's offline practice reviewer: placeholder ballots, never a scientific vote."""


class CortexModel(Protocol):
    def __call__(self, model: str, prompt: str, temperature: float) -> object: ...

    def close(self) -> None: ...


def cortex_model(reasoning_effort: dict[str, str]) -> CortexModel:
    """Stream A's Snowflake Cortex client. Reads SNOWFLAKE_ACCOUNT and SNOWFLAKE_PAT."""
    factory = cast(Callable[..., CortexModel], _jury.CortexModel)
    return factory(reasoning_effort=reasoning_effort)
