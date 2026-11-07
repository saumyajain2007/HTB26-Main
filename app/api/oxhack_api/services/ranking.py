"""The ranking seam: how the live source picks a Disease's shortlist.

`LiveSource` hands a `RankingBackend` the Disease's Targets, every Target's
evidence-only score and the approved drug universe, and gets back the shortlist
in order, with why each drug was selected.

- `NetworkRanking` is stream B's network ranking (Zaid's `ranking.scoring.RankingEngine`
  and `ranking.rwr.RWREngine`) over the protein network bundle that
  `python -m oxhack_api.prepare` builds. Live mode uses it whenever that bundle
  exists.
- `EvidenceRanking` is plan.md section 4.4's transparent fallback: stream A's
  direct Target-evidence baseline (`pipeline.experiment.direct_shortlist`). The
  Experiment says so (`ranking_method` evidence_only): no network is drawn, no
  network score is invented, and every Candidate is `not_scorable` with
  `network_unavailable`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from .. import stream_b
from ..schemas import (
    SHORTLIST_MAX,
    CandidateNetwork,
    CandidateRwr,
    CandidateStatus,
    DataRelease,
    NetworkEdge,
    NetworkGraph,
    NetworkNode,
    NetworkRole,
    NetworkWarning,
    RankingMethod,
    RankingSettings,
    SelectedBy,
    SelectionReason,
    ShortlistMethod,
    TargetExcludedReason,
    UnscorableReason,
)
from ..stream_a import JSON, OT_RELEASE, direct_shortlist

log = logging.getLogger(__name__)

EVIDENCE_ONLY_RULE: Mapping[str, object] = {
    "score": "evidence_only",
    "excluded_datasources": ["clinical_precedence", "cancer_biomarkers"],
}
"""Stream A A1's scoring rule: Open Targets association scores without clinical precedence
and cancer biomarker evidence."""


@dataclass(frozen=True)
class RankingInput:
    """What a ranking sees. Nothing here names a drug's indications or trials."""

    disease_id: str
    target_ids: list[str]
    """The selected Disease Targets (the top `top_targets` by evidence-only score)."""
    scores: Mapping[str, float]
    """Evidence-only association score of every Target associated with the Disease."""
    drugs: Sequence[JSON]
    """The approved drug universe: `drug_targets.json` rows (stream A A2)."""
    symbols: Mapping[str, str] = field(default_factory=dict[str, str])
    """Gene symbol of every Open Targets Target, by Ensembl ID, to label the network."""
    release: str = OT_RELEASE
    """The Open Targets release the scores come from."""
    rule: Mapping[str, object] = field(default_factory=lambda: dict(EVIDENCE_ONLY_RULE))
    """How the scores were computed (stream A A1's `rule`)."""


@dataclass(frozen=True)
class Ranked:
    """One shortlisted drug, as the ranking placed it."""

    candidate_id: str
    status: CandidateStatus
    selected_by: list[SelectedBy]
    selection_reasons: list[SelectionReason]
    network: CandidateNetwork | None
    unscorable_reason: UnscorableReason | None
    direct_evidence_rank: int | None
    routes: list[JSON] = field(default_factory=list[JSON])
    """At most three representative shortest paths from the drug's Targets to the Disease
    Targets (stream B's `representatives`); empty without a network result."""


@dataclass(frozen=True)
class Ranking:
    """A ranking's shortlist, in shortlist order, and what it used."""

    shortlist: list[Ranked]
    eligible: int
    """Drugs the ranking could place at all, of which the shortlist is the top."""
    network: NetworkGraph | None
    """The subgraph to draw; None when no network ranking ran."""
    excluded_targets: dict[str, TargetExcludedReason] = field(
        default_factory=dict[str, TargetExcludedReason]
    )
    """Disease Targets the ranking could not use, and why; the rest are retained."""
    graph: JSON | None = None
    """The protein network the routes were found in (stream B's graph provenance), for the
    route evidence; None when no network ranking ran."""
    retained_target_ids: list[str] = field(default_factory=list[str])
    """The Disease Targets in the network's largest component: where routes end."""
    full: JSON | None = None
    """Stream B's complete output (every eligible drug), archived with the Experiment."""


class RankingBackend(Protocol):
    method: RankingMethod
    releases: list[DataRelease]
    """Releases the ranking adds to the Experiment's, e.g. the network's string-12.5."""

    def settings(self) -> RankingSettings: ...

    def rank(self, request: RankingInput, exclude: frozenset[str]) -> Ranking:
        """The shortlist of at most SHORTLIST_MAX drugs, leaving out `exclude` (drugs the
        caller found ineligible, e.g. with no confirmed regulator approval). The same
        input always gives the same result."""
        ...


class EvidenceRanking:
    """plan.md section 4.4: "Evidence ranking - network unavailable".

    Stream A's direct Target-evidence baseline, unchanged: each regulator-approved
    drug scores the highest evidence-only association score among its own Targets
    (every Target associated with the Disease counts, not only the top 50); drugs
    with no positive score are left out; the rest are ranked by that score, highest
    first, ties broken by ChEMBL ID in string order; the top 15 are the shortlist.
    No drug name, indication or trial is looked at.
    """

    method: RankingMethod = "evidence_only"

    def __init__(self, top_targets: int = 50) -> None:
        self._top_targets = top_targets
        self.releases: list[DataRelease] = []

    def settings(self) -> RankingSettings:
        return RankingSettings(
            top_targets=self._top_targets,
            randomisations=None,
            seed=None,
            min_bin_size=None,
            shortlist_method=None,
            restart_probability=None,
            network_slots=0,
            evidence_slots=SHORTLIST_MAX,
        )

    def rank(self, request: RankingInput, exclude: frozenset[str]) -> Ranking:
        drugs = [drug for drug in request.drugs if drug["drug_id"] not in exclude]
        ids, eligible = direct_shortlist(drugs, dict(request.scores))
        shortlist = [
            Ranked(
                candidate_id=candidate_id,
                status="not_scorable",
                selected_by=["evidence"],
                selection_reasons=["evidence_ranking_network_unavailable"],
                network=None,
                unscorable_reason="network_unavailable",
                direct_evidence_rank=rank,
            )
            for rank, candidate_id in enumerate(ids, 1)
        ]
        return Ranking(shortlist=shortlist, eligible=eligible, network=None)


class NetworkRanking:
    """Stream B's network ranking (Zaid's `ranking.scoring.RankingEngine` for closeness and
    `ranking.rwr.RWREngine` for the random walk with restart).

    Reads the artefact bundle `python -m oxhack_api.prepare` builds (stream B's
    `ranking/README.md`: the STRING 12.5 physical network and its distance matrix) and
    the approved drug universe stream B reads, `drug_targets.json`. Both are loaded once,
    on first use or by `warm()`, on a background or job thread, never a request thread.

    Each Disease is ranked once (about 5 s); a shortlist that drops ineligible drugs is
    re-ranked from the same result with stream B's own rank and shortlist functions, as
    stream B's scores of a drug do not depend on the other drugs. From stream B's output:

    - statuses (`scored`, `distance_only`, `not_scorable`), network results and coded
      reasons pass through unchanged; each placed drug's `path` is its shortest route
      (stream B's first representative path);
    - the shortlist is stream B's: 10 network + 5 evidence, deduplicated, then filled
      from the next supported evidence and then network results, with each reason. The
      network places come from the random walk on the physical network (stream B's
      application default, `physical_rwr`) unless `shortlist_method` is `zscore`;
    - every placed drug carries both network results: its closeness (`network`) and,
      with physical_rwr, its random-walk rank and mass (`network.rwr`);
    - `direct_evidence_rank` is stream B's evidence rank of drugs with direct support;
      a drug with none gets null, not the rank of an arbitrary tie at zero;
    - Disease Targets outside the network or its largest component are
      `excluded_targets`;
    - the subgraph to draw holds the shortlisted drugs' routes and the Disease
      Targets linked to them (`subgraph`).

    Stream B selects the top 50 Disease Targets itself and uses every supplied score for
    its direct-evidence baseline, so it gets every association, not only the top 50.
    """

    method: RankingMethod = "network"

    def __init__(
        self,
        bundle_dir: Path,
        drugs_path: Path,
        *,
        min_bin_size: int | None = None,
        shortlist_method: ShortlistMethod = stream_b.SHORTLIST_METHOD,
        cache_size: int = 4,
    ) -> None:
        """`min_bin_size` overrides stream B's 100 proteins per degree group; tests on tiny
        graphs need fewer. `shortlist_method` zscore restores the original closeness
        shortlist. Everything else is stream B's default."""
        if not stream_b.bundle_ready(bundle_dir):
            raise FileNotFoundError(f"No protein network bundle in {bundle_dir}")
        self.releases: list[DataRelease] = [stream_b.GRAPH_VERSION]
        self._bundle_dir = bundle_dir
        self._drugs_path = drugs_path
        self._settings = (
            stream_b.Settings()
            if min_bin_size is None
            else stream_b.Settings(min_bin_size=min_bin_size)
        )
        self._method: ShortlistMethod = shortlist_method
        self._rwr_settings = stream_b.RwrSettings(top_targets=self._settings.top_targets)
        self._lock = threading.Lock()
        self._loaded: tuple[stream_b.Bundle, stream_b.Engine, stream_b.Drugs] | None = None
        self._results: OrderedDict[str, JSON] = OrderedDict()
        self._cache_size = cache_size

    def settings(self) -> RankingSettings:
        settings = self._settings
        return RankingSettings(
            top_targets=settings.top_targets,
            randomisations=settings.randomisations,
            seed=settings.seed,
            min_bin_size=settings.min_bin_size,
            shortlist_method=self._method,
            restart_probability=self._rwr_settings.restart_probability
            if self._method == "physical_rwr"
            else None,
            network_slots=settings.network_slots,
            evidence_slots=settings.evidence_slots,
        )

    def warm(self) -> None:
        """Load the bundle and the engine now, so the first build does not wait."""
        self._load()

    def _load(self) -> tuple[stream_b.Bundle, stream_b.Engine, stream_b.Drugs]:
        with self._lock:
            if self._loaded is None:
                bundle = stream_b.Bundle(self._bundle_dir)
                self._loaded = (
                    bundle,
                    bundle.engine(self._settings, self._rwr_settings),
                    stream_b.Drugs(self._drugs_path),
                )
                log.info("protein network loaded from %s", self._bundle_dir)
            return self._loaded

    def rank(self, request: RankingInput, exclude: frozenset[str]) -> Ranking:
        bundle, engine, drugs = self._load()
        universe = {cast(str, drug["drug_id"]) for drug in request.drugs}
        if not drugs.ids <= universe:
            raise ValueError("the network ranking reads a different drug universe")
        full = self._full(request, engine, drugs)
        selected = cast(list[str], full["disease"]["selected_target_ids"])
        if selected != list(request.target_ids):
            raise ValueError("the network ranking selected different Disease Targets")
        result = stream_b.select(
            stream_b.rerank(full, exclude, self._settings) if exclude else full,
            self._method,
            self._settings,
        )
        candidates = {c["candidate_id"]: c for c in result["candidates"]}
        coverage = full["disease"]["coverage"]
        retained = cast(list[str], coverage["retained_target_ids"])
        paths = bundle.paths(retained)
        walked = self._method == "physical_rwr"
        shortlist = [
            _ranked(candidates[cid], paths, walked=walked)
            for cid in cast(list[str], result["shortlist"])
        ]
        return Ranking(
            shortlist=shortlist,
            eligible=len(result["candidates"]),
            network=subgraph(
                bundle,
                shortlist,
                [candidates[r.candidate_id] for r in shortlist],
                selected,
                set(retained),
                request.symbols,
            ),
            excluded_targets=_excluded_targets(coverage, selected),
            graph=bundle.graph_provenance,
            retained_target_ids=retained,
            full=result,
        )

    def _full(self, request: RankingInput, engine: stream_b.Engine, drugs: stream_b.Drugs) -> JSON:
        """Stream B's ranking of the Disease, computed once per set of scores."""
        disease: JSON = {
            "disease_id": request.disease_id,
            "disease_name": request.disease_id,
            "release": request.release,
            "rule": dict(request.rule),
            "targets": [
                {"target_id": gene, "evidence_only_score": score}
                for gene, score in sorted(request.scores.items())
            ],
        }
        key = hashlib.sha256(json.dumps(disease, sort_keys=True).encode()).hexdigest()
        with self._lock:
            if key in self._results:
                self._results.move_to_end(key)
                return self._results[key]
        result = engine.rank(disease, drugs)
        with self._lock:
            self._results[key] = result
            while len(self._results) > self._cache_size:
                self._results.popitem(last=False)
        return result


def _ranked(candidate: JSON, paths: stream_b.Paths, *, walked: bool) -> Ranked:
    """One of stream B's shortlisted Candidates, in the contract's terms. `walked`: the
    Experiment shows the random walk (`physical_rwr`)."""
    network: CandidateNetwork | None = None
    routes: list[JSON] = []
    result = cast(JSON | None, candidate["network"])
    walk = cast(JSON, candidate["rwr"]["physical"])
    # Both rankings keep the drug Targets in the same largest component, so a drug the
    # walk reaches always has a closeness result too, and the other way round.
    if (walk["status"] == "scored") != (result is not None):
        raise ValueError(f"{candidate['candidate_id']} is placed by only one network ranking")
    if result is not None:
        retained = cast(list[str], candidate["coverage"]["retained_target_ids"])
        routes = stream_b.representatives(paths.nearest(retained))
        if not routes:
            raise ValueError(f"{candidate['candidate_id']} has a network result but no route")
        network = CandidateNetwork(
            rank=cast(int, result["rank"]),
            rwr=CandidateRwr(rank=cast(int, walk["rank"]), mass=cast(float, walk["score"]))
            if walked
            else None,
            mean_distance=cast(float, result["mean_distance"]),
            degree_matched_z=cast(float | None, result["degree_matched_z"]),
            graph_version=cast(str, result["graph_version"]),
            warning=cast(NetworkWarning | None, result["warning"]),
            path=cast(list[str], routes[0]["target_ids"]),
        )
    supported = candidate["direct_evidence"]["status"] == "supported"
    return Ranked(
        candidate_id=cast(str, candidate["candidate_id"]),
        status=cast(CandidateStatus, candidate["status"]),
        selected_by=cast(list[SelectedBy], candidate["selected_by"]),
        selection_reasons=cast(list[SelectionReason], candidate["selection_reasons"]),
        network=network,
        unscorable_reason=cast(UnscorableReason | None, candidate["unscorable_reason"]),
        direct_evidence_rank=cast(int | None, candidate["direct_evidence_rank"])
        if supported
        else None,
        routes=routes,
    )


_TARGET_REASONS: dict[str, TargetExcludedReason] = {
    "not_in_graph": "not_in_graph",
    "outside_largest_component": "outside_largest_component",
}


def _excluded_targets(coverage: JSON, selected: list[str]) -> dict[str, TargetExcludedReason]:
    """Why each selected Disease Target is not in the network's largest component."""
    chosen = set(selected)
    excluded: dict[str, TargetExcludedReason] = {}
    for row in cast(list[JSON], coverage["excluded_targets"]):
        gene, reason = row["target_id"], cast(str, row["reason"])
        if gene not in chosen:
            continue
        if reason not in _TARGET_REASONS:
            raise ValueError(f"Disease Target {gene} was excluded for {reason}")
        excluded[gene] = _TARGET_REASONS[reason]
    return excluded


SUBGRAPH_NODES = 40
"""Most proteins the drawn network holds, beyond the shortest routes it must show."""


def subgraph(
    bundle: stream_b.Bundle,
    shortlist: Sequence[Ranked],
    candidates: Sequence[JSON],
    selected: Sequence[str],
    retained: set[str],
    symbols: Mapping[str, str],
    *,
    limit: int = SUBGRAPH_NODES,
) -> NetworkGraph:
    """The small network the UI draws: the routes from the shortlisted drugs' Targets to
    the Disease Targets, and every high-confidence link between the proteins drawn.

    Proteins are added in this order while fewer than `limit` are drawn:
    1. each placed drug's shortest route (always, so every drug's `path` can be drawn);
    2. Disease Targets, strongest evidence first, that link to a protein already drawn
       (the first one starts the drawing when no drug is placed);
    3. the drugs' other representative routes, whole, in shortlist order.
    """
    nodes: dict[str, None] = {}

    def add(ids: Iterable[str], *, force: bool = False) -> bool:
        new = [gene for gene in ids if gene not in nodes]
        if not force and len(nodes) + len(new) > limit:
            return False
        nodes.update(dict.fromkeys(new))
        return True

    for ranked in shortlist:
        if ranked.network is not None:
            add(ranked.network.path, force=True)
    added = True
    while added and len(nodes) < limit:
        added = False
        for gene in selected:
            if gene in nodes or gene not in retained:
                continue
            if not nodes or any(n in nodes for n in bundle.neighbours(gene)):
                added = add([gene]) or added
    for ranked in shortlist:
        for route in ranked.routes[1:]:
            add(cast(list[str], route["target_ids"]))
    drug_targets = {target["id"] for candidate in candidates for target in candidate["targets"]}
    disease = set(selected) & retained

    def role(gene: str) -> NetworkRole:
        if gene in disease:
            return "both" if gene in drug_targets else "disease"
        return "drug" if gene in drug_targets else "link"

    edges = sorted(
        {
            (min(a, b), max(a, b))
            for a in nodes
            for b in bundle.neighbours(a)
            if b in nodes and a != b
        }
    )
    return NetworkGraph(
        graph_version=stream_b.GRAPH_VERSION,
        nodes=[
            NetworkNode(id=gene, symbol=symbols.get(gene, gene), role=role(gene)) for gene in nodes
        ],
        edges=[NetworkEdge(source=a, target=b) for a, b in edges],
    )


def archive_full(path: Path, result: JSON) -> JSON:
    """Write stream B's complete ranking, gzipped, and return its size and SHA-256."""
    data = gzip.compress(json.dumps(result, sort_keys=True, allow_nan=False).encode(), mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(data)
    partial.replace(path)
    return {"file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
