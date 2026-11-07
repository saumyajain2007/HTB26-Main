"""The live source (`OXHACK_SOURCE=live`): stream A's pipeline over the prepared data.

Prepare the data first with `uv run python -m oxhack_api.prepare`. A build runs
on the job's thread, in the stages the job runner reports:

- **targets**: stream A's A1 (`pipeline.disease_targets`): every Open Targets
  26.09 association of the Disease, rescored without clinical-precedence and
  cancer-biomarker evidence; the top 50 are the Disease Targets. The network
  ranking keeps those in its protein network (`retained`); with no network
  ranking every Target is kept.
- **ranking**: the `RankingBackend` (stream B's network ranking when its bundle
  is prepared, else the evidence ranking) ranks the approved drug universe
  (`drug_targets.json`, stream A's A2) into a shortlist of at most 15. A
  shortlisted drug that ChEMBL does not list as its own parent, or whose
  regulator-backed approval Open Targets cannot confirm, is left out and the next
  one takes its place; this is stream A's rule from `pipeline.experiment`.
- **evidence**: stream A's A4 (`build_evidence_packet`): each Candidate's
  sourced evidence, warnings and PubChem ID, the Reactome pathways its Targets
  share with the Disease Targets, and, with the network ranking, its
  representative routes in the protein network (`add_network_paths`). Every
  item's plain `summary` is built with `plain.py` from structured records (the
  association score, the ChEMBL mechanism record, the bioactivity pair, the
  approval report, the warning's toxicity class, the route's proteins, the
  pathway's members), never by reading the `statement` text.

Each build also writes its audit trail to `<data_dir>/experiments/<id>/`: the
Disease Targets, the ranking (with stream B's complete output, gzipped, and its
SHA-256), the jury evidence packet, mapping coverage and stream A's bioactivity
cross-check.

**Known answer.** A Candidate is the Experiment's known-answer check when stream
A's drug universe records a regulator-backed approval of it for this exact
Disease: an Open Targets 26.09 APPROVAL indication with an FDA, EMA, PMDA or
DailyMed report, or one of stream A's curated regulator records
(`pipeline/approval_overrides.json`, e.g. baricitinib for COVID-19). Stage data
lags regulators, so some real approvals are missing. The flag is computed after
ranking and never feeds it, but it is not a blind test: the evidence-only
association scores still include literature and other evidence that may reflect
the known use, so finding a known answer checks the pipeline, not a discovery
(plan.md section 6.3).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import duckdb
import httpx

from ..schemas import (
    Candidate,
    CandidateTarget,
    DataRelease,
    DiseaseRef,
    DiseaseSearchResult,
    DiseaseTarget,
    EvidenceItem,
    Warning,
)
from ..stream_a import (
    CHEMBL_RELEASE,
    DISEASE_PARQUET,
    JSON,
    OT_DATASETS,
    OT_RELEASE,
    EvidenceSources,
    NetworkPaths,
    OpenTargetsError,
    Pathways,
    reactome_release,
    write_json,
)
from . import plain
from .ranking import Ranking, RankingBackend, RankingInput, archive_full
from .source import BuildResult, BuildSteps, EarlyResult, ExperimentPlan, SourceError

log = logging.getLogger(__name__)

COMMON_DISEASES = (
    "MONDO_0100096",  # COVID-19: shown first; finds baricitinib, the known-answer check
    "MONDO_0008383",  # rheumatoid arthritis
    "MONDO_0005083",  # psoriasis
    "MONDO_0044903",  # myelofibrosis: fedratinib, the known answer, docks into JAK2
    "MONDO_0009891",  # acquired polycythemia vera: pacritinib, the known answer, into JAK2
    "MONDO_0004948",  # B-cell chronic lymphocytic leukemia: venetoclax into its own BCL2 crystal
    "MONDO_0004980",  # atopic eczema: tofacitinib and midostaurin into JAK2
)
"""Well-known Diseases offered before a search, each with binding poses to show. Each was
built live on 25 Oct 2026 (Open Targets 26.09, STRING 12.5) to a full shortlist of 15, and at
least one of its drugs docks into a prepared structure (worker/structures: JAK2, BCL2, CRBN)."""

NOT_DISEASE_AREAS = (
    "EFO_0001444",  # measurement: blood pressure, LDL cholesterol, biomarker levels
    "EFO_0000651",  # phenotype: a symptom or sign, not a Disease
    "GO_0008150",  # biological process
    "MONDO_0005583",  # non-human animal disease
    "EFO_0002571",  # medical procedure
)
"""Open Targets therapeutic areas that aren't diseases. An entry filed only under these
is left out of search; one also filed under a disease area (asthma is also a phenotype)
stays."""

MIN_TESTED_DRUGS = 3
"""Search lists a Disease only when at least this many drugs reached phase 2 or later for it.
Diseases nobody has tried to treat (most rare monogenic syndromes, "susceptibility to"
entries) give a thin shortlist and nothing for the jury to weigh, so they aren't what the
app is for. 1,757 Diseases in Open Targets 26.09 qualify, every common one among them."""

TESTED_STAGES = ("PHASE_2", "PHASE_2_3", "PHASE_3", "PHASE_4", "APPROVAL")

PREPARE_HINT = "Run `uv run python -m oxhack_api.prepare` first."
STRING_MAP = Path("string_id_map.json")
"""Stream A's STRING-to-gene mapping (A3) under the data folder; network routes cite it."""

Dockable = Callable[[str, Sequence[str]], bool]
"""Whether a binding pose can be computed for a drug (by ChEMBL ID) acting on these Targets."""


class DataNotPrepared(RuntimeError):
    """The data folder is missing what the live source reads."""


# ---------------------------------------------------------------------------
# Disease search and resolution, over the Open Targets disease listing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiseaseEntry:
    id: str
    name: str
    description: str | None
    exact_synonyms: tuple[str, ...]
    other_synonyms: tuple[str, ...]
    obsolete_ids: tuple[str, ...]


class DiseaseCatalogue:
    """Every Disease in the Open Targets 26.09 listing, kept in memory (about 46,000).

    Any of them resolves by ID, so saved Experiments keep working, but search lists only
    the investigable ones: real diseases (`NOT_DISEASE_AREAS`) that drugs have been tested
    for (`MIN_TESTED_DRUGS`). Without `indications`, search lists every entry.
    """

    def __init__(self, path: Path, indications: Path | None = None) -> None:
        with duckdb.connect() as connection:
            rows = connection.execute(
                """
                select id, name, description, exactSynonyms,
                       list_concat(relatedSynonyms, narrowSynonyms, broadSynonyms),
                       obsoleteTerms
                from read_parquet(?)
                """,
                [str(path)],
            ).fetchall()
            searchable = (
                None
                if indications is None
                else {
                    disease_id
                    for (disease_id,) in connection.execute(
                        """
                        select d.id
                        from read_parquet(?) d
                        join read_parquet(?) i on i.diseaseId = d.id
                        where len(list_filter(coalesce(d.therapeuticAreas, []),
                                              lambda area: not list_contains(?, area))) > 0
                          and list_contains(?, i.maxClinicalStage)
                        group by d.id
                        having count(distinct i.drugId) >= ?
                        """,
                        [
                            str(path),
                            str(indications / "*.parquet"),
                            list(NOT_DISEASE_AREAS),
                            list(TESTED_STAGES),
                            MIN_TESTED_DRUGS,
                        ],
                    ).fetchall()
                }
            )
        listing = cast(
            list[tuple[str, str, str | None, list[str] | None, list[str] | None, list[str] | None]],
            rows,
        )
        self._entries = [
            DiseaseEntry(
                id=disease_id,
                name=name,
                description=description or None,
                exact_synonyms=_unique(exact or [], name),
                other_synonyms=_unique(other or [], name, *(exact or [])),
                obsolete_ids=tuple(obsolete or []),
            )
            for disease_id, name, description, exact, other, obsolete in listing
        ]
        self._searchable = (
            self._entries
            if searchable is None
            else [entry for entry in self._entries if entry.id in searchable]
        )
        self._by_id = {entry.id: entry for entry in self._entries}
        self._by_obsolete: dict[str, list[DiseaseEntry]] = {}
        for entry in self._entries:
            for old in entry.obsolete_ids:
                self._by_obsolete.setdefault(old, []).append(entry)

    def __len__(self) -> int:
        return len(self._entries)

    def resolve(self, disease_id: str) -> DiseaseEntry | None:
        """The Disease with this ID, or the one Disease that replaced it (stream A's
        rule: an exact ID or obsolete-term match, and never an ambiguous one)."""
        if disease_id in self._by_id:
            return self._by_id[disease_id]
        replaced = self._by_obsolete.get(disease_id, [])
        return replaced[0] if len(replaced) == 1 else None

    def search(self, query: str, limit: int) -> list[DiseaseSearchResult]:
        """Case-insensitive search of names, synonyms and IDs, best match first.

        Tiers: the ID; the name itself; an exact synonym itself; the name's start; a
        word in the name; an exact synonym's start; the name containing the query;
        any synonym containing it. Within a tier, shorter matched text first, then
        name and ID, so the order is stable.
        """
        needle = " ".join(query.split()).casefold()
        if not needle:
            return []
        scored: list[tuple[tuple[int, int, str, str], DiseaseSearchResult]] = []
        for entry in self._searchable:
            match = _match(entry, needle)
            if match is None:
                continue
            tier, text, synonym = match
            result = DiseaseSearchResult(
                id=entry.id,
                name=entry.name,
                description=entry.description,
                matched_synonym=synonym,
            )
            scored.append(((tier, len(text), entry.name.casefold(), entry.id), result))
        scored.sort(key=lambda row: row[0])
        return [result for _, result in scored[:limit]]


def _unique(values: Sequence[str], *skip: str) -> tuple[str, ...]:
    seen = {value.casefold() for value in skip}
    kept: list[str] = []
    for value in values:
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            kept.append(value)
    return tuple(kept)


def _match(entry: DiseaseEntry, needle: str) -> tuple[int, str, str | None] | None:
    """(tier, matched text, synonym or None) for the best way the entry matches."""
    name = entry.name.casefold()
    if needle == entry.id.casefold():
        return 0, entry.name, None
    if needle == name:
        return 1, entry.name, None
    exact = [(s, s.casefold()) for s in entry.exact_synonyms]
    for synonym, folded in exact:
        if needle == folded:
            return 2, synonym, synonym
    if name.startswith(needle):
        return 3, entry.name, None
    if any(word.startswith(needle) for word in name.split()[1:]):
        return 4, entry.name, None
    starts = [s for s, folded in exact if folded.startswith(needle)]
    if starts:
        best = min(starts, key=len)
        return 5, best, best
    if needle in name:
        return 6, entry.name, None
    contains = [s for s, folded in exact if needle in folded]
    contains += [s for s in entry.other_synonyms if needle in s.casefold()]
    if contains:
        best = min(contains, key=len)
        return 7, best, best
    return None


# ---------------------------------------------------------------------------
# The live source.
# ---------------------------------------------------------------------------


class LiveSource:
    """Implements `ExperimentSource` with stream A's pipeline and a `RankingBackend`."""

    def __init__(
        self,
        data_dir: Path,
        ranking: RankingBackend,
        *,
        dockable: Dockable,
        offline: bool = False,
    ) -> None:
        missing = [
            str(path.relative_to(data_dir))
            for path in (
                data_dir / DISEASE_PARQUET,
                data_dir / "drug_targets.json",
                *(data_dir / "ot" / dataset for dataset in OT_DATASETS),
            )
            if not path.exists()
        ]
        reactome = reactome_release(data_dir)
        if reactome is None:
            missing.append("reactome/<release>/")
        if ranking.method == "network" and not (data_dir / STRING_MAP).is_file():
            missing.append(str(STRING_MAP))
        if missing or reactome is None:
            raise DataNotPrepared(
                f"The live source has no {', '.join(missing)} in {data_dir}. {PREPARE_HINT}"
            )
        self._data_dir = data_dir
        self._ranking = ranking
        self._dockable = dockable
        self._offline = offline
        self._catalogue = DiseaseCatalogue(
            data_dir / DISEASE_PARQUET, data_dir / "ot" / "clinical_indication"
        )
        self._drugs = cast(JSON, json.loads((data_dir / "drug_targets.json").read_text()))
        self._symbols = _gene_symbols(data_dir / "ot" / "target")
        self._pathways = Pathways(*reactome)
        self._string_mappings: list[JSON] = (
            cast(list[JSON], json.loads((data_dir / STRING_MAP).read_text())["mappings"])
            if ranking.method == "network"
            else []
        )
        # Stream A queries Parquet on DuckDB's shared default connection, which is not
        # thread-safe, so the stages of concurrent builds take turns.
        self._lock = threading.Lock()

    @property
    def data_releases(self) -> list[DataRelease]:
        return [OT_RELEASE, CHEMBL_RELEASE, *self._ranking.releases, self._pathways.release]

    def search_diseases(self, query: str, limit: int) -> list[DiseaseSearchResult]:
        return self._catalogue.search(query, limit)

    def common_diseases(self) -> list[DiseaseRef]:
        entries = (self._catalogue.resolve(disease_id) for disease_id in COMMON_DISEASES)
        return [DiseaseRef(id=entry.id, name=entry.name) for entry in entries if entry]

    def plan(self, disease_id: str) -> ExperimentPlan | None:
        entry = self._catalogue.resolve(disease_id)
        if entry is None:
            return None
        return ExperimentPlan(
            disease=DiseaseRef(id=entry.id, name=entry.name),
            data_releases=self.data_releases,
            ranking_method=self._ranking.method,
            ranking_settings=self._ranking.settings(),
            jury_config=None,
            fixture_note=None,
        )

    def build(self, disease_id: str, experiment_id: UUID) -> BuildSteps:
        entry = self._catalogue.resolve(disease_id)
        if entry is None:
            raise SourceError(f"Open Targets 26.09 has no Disease {disease_id}.")
        disease = DiseaseRef(id=entry.id, name=entry.name)
        sources = EvidenceSources(self._data_dir, offline=self._offline)
        top_n = self._ranking.settings().top_targets

        yield "targets"
        with self._lock, _upstream_errors():
            disease_targets, scores = sources.disease_targets(entry.id, top_n)
            full_names = sources.target_names(t["target_id"] for t in disease_targets["targets"])

        yield "ranking"
        with self._lock, _upstream_errors():
            request = RankingInput(
                disease_id=entry.id,
                target_ids=[t["target_id"] for t in disease_targets["targets"]],
                scores=scores,
                drugs=self._drugs["drugs"],
                symbols=self._symbols,
                release=disease_targets["release"],
                rule=disease_targets["rule"],
            )
            ranking = self._shortlist(sources, request)
        targets = [
            DiseaseTarget(
                rank=row["rank"],
                target_id=row["target_id"],
                symbol=row["name"],
                name=full_names.get(row["target_id"]) or row["name"],
                evidence_only_score=min(1.0, max(0.0, row["evidence_only_score"])),
                retained=row["target_id"] not in ranking.excluded_targets,
                excluded_reason=ranking.excluded_targets.get(row["target_id"]),
            )
            for row in disease_targets["targets"]
        ]
        yield EarlyResult(targets=targets, network=ranking.network)

        yield "evidence"
        with self._lock, _upstream_errors():
            ids = [ranked.candidate_id for ranked in ranking.shortlist]
            routes = (
                None
                if ranking.graph is None
                else NetworkPaths(
                    paths={r.candidate_id: r.routes for r in ranking.shortlist},
                    graph=ranking.graph,
                    symbols=self._symbols,
                    string_mappings=self._string_mappings,
                    disease_target_ids=ranking.retained_target_ids,
                )
            )
            updates, packet = sources.evidence_packet(
                {"id": entry.id, "name": entry.name},
                ids,
                disease_targets,
                self._drugs,
                experiment_id=str(experiment_id),
                releases=list(dict.fromkeys([*self._drugs["releases"], *self._ranking.releases])),
                pathways=self._pathways,
                network_paths=routes,
            )
            candidates = self._candidates(sources, disease, disease_targets, ranking, updates)
            self._archive(
                experiment_id,
                ranking,
                disease_targets=disease_targets,
                evidence_packet=packet,
                coverage={
                    **sources.coverage,
                    "network_paths": None if routes is None else routes.coverage,
                },
                consistency=sources.bioactivity_consistency(self._drugs, updates),
            )
        return BuildResult(targets=targets, network=ranking.network, candidates=candidates)

    # Ranking ----------------------------------------------------------------

    def _shortlist(self, sources: EvidenceSources, request: RankingInput) -> Ranking:
        """The backend's shortlist with ineligible drugs replaced, as stream A does it."""
        by_drug = {drug["drug_id"]: drug for drug in request.drugs}
        excluded: set[str] = set()
        while True:
            ranking = self._ranking.rank(request, frozenset(excluded))
            ids = [ranked.candidate_id for ranked in ranking.shortlist]
            # Everything the checks below and the evidence step ask ChEMBL about these
            # drugs, fetched in parallel first: a first build no longer waits on each in turn.
            sources.prefetch(ids, by_drug)
            conflicts = {i for i in ids if not sources.is_parent(i)}
            for candidate_id in sorted(conflicts):
                sources.reject("chembl", candidate_id, "upstream_parent_contract_conflict")
            unapproved = {
                i
                for i in ids
                if i not in conflicts and not sources.approval(by_drug[i]["source_chembl_ids"])
            }
            for candidate_id in sorted(unapproved):
                sources.reject("open_targets", candidate_id, "regulator_approval_not_confirmed")
            if not conflicts and not unapproved:
                break
            excluded |= conflicts | unapproved
        if not ranking.shortlist:
            raise SourceError(
                "No approved drug acts on a protein with direct evidence for this Disease, so "
                "there is nothing to shortlist."
            )
        return ranking

    # Candidates -------------------------------------------------------------

    def _candidates(
        self,
        sources: EvidenceSources,
        disease: DiseaseRef,
        disease_targets: JSON,
        ranking: Ranking,
        updates: list[JSON],
    ) -> list[Candidate]:
        by_update = {update["candidate_id"]: update for update in updates}
        by_drug = {drug["drug_id"]: drug for drug in self._drugs["drugs"]}
        symbols = {t["target_id"]: t["name"] for t in disease_targets["targets"]}
        summaries = _Summaries(sources, disease.name, symbols, self._symbols, self._pathways)
        candidates: list[Candidate] = []
        for position, ranked in enumerate(ranking.shortlist, 1):
            update = by_update[ranked.candidate_id]
            if not any(item["kind"] == "approval" for item in update["evidence"]):
                raise SourceError(
                    f"Open Targets could not confirm a regulator approval for {update['name']}."
                )
            targets = [CandidateTarget.model_validate(t) for t in update["targets"]]
            target_ids = [t.id for t in targets]
            name = cast(str, update["name"])
            detail = (
                None
                if ranked.unscorable_reason is None
                else plain.unscorable(ranked.unscorable_reason, _display(name), disease.name)
            )
            candidates.append(
                Candidate(
                    candidate_id=ranked.candidate_id,
                    name=name,
                    status=ranked.status,
                    shortlist_rank=position,
                    selected_by=ranked.selected_by,
                    selection_reasons=ranked.selection_reasons,
                    network=ranked.network,
                    unscorable_reason=ranked.unscorable_reason,
                    unscorable_detail=detail,
                    direct_evidence_rank=ranked.direct_evidence_rank,
                    shared_target_count=sum(1 for t in target_ids if t in symbols),
                    targets=targets,
                    evidence=[summaries.item(item, update) for item in update["evidence"]],
                    warnings=[Warning.model_validate(w) for w in update["warnings"]],
                    safety_status=update["safety_status"],
                    dockable=self._dockable(ranked.candidate_id, target_ids),
                    pubchem_cid=update["pubchem_cid"],
                    known_answer=disease.id
                    in by_drug[ranked.candidate_id]["approval"]["disease_ids"],
                )
            )
        return candidates

    def _archive(self, experiment_id: UUID, ranking: Ranking, **files: object) -> None:
        """Keep the build's inputs and checks for audits, as stream A's runs do."""
        folder = self._data_dir / "experiments" / str(experiment_id)
        for name, value in files.items():
            write_json(folder / f"{name}.json", value)
        full = (
            None
            if ranking.full is None
            else archive_full(folder / "network_ranking.json.gz", ranking.full)
        )
        write_json(
            folder / "ranking.json",
            {
                "method": self._ranking.method,
                "settings": self._ranking.settings().model_dump(mode="json"),
                "eligible": ranking.eligible,
                "full_ranking": full,
                "shortlist": [
                    {
                        "candidate_id": r.candidate_id,
                        "direct_evidence_rank": r.direct_evidence_rank,
                        "selected_by": r.selected_by,
                        "selection_reasons": r.selection_reasons,
                        "status": r.status,
                        "unscorable_reason": r.unscorable_reason,
                    }
                    for r in ranking.shortlist
                ],
            },
        )


def _display(name: str) -> str:
    """A ChEMBL name (BARICITINIB) in sentence case, as the web app shows it."""
    return name.capitalize() if name.isupper() else name


def _gene_symbols(target_dir: Path) -> dict[str, str]:
    """Every Open Targets Target's approved symbol, by Ensembl gene ID."""
    with duckdb.connect() as connection:
        rows = connection.execute(
            "select id, approvedSymbol from read_parquet(?) where approvedSymbol is not null",
            [str(target_dir / "*.parquet")],
        ).fetchall()
    return {cast(str, gene): cast(str, symbol) for gene, symbol in rows}


class _Summaries:
    """Plain summaries of stream A's evidence items, from the structured records."""

    def __init__(
        self,
        sources: EvidenceSources,
        disease: str,
        symbols: dict[str, str],
        all_symbols: dict[str, str],
        pathways: Pathways,
    ) -> None:
        self._sources = sources
        self._disease = disease
        self._symbols = symbols
        """The Disease Targets' symbols, by Ensembl ID."""
        self._all_symbols = all_symbols
        self._pathways = pathways
        self._mechanisms: dict[str, dict[int, JSON]] = {}

    def item(self, item: JSON, update: JSON) -> EvidenceItem:
        return EvidenceItem.model_validate({**item, "summary": self.summary(item, update)})

    def summary(self, item: JSON, update: JSON) -> str:
        kind, source_id, values = item["kind"], cast(str, item["source_id"]), item["values"]
        names = {t["id"]: cast(str, t["name"]) for t in update["targets"]}
        if kind == "target_association":
            gene = source_id.split("/")[0]
            return plain.target_association(
                self._symbols[gene], self._disease, values["evidence_only_score"]
            )
        if kind == "mechanism":
            record = self._mechanism(update["candidate_id"], int(source_id))
            target = record.get("target_chembl_id")
            genes = self._sources.map_target(target) if target else set[str]()
            acted_on = [name for gene, name in names.items() if gene in genes]
            if not acted_on:
                raise ValueError(f"mechanism {source_id} names none of the drug's Targets")
            return plain.mechanism(plain.join(acted_on), record.get("action_type"))
        if kind == "bioactivity":
            _, target = source_id.split("/")
            genes = self._sources.map_target(target, single=True)
            if len(genes) != 1 or next(iter(genes)) not in names:
                raise ValueError(f"bioactivity {source_id} does not map to one of the Targets")
            return plain.bioactivity(
                names[next(iter(genes))], values["median_pchembl"], int(values["n_activities"])
            )
        if kind == "approval":
            regulator = self._sources.report_source(source_id)
            if regulator is None:
                raise ValueError(f"approval report {source_id} is not in Open Targets")
            return plain.approval(regulator)
        if kind == "warning":
            warning = next(w for w in update["warnings"] if w["evidence_id"] == item["id"])
            return plain.warning_summary(warning["toxicity_class"])
        if kind == "network_path":
            route = source_id.split("@")[0].split(">")
            if len(route) != int(values["hops"]) + 1 or route[0] not in names:
                raise ValueError(f"network path {source_id} does not start at a drug Target")
            return plain.network_path([self._all_symbols[gene] for gene in route])
        if kind == "pathway":
            genes = self._pathways.genes(source_id)
            if genes.isdisjoint(names):
                raise ValueError(f"pathway {source_id} has none of the drug's Targets")
            return plain.pathway(
                [symbol for gene, symbol in self._symbols.items() if gene in genes],
                self._pathways.name(source_id),
            )
        raise ValueError(f"unknown evidence kind {kind}")

    def _mechanism(self, candidate_id: str, mec_id: int) -> JSON:
        if candidate_id not in self._mechanisms:
            self._mechanisms[candidate_id] = {
                record["mec_id"]: record for record in self._sources.mechanisms(candidate_id)
            }
        return self._mechanisms[candidate_id][mec_id]


@contextmanager
def _upstream_errors() -> Generator[None]:
    """Turn a source database failure into a SourceError the user can read."""
    try:
        yield
    except (httpx.HTTPError, OpenTargetsError) as exc:
        raise SourceError(
            "A source database (Open Targets, ChEMBL or PubChem) did not give a usable answer "
            f"({type(exc).__name__}). Try again in a minute."
        ) from exc
    except FileNotFoundError as exc:
        raise SourceError(f"Some source data is missing: {exc}. {PREPARE_HINT}") from exc
