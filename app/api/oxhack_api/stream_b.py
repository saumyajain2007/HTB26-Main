"""The one place the API calls stream B: Zaid's `ranking/` at the repository root.

Stream B is untyped Python over JSON-shaped dicts, like stream A. This module gives
each call the API makes a typed signature, so strict type checking holds everywhere
else, and it is the only file that relaxes it for stream B. It adds no rule of its
own: the graph build, the network-proximity scoring, the shortlist policy and the
shortest-path reconstruction are all stream B's.

Stream B documents its inputs and outputs in `ranking/README.md` (the artefact
bundle), `ranking/STAGE2.md` (ranking), `ranking/RWR.md` (random walk with restart),
`ranking/SHORTLIST_HANDOFF.md` (shortlist methods) and `ranking/NETWORK_PATHS.md` (paths).
"""

# Stream B has no type annotations on most functions; only this module sees its Unknowns.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnnecessaryCast=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from ranking import artifacts as _artifacts
from ranking import data as _data
from ranking import functional_graph as _functional_graph
from ranking import paths as _paths
from ranking import rwr as _rwr
from ranking import scoring as _scoring
from ranking import shortlist as _shortlist

from .settings import NETWORK_BUNDLE

JSON = dict[str, Any]

BUNDLE_NAME = NETWORK_BUNDLE
"""The artefact bundle the API ranks with: STRING 12.5 physical links, combined score at
least 700 and direct experiments at least 400 (stream B's defaults)."""
GRAPH_VERSION = "string-12.5"
MIN_COMBINED_SCORE = 700
MIN_EXPERIMENTS = 400

Settings = _scoring.RankingSettings
"""Stream B's `RankingSettings`: top_targets, randomisations, seed, min_bin_size and the
10 network + 5 evidence shortlist quotas."""

RwrSettings = _rwr.RWRSettings
"""Stream B's `RWRSettings`: restart probability 0.3, tolerance 1e-12, at most 1,000
iterations, top 50 Disease Targets (`ranking/rwr_protocol.json`)."""

SHORTLIST_METHOD = "physical_rwr"
"""Stream B's application default (`ranking/application/shortlist.py`): the random
walk on the physical network fills the 10 network places. `zscore` is the original
closeness policy, kept for the frozen replays."""


def bundle_ready(directory: Path) -> bool:
    """True when the bundle was published: stream B writes manifest.json last, atomically."""
    return (directory / "manifest.json").is_file()


def build_bundle(
    mapping: Path,
    links: Path,
    output: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> JSON:
    """Build the graph and the largest component's distance matrix (stream B Stage 1).
    Publishes `output` only when complete, and never overwrites it. Returns the manifest."""
    return cast(
        JSON,
        _artifacts.build_artifacts(
            mapping,
            links,
            output,
            min_combined_score=MIN_COMBINED_SCORE,
            min_experiments=MIN_EXPERIMENTS,
            progress=progress,
        ),
    )


class Bundle:
    """A loaded, checksum-verified artefact bundle; the distance matrix stays memory-mapped."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._artifacts = _artifacts.load_artifacts(directory)
        self.manifest = cast(JSON, self._artifacts.manifest)
        self.graph_gene_ids = cast(tuple[str, ...], self._artifacts.graph_gene_ids)
        self.distance_gene_ids = frozenset(cast(tuple[str, ...], self._artifacts.distance_gene_ids))
        self._graph_index = {gene: i for i, gene in enumerate(self.graph_gene_ids)}

    @property
    def graph_provenance(self) -> JSON:
        """The pinned graph's description, in the shape stream A's `add_network_paths`
        checks (`network_paths_provenance.graph` in stream B's path export)."""
        return {
            "graph_version": GRAPH_VERSION,
            "releases": self.manifest["releases"],
            "filters": self.manifest["filters"],
            "scope": "largest_connected_component",
            "provenance": "derived_from_pinned_filtered_STRING_graph",
            "edge_level_citations": "not_retained",
            "undirected": True,
            "unweighted": True,
            "artifact_files": self.manifest["files"],
        }

    def neighbours(self, gene: str) -> list[str]:
        """The genes linked to `gene` in the saved graph (empty when it is not in it)."""
        index = self._graph_index.get(gene)
        if index is None:
            return []
        graph = self._artifacts.graph
        row = graph.indices[graph.indptr[index] : graph.indptr[index + 1]]
        return [self.graph_gene_ids[int(i)] for i in row]

    def engine(self, settings: Any, rwr: Any) -> Engine:
        return Engine(self, settings, rwr)

    def paths(self, disease_target_ids: Sequence[str]) -> Paths:
        return Paths(self, disease_target_ids)

    def close(self) -> None:
        self._artifacts.close()


class Engine:
    """Stream B's `RankingEngine` and physical `RWREngine` over one bundle; reuse it for
    every Disease."""

    def __init__(self, bundle: Bundle, settings: Any, rwr: Any) -> None:
        if rwr.top_targets != settings.top_targets:
            raise ValueError("the random walk and the closeness ranking use different Targets")
        self._engine = _scoring.RankingEngine(bundle._artifacts, settings)  # pyright: ignore[reportPrivateUsage]
        # Stream B's own loader, which checks the graph again; RWR needs no distances.
        self._rwr = _rwr.RWREngine(_functional_graph.load_rwr_graph(bundle.directory), rwr)
        self.settings = settings
        self.rwr_settings = rwr

    def rank(self, disease: JSON, drugs: Drugs) -> JSON:
        """Stream B's full ranking (format v2) of every approved drug for the Disease, with
        each drug's physical random-walk result under `rwr.physical` (`enrich_ranking`).

        `disease` is a stream B Disease file in memory: `disease_id`, `disease_name`,
        `release`, `rule` and `targets` (`target_id`, `evidence_only_score`)."""
        loaded = _disease(disease)
        ranking = self._engine.rank(loaded, drugs.loaded)
        walk = self._rwr.rank(loaded, drugs.loaded)
        if walk["convergence"]["status"] != "converged":
            raise ValueError(f"the random walk did not converge: {walk['convergence']}")
        return cast(JSON, _rwr.enrich_ranking(ranking, walk, "physical"))


class Drugs:
    """Stream B's view of the approved drug universe (`drug_targets.json`, stream A A2)."""

    def __init__(self, path: Path) -> None:
        self.loaded = _data.load_drugs(path)

    @property
    def ids(self) -> frozenset[str]:
        """ChEMBL IDs of the drugs stream B ranks (those with a regulator approval)."""
        return frozenset(cast(str, drug.id) for drug in self.loaded.drugs)


def _disease(record: JSON) -> Any:
    """`ranking.data.load_disease`, from a record instead of a file, with its checks."""
    rule = record.get("rule", {})
    if (
        not isinstance(rule, dict)
        or rule.get("score") != "evidence_only"
        or not {"clinical_precedence", "cancer_biomarkers"}.issubset(
            cast(list[str], rule.get("excluded_datasources", []))
        )
    ):
        raise ValueError(
            "Disease Targets must be evidence-only scores without clinical precedence and "
            "cancer biomarkers"
        )
    disease_id = cast(str, record["disease_id"])
    if not _data.DISEASE_ID.fullmatch(disease_id):
        raise ValueError(f"Invalid Disease ID {disease_id!r}")
    return _data.Disease(
        disease_id,
        cast(str, record.get("disease_name") or disease_id),
        cast(str, record["release"]),
        rule,
        _data.normalise_targets(record["targets"], disease=True),
        {"path": None, "note": "in memory: the Experiment's Disease Targets"},
    )


def rerank(result: JSON, exclude: frozenset[str], settings: Any) -> JSON:
    """The ranking as if the excluded drugs had never been in the universe.

    Stream B's scores of a drug do not depend on the other drugs (each degree profile
    has its own seeded draws, and the random walk starts from the Disease Targets
    only), so only the ranks and the shortlist change: they are assigned again with
    stream B's own `assign_ranks` and `make_shortlist`, and random-walk ranks in
    `RWREngine.rank`'s order (higher mass first, then ChEMBL ID).
    """
    kept = deepcopy([c for c in result["candidates"] if c["candidate_id"] not in exclude])
    for candidate in kept:
        if candidate["network"] is not None:
            candidate["network"]["rank"] = None
        candidate.update(
            direct_evidence_rank=None,
            shared_target_rank=None,
            selected_by=[],
            selection_reasons=[],
            shortlist_rank=None,
        )
    _scoring.assign_ranks(kept)
    walks = [c["rwr"]["physical"] for c in kept if "rwr" in c]
    scored = sorted(
        (c for c in kept if "rwr" in c and c["rwr"]["physical"]["score"] is not None),
        key=lambda c: (-c["rwr"]["physical"]["score"], c["candidate_id"]),
    )
    for walk in walks:
        walk["rank"] = None
    for rank, candidate in enumerate(scored, 1):
        candidate["rwr"]["physical"]["rank"] = rank
    shortlist = cast(list[str], _scoring.make_shortlist(kept, settings))
    return {**result, "candidates": kept, "shortlist": shortlist}


def select(result: JSON, method: str, settings: Any) -> JSON:
    """The ranking with its shortlist chosen by `method` (stream B's `project_shortlist`):
    physical_rwr fills the network places from the random walk, zscore keeps stream B's
    original closeness shortlist. Same quotas, deduplication and fill either way."""
    if method == "zscore":
        return result
    return cast(
        JSON,
        _shortlist.project_shortlist(
            result,
            _shortlist.ShortlistSettings(
                method=method,
                network_slots=settings.network_slots,
                evidence_slots=settings.evidence_slots,
            ),
        ),
    )


class Paths:
    """Stream B's deterministic shortest paths from drug Targets to the Disease Targets."""

    def __init__(self, bundle: Bundle, disease_target_ids: Sequence[str]) -> None:
        self._paths = _paths.PathReconstructor(bundle._artifacts, list(disease_target_ids))  # pyright: ignore[reportPrivateUsage]

    def nearest(self, drug_target_ids: Sequence[str]) -> list[JSON]:
        """One verified nearest path per drug Target (`status` available or unavailable)."""
        return [cast(JSON, self._paths.nearest_path(gene)) for gene in drug_target_ids]


def representatives(paths: Sequence[JSON]) -> list[JSON]:
    """At most three available paths: shortest, lower median and longest (stream B's rule),
    ordered by hops, drug Target ID, Disease Target ID and the full path."""
    return cast(list[JSON], _paths.representatives(list(paths)))
