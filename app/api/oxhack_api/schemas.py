"""The API contract: every request and response body, as Pydantic v2 models.

This module is the single source of truth for the shapes the API sends and
accepts. `python -m oxhack_api.export_openapi` turns it into `api/openapi.json`,
which the web app turns into TypeScript types.

IDs follow plan.md section 3: one ID per kind of thing. Names and symbols are
display text only and never join anything. Coded values are `Literal` types so
a new code is a deliberate contract change.

The shapes map onto the Postgres tables in `db/migrations/` (0001 and 0002):
`Experiment` onto `experiments` and `experiment_targets`, `Candidate` onto
`candidates` (the full object is the `payload` column), `JuryRun` onto
`jury_runs`, `jurors` and `jury_votes`, `DockJob` onto `dock_jobs`, and
`EvaluationResult` onto `evaluation_results`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypeAliasType

# ---------------------------------------------------------------------------
# Identifier formats (plan.md section 3).
# ---------------------------------------------------------------------------

DiseaseId = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z]+_[A-Za-z0-9]+$",
        description="Open Targets disease ID, with an underscore, e.g. MONDO_0100096.",
        examples=["MONDO_0100096"],
    ),
]
TargetId = Annotated[
    str,
    Field(
        pattern=r"^ENSG[0-9]{11}$",
        description="Ensembl gene ID of a human protein, e.g. ENSG00000162434 (JAK1).",
        examples=["ENSG00000162434"],
    ),
]
CandidateId = Annotated[
    str,
    Field(
        pattern=r"^CHEMBL[0-9]+$",
        description="ChEMBL parent molecule ID of a drug, e.g. CHEMBL2105759 (baricitinib).",
        examples=["CHEMBL2105759"],
    ),
]
EvidenceId = Annotated[
    str,
    Field(
        pattern=r"^E[0-9]+$",
        description="Evidence item ID, unique within one Experiment, e.g. E12.",
        examples=["E12"],
    ),
]
StructureId = Annotated[
    str,
    Field(
        pattern=r"^[0-9][A-Z0-9]{3}_[A-Za-z0-9]+$",
        description="Protein structure ID: PDB ID and chain, e.g. 6WTO_A.",
        examples=["6WTO_A"],
    ),
]
PdbId = Annotated[
    str,
    Field(pattern=r"^[0-9][A-Z0-9]{3}$", description="RCSB PDB entry ID.", examples=["6WTO"]),
]
DataRelease = Annotated[
    str,
    Field(
        pattern=r"^[a-z]+-[0-9][0-9.]*$",
        description="A pinned source release, written source-version, e.g. opentargets-26.09.",
        examples=["opentargets-26.09"],
    ),
]
ModelId = Annotated[
    str,
    Field(
        min_length=1,
        description="Pinned model ID as the jury provider names it, e.g. claude-sonnet-5.",
        examples=["claude-sonnet-5"],
    ),
]

# ---------------------------------------------------------------------------
# Coded values. Each is a named alias, so OpenAPI lists it as its own schema and
# the web app can key its wording on it (e.g. Record<UnscorableReason, string>).
# ---------------------------------------------------------------------------

ExperimentStatus = TypeAliasType(
    "ExperimentStatus", Literal["queued", "building", "ready", "failed"]
)
BuildStage = TypeAliasType("BuildStage", Literal["targets", "ranking", "evidence", "saving"])
RankingMethod = TypeAliasType("RankingMethod", Literal["network", "evidence_only"])
ShortlistMethod = TypeAliasType("ShortlistMethod", Literal["physical_rwr", "zscore"])
JuryMode = TypeAliasType("JuryMode", Literal["fixture", "mock", "cortex"])
CandidateStatus = TypeAliasType(
    "CandidateStatus", Literal["scored", "distance_only", "not_scorable"]
)
SelectedBy = TypeAliasType("SelectedBy", Literal["network", "evidence"])
SelectionReason = TypeAliasType(
    "SelectionReason",
    Literal[
        "initial_network_quota",
        "initial_evidence_quota",
        "evidence_fill_after_deduplication",
        "network_fill_after_deduplication",
        "evidence_ranking_network_unavailable",
    ],
)
UnscorableReason = TypeAliasType(
    "UnscorableReason",
    Literal["no_retained_disease_targets", "no_retained_drug_targets", "network_unavailable"],
)
NetworkWarning = TypeAliasType(
    "NetworkWarning", Literal["zero_null_variance", "insufficient_degree_matched_pool"]
)
TargetExcludedReason = TypeAliasType(
    "TargetExcludedReason", Literal["not_in_graph", "outside_largest_component"]
)
NetworkRole = TypeAliasType("NetworkRole", Literal["disease", "drug", "both", "link"])
SafetyStatus = TypeAliasType("SafetyStatus", Literal["warnings_recorded", "unknown"])
EvidenceKind = TypeAliasType(
    "EvidenceKind",
    Literal[
        "target_association",
        "mechanism",
        "bioactivity",
        "approval",
        "warning",
        "network_path",
        "pathway",
    ],
)
EvidenceSource = TypeAliasType(
    "EvidenceSource", Literal["open_targets", "chembl", "string", "reactome"]
)
JuryStatus = TypeAliasType("JuryStatus", Literal["queued", "running", "done", "failed"])
JurorStatus = TypeAliasType(
    "JurorStatus", Literal["pending", "running", "valid", "invalid", "failed"]
)
Decision = TypeAliasType("Decision", Literal["investigate", "watch", "deprioritise"])
Direction = TypeAliasType("Direction", Literal["supported", "contradicted", "unknown"])
DockKind = TypeAliasType("DockKind", Literal["candidate", "redock_control", "negative_control"])
DockStatus = TypeAliasType("DockStatus", Literal["queued", "running", "done", "failed"])
ControlStatus = TypeAliasType("ControlStatus", Literal["not_measured", "passed", "failed"])
DockFileName = TypeAliasType(
    "DockFileName",
    Literal["receptor.pdb", "poses.sdf", "crystal_ligand.sdf", "scores.json", "log.txt"],
)
EvaluationKind = TypeAliasType("EvaluationKind", Literal["retrieval", "reranking"])
EvaluationScope = TypeAliasType("EvaluationScope", Literal["full_eligible", "common_scorable"])
EvaluationCaseStatus = TypeAliasType(
    "EvaluationCaseStatus",
    Literal[
        "evaluated",
        "missing_labels",
        "no_positive_references",
        "no_positive_in_scope",
        "empty_universe",
    ],
)

SHORTLIST_MAX = 15
"""The Candidate list is the shortlist only: never more than this many."""

REDOCK_SUCCESS_ANGSTROM = 2.0
"""A redock RMSD at or below this many angstroms reproduces the crystal pose."""


class Model(BaseModel):
    """Base for every contract model: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Health.
# ---------------------------------------------------------------------------


class Health(Model):
    status: Literal["ok"] = Field(description="Always ok when the API answers.")
    source: Literal["fixture", "live"] = Field(
        description="Where Experiment data comes from: saved fixtures or the live pipeline."
    )
    version: str = Field(description="Version of the oxhack-api package.")


class ErrorResponse(Model):
    detail: str = Field(description="What went wrong, in plain words.")


class ValidationIssue(BaseModel):
    """One problem with the request, as FastAPI reports it."""

    model_config = ConfigDict(extra="allow")

    loc: list[str | int] = Field(description="Where the problem is, e.g. [body, disease_id].")
    msg: str = Field(description="What is wrong.")
    type: str = Field(description="Machine-readable kind of problem.")


class UnprocessableResponse(Model):
    detail: str | list[ValidationIssue] = Field(
        description=(
            "Either one plain-words reason the request cannot be done, or the list of "
            "fields that failed validation."
        )
    )


# ---------------------------------------------------------------------------
# Diseases.
# ---------------------------------------------------------------------------


class DiseaseRef(Model):
    id: DiseaseId
    name: str = Field(description="Disease name as Open Targets gives it, e.g. COVID-19.")


class DiseaseSearchResult(Model):
    id: DiseaseId
    name: str = Field(description="Disease name as Open Targets gives it.")
    description: str | None = Field(
        description="One-sentence definition from Open Targets, or null if it has none."
    )
    matched_synonym: str | None = Field(
        description="The synonym that matched the query when the name itself did not, else null."
    )


class DiseaseSearchResponse(Model):
    query: str = Field(description="The search text, as received.")
    results: list[DiseaseSearchResult] = Field(
        description="Diseases this API can build an Experiment for, best match first."
    )


class CommonDiseases(Model):
    """Well-known Diseases to offer before anything is searched for."""

    items: list[DiseaseRef] = Field(
        description=(
            "Diseases this API is known to build a full network shortlist for, the one to "
            "show first leading."
        )
    )


# ---------------------------------------------------------------------------
# Settings fixed per Experiment.
# ---------------------------------------------------------------------------


class RankingSettings(Model):
    """Settings for the ranking (stream B `RankingSettings`). The network-only settings are
    null when `Experiment.ranking_method` is evidence_only: no network ranking ran."""

    top_targets: int = Field(
        ge=1, description="How many Disease Targets to use, strongest evidence first."
    )
    randomisations: int | None = Field(
        ge=2,
        description=(
            "How many random protein sets the closeness comparison draws; null when no network "
            "ranking ran."
        ),
    )
    seed: int | None = Field(
        ge=0,
        description=(
            "Random seed, so the same inputs give the same ranking; null when no network "
            "ranking ran."
        ),
    )
    min_bin_size: int | None = Field(
        ge=1,
        description=(
            "Fewest proteins in each degree group used to draw random sets; null when no "
            "network ranking ran."
        ),
    )
    shortlist_method: ShortlistMethod | None = Field(
        description=(
            "Which network ranking fills the network places: physical_rwr (a random walk from "
            "the Disease Targets, stream B's application default) or zscore (closeness compared "
            "with random protein sets). Null when no network ranking ran."
        )
    )
    restart_probability: float | None = Field(
        gt=0,
        le=1,
        description=(
            "Chance the random walk jumps back to the Disease Targets at each step; null unless "
            "shortlist_method is physical_rwr."
        ),
    )
    network_slots: int = Field(
        ge=0, description="Shortlist places filled first from the network ranking."
    )
    evidence_slots: int = Field(
        ge=0, description="Shortlist places filled first from the direct-evidence ranking."
    )

    @model_validator(mode="after")
    def _method_settings(self) -> RankingSettings:
        if (self.shortlist_method is None) != (self.randomisations is None):
            raise ValueError("shortlist_method is set exactly when a network ranking ran")
        if (self.shortlist_method == "physical_rwr") != (self.restart_probability is not None):
            raise ValueError("restart_probability is set exactly for physical_rwr")
        return self


class JuryModel(Model):
    id: ModelId
    display_name: str = Field(description="Name to show for this model, e.g. Claude Sonnet 5.")
    family: str = Field(description="Company or model family, e.g. Anthropic.")


class JuryConfig(Model):
    """The fixed Model jury configuration of one Experiment."""

    mode: JuryMode = Field(
        description=(
            "fixture: a recorded review with made-up votes. mock: a practice review; no model "
            "is called and every vote is a placeholder with no scientific meaning. cortex: "
            "real models through Snowflake Cortex."
        )
    )
    models: list[JuryModel] = Field(
        min_length=1, description="The jurors, each a different model family."
    )
    prompt_version: str = Field(description="Version of the review prompt, e.g. jury-v3.")
    temperature: float = Field(ge=0, description="Sampling temperature sent to the models.")
    max_attempts: int = Field(
        ge=1, description="Tries per juror before its review counts as invalid."
    )
    shuffle_seed: int = Field(description="Seed for the order each juror sees the Candidates in.")
    reasoning_effort: dict[str, str] = Field(
        default_factory=dict[str, str],
        description=(
            "Reasoning effort sent to each model that takes one, by model ID, e.g. "
            "{'gpt-5.4': 'low'}. Models without an entry use their default."
        ),
    )


# ---------------------------------------------------------------------------
# Targets and the protein network.
# ---------------------------------------------------------------------------


class DiseaseTarget(Model):
    """One selected Disease Target (row of `experiment_targets`)."""

    rank: int = Field(ge=1, description="Position by evidence-only score, 1 is strongest.")
    target_id: TargetId
    symbol: str = Field(description="Gene symbol to show, e.g. TYK2.")
    name: str = Field(description="Full protein name, e.g. tyrosine kinase 2.")
    evidence_only_score: float = Field(
        ge=0,
        le=1,
        description=(
            "Open Targets association score without trial and drug-biomarker evidence. "
            "Strength of the link, not a chance of treatment success."
        ),
    )
    retained: bool = Field(
        description=(
            "True when the Target maps into the protein network. With no network ranking "
            "(ranking_method evidence_only) every Target is kept."
        )
    )
    excluded_reason: TargetExcludedReason | None = Field(
        description="Why the Target was left out of the network; null when retained."
    )

    @model_validator(mode="after")
    def _reason_iff_excluded(self) -> DiseaseTarget:
        if self.retained != (self.excluded_reason is None):
            raise ValueError("excluded_reason must be set exactly when retained is false")
        return self


class NetworkNode(Model):
    id: TargetId
    symbol: str = Field(description="Gene symbol to label the node with.")
    role: NetworkRole = Field(
        description=(
            "disease: a Disease Target. drug: a Candidate's Target. both: a Disease Target "
            "that a Candidate also acts on. link: a protein on a route between them."
        )
    )


class NetworkEdge(Model):
    source: TargetId = Field(description="Protein ID at one end; edges have no direction.")
    target: TargetId = Field(description="Protein ID at the other end.")


class NetworkGraph(Model):
    """The small subgraph the UI draws: routes from Candidate Targets to Disease Targets."""

    graph_version: DataRelease = Field(description="The protein network release, e.g. string-12.5.")
    nodes: list[NetworkNode] = Field(description="Proteins in the subgraph.")
    edges: list[NetworkEdge] = Field(
        description="High-confidence interactions between those proteins."
    )

    @model_validator(mode="after")
    def _edges_join_known_nodes(self) -> NetworkGraph:
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("network node IDs must be unique")
        known = set(ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge {edge.source}-{edge.target} joins an unknown node")
            if edge.source == edge.target:
                raise ValueError("network edges may not be self-loops")
        return self


# ---------------------------------------------------------------------------
# Evidence (stream A shape).
# ---------------------------------------------------------------------------


class EvidenceItem(Model):
    """One sourced fact. The same item keeps one ID across all Candidates of an Experiment."""

    id: EvidenceId
    kind: EvidenceKind = Field(description="What the item records.")
    source: EvidenceSource = Field(description="Database the fact comes from.")
    source_id: str = Field(
        description=(
            "The record's own ID in that database. For a network_path, the route's protein IDs "
            "joined by '>', then '@' and the SHA-256 of the network it was found in."
        )
    )
    url: str = Field(description="Link to the original record.")
    release: DataRelease = Field(description="Data release the record was read from.")
    statement: str = Field(
        description="The fact as the source records it, naming the source. For audits and the jury."
    )
    summary: str = Field(
        description="The same fact in plain words for students, e.g. 'Blocks JAK1.'"
    )
    values: dict[str, float] = Field(
        description="Numbers quoted in the statement, by name; empty when it quotes none."
    )


class Warning(Model):
    """A documented safety warning. Missing warnings never mean a drug is safe."""

    evidence_id: EvidenceId = Field(description="The warning evidence item this summarises.")
    type: str = Field(description="Kind of warning as the source names it, e.g. Black Box Warning.")
    toxicity_class: str | None = Field(
        description="Area of harm, e.g. infectious disease; null if the source gives none."
    )
    description: str | None = Field(
        description="The source's own wording; null if the source gives none."
    )


# ---------------------------------------------------------------------------
# Candidates.
# ---------------------------------------------------------------------------


class CandidateTarget(Model):
    id: TargetId
    name: str = Field(description="Gene symbol of the Target, e.g. JAK1 (stream A's field name).")
    mechanism: str | None = Field(
        description=(
            "Action type from the mechanism record, e.g. INHIBITOR; null when the link comes "
            "from bioactivity measurements only."
        )
    )


class CandidateRwr(Model):
    """Random walk with restart result for one Candidate (stream B's physical RWR)."""

    rank: int = Field(
        ge=1,
        description="Position in the random-walk ranking of all eligible drugs; 1 is the most.",
    )
    mass: float = Field(
        ge=0,
        description=(
            "Average share of the walk's time spent on the drug's Targets once it settles. "
            "Higher is more connected to the Disease; it is not a probability of success."
        ),
    )


class CandidateNetwork(Model):
    """Network-proximity result for one Candidate. Null on the Candidate when not scorable."""

    rank: int = Field(
        ge=1,
        description=(
            "Position in the closeness (z-score) ranking of all eligible drugs. distance_only "
            "Candidates come after every scored one."
        ),
    )
    rwr: CandidateRwr | None = Field(
        description=(
            "The random-walk result; null when the Experiment's shortlist_method is zscore "
            "(saved before the random walk ran)."
        )
    )
    mean_distance: float = Field(
        ge=0,
        description=(
            "Average number of network steps from the drug's Targets to the nearest Disease "
            "Target. Lower is closer; it is not a measure of efficacy."
        ),
    )
    degree_matched_z: float | None = Field(
        description=(
            "Closeness compared with random protein sets of matching connectivity; more "
            "negative is closer than expected. Null for distance_only."
        )
    )
    graph_version: DataRelease = Field(description="The protein network release used.")
    warning: NetworkWarning | None = Field(
        description="Why the comparison with random sets is unavailable; null when scored."
    )
    path: list[TargetId] = Field(
        min_length=1,
        description=(
            "One shortest route, as protein IDs in order, from the drug's closest Target to a "
            "Disease Target. A single ID means the Target is itself a Disease Target."
        ),
    )

    @model_validator(mode="after")
    def _z_xor_warning(self) -> CandidateNetwork:
        if (self.degree_matched_z is None) == (self.warning is None):
            raise ValueError("network has either a degree_matched_z or a warning, not both")
        return self


class Candidate(Model):
    """One shortlisted drug (plan.md section 9.2, plus shortlist and display fields)."""

    candidate_id: CandidateId
    name: str = Field(description="Drug name as ChEMBL gives it, e.g. BARICITINIB.")
    status: CandidateStatus = Field(
        description=(
            "scored: has a closeness z-score. distance_only: has a network distance but no "
            "z-score. not_scorable: cannot be placed in the network, including when no network "
            "ranking ran (unscorable_reason network_unavailable)."
        )
    )
    shortlist_rank: int = Field(
        ge=1, le=SHORTLIST_MAX, description="Order in which the Candidate joined the shortlist."
    )
    selected_by: list[SelectedBy] = Field(
        min_length=1, description="Which rankings put the Candidate on the shortlist."
    )
    selection_reasons: list[SelectionReason] = Field(
        min_length=1, description="The shortlist rule behind each selection, in order."
    )
    network: CandidateNetwork | None = Field(
        description="Network-proximity result; null exactly when status is not_scorable."
    )
    unscorable_reason: UnscorableReason | None = Field(
        description="Why the Candidate cannot be placed in the network; null unless not_scorable."
    )
    unscorable_detail: str | None = Field(
        description="The same reason in plain words for this drug; null unless not_scorable."
    )
    direct_evidence_rank: int | None = Field(
        ge=1,
        description=(
            "Position when drugs are ranked only by direct links between their Targets and the "
            "Disease; null when no Disease evidence was available."
        ),
    )
    shared_target_count: int = Field(
        ge=0, description="How many of the drug's Targets are themselves Disease Targets."
    )
    targets: list[CandidateTarget] = Field(
        description="Human proteins the drug acts on; empty when it has none."
    )
    evidence: list[EvidenceItem] = Field(description="Sourced facts about this Candidate.")
    warnings: list[Warning] = Field(description="Documented safety warnings.")
    safety_status: SafetyStatus = Field(
        description="warnings_recorded when any warning exists; otherwise unknown, never safe."
    )
    dockable: bool = Field(
        description="True when a binding pose can be computed for it on a prepared structure."
    )
    pubchem_cid: int | None = Field(
        ge=1, description="PubChem compound ID for the 2D drawing; null for antibodies."
    )
    known_answer: bool = Field(
        description=(
            "True when this Candidate is the Experiment's known-answer check: a drug-Disease "
            "relationship already in the evidence. It checks the pipeline, not a discovery."
        )
    )

    @model_validator(mode="after")
    def _status_invariants(self) -> Candidate:
        if self.status == "not_scorable":
            if self.network is not None:
                raise ValueError("a not_scorable Candidate has network = null")
            if self.unscorable_reason is None or not self.unscorable_detail:
                raise ValueError("a not_scorable Candidate needs unscorable_reason and detail")
        else:
            if self.network is None:
                raise ValueError(f"a {self.status} Candidate needs a network result")
            if self.unscorable_reason is not None or self.unscorable_detail is not None:
                raise ValueError(f"a {self.status} Candidate has no unscorable_reason")
            if self.status == "scored" and self.network.degree_matched_z is None:
                raise ValueError("a scored Candidate needs degree_matched_z")
            if self.status == "distance_only" and self.network.degree_matched_z is not None:
                raise ValueError("a distance_only Candidate has degree_matched_z = null")
        if len(set(self.selected_by)) != len(self.selected_by):
            raise ValueError("selected_by may not repeat a value")
        fallback = self.unscorable_reason == "network_unavailable"
        if fallback != ("evidence_ranking_network_unavailable" in self.selection_reasons):
            raise ValueError(
                "network_unavailable goes with the evidence_ranking_network_unavailable selection"
            )
        if fallback and (
            self.selected_by != ["evidence"]
            or self.selection_reasons != ["evidence_ranking_network_unavailable"]
        ):
            raise ValueError("with no network ranking a Candidate is selected by evidence only")
        evidence_ids = [item.id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence IDs must be unique within a Candidate")
        warning_items = {item.id for item in self.evidence if item.kind == "warning"}
        for warning in self.warnings:
            if warning.evidence_id not in warning_items:
                raise ValueError(f"warning {warning.evidence_id} has no warning evidence item")
        if (self.safety_status == "warnings_recorded") != bool(self.warnings):
            raise ValueError("safety_status is warnings_recorded exactly when warnings exist")
        return self


# ---------------------------------------------------------------------------
# Model jury.
# ---------------------------------------------------------------------------


class TokenUsage(Model):
    """Tokens one attempt used, as the provider reported them. Null means not reported."""

    attempt: int = Field(ge=1, description="Which attempt, starting at 1.")
    input_tokens: int | None = Field(ge=0, description="Tokens sent; null if not reported.")
    output_tokens: int | None = Field(ge=0, description="Tokens returned; null if not reported.")


class Juror(Model):
    """Progress and outcome of one model's review."""

    model_id: ModelId
    status: JurorStatus = Field(
        description=(
            "pending: not started. running: reviewing now. valid: review passed every check. "
            "invalid: replied, but no reply passed the checks. failed: never replied."
        )
    )
    attempts: int = Field(ge=0, description="How many times the model has been asked so far.")
    latency_ms: int | None = Field(
        ge=0, description="Time the review took, in milliseconds; null until it finishes."
    )
    errors: list[str] = Field(
        description="Why earlier or failed attempts were rejected, one line each."
    )
    token_usage: list[TokenUsage] = Field(
        default_factory=list[TokenUsage],
        description=(
            "Tokens each attempt used, for cost reporting. A null count means the full cost "
            "is unknown; counts are never estimated."
        ),
    )


class SafetyReview(Model):
    status: SafetyStatus = Field(description="What the juror found on safety.")
    evidence_ids: list[EvidenceId] = Field(description="Warning evidence items the juror cited.")


class JuryVote(Model):
    """One valid juror's review of one Candidate (row of `jury_votes`)."""

    model_id: ModelId
    candidate_id: CandidateId
    rank: int = Field(
        ge=1, description="The juror's position for this Candidate, 1 is most promising."
    )
    decision: Decision = Field(description="What the juror suggests doing with the Candidate.")
    direction: Direction = Field(
        description=(
            "Whether the evidence supports the drug's action helping in this Disease, "
            "contradicts it, or leaves it unknown."
        )
    )
    rationale: str = Field(description="The juror's evidence-based case for the Candidate.")
    objection: str = Field(description="The juror's strongest scientific objection.")
    missing_evidence: list[str] = Field(description="Evidence the juror says is missing.")
    supporting_evidence_ids: list[EvidenceId] = Field(description="Evidence items cited in favour.")
    contradicting_evidence_ids: list[EvidenceId] = Field(
        description="Evidence items cited against."
    )
    safety: SafetyReview


class ConsensusEntry(Model):
    candidate_id: CandidateId
    rank: int = Field(ge=1, description="Consensus position; tied Candidates share a rank.")
    borda_points: int = Field(ge=0, description="Points summed over valid jurors.")


class Consensus(Model):
    method: Literal["borda"] = Field(description="How juror ranks were combined.")
    jurors_counted: int = Field(ge=0, description="Valid jurors whose ranks were combined.")
    ranking: list[ConsensusEntry] = Field(description="Candidates in consensus order.")


class JuryRun(Model):
    """The one Model jury review of an Experiment's shortlist."""

    status: JuryStatus = Field(
        description="queued, running, done, or failed (no review could be produced)."
    )
    models: list[JuryModel] = Field(
        min_length=1, description="The jurors, with names to show; never hard-code them."
    )
    jurors: list[Juror] = Field(description="Per-juror progress, in the order of models.")
    votes: list[JuryVote] = Field(
        description="Reviews from valid jurors; they appear as each juror finishes."
    )
    consensus: Consensus | None = Field(description="Combined ranking; null until done.")
    agreement: float | None = Field(
        ge=0,
        le=1,
        description=(
            "Agreement between jurors (Kendall's W): 0 none, 1 full. Consistency between "
            "models, not a chance of success. Null below two valid jurors."
        ),
    )
    contested: list[CandidateId] = Field(
        description="Candidates on which valid jurors gave different decisions."
    )
    error: str | None = Field(description="Why the run failed; null unless failed.")
    created_at: datetime = Field(description="When the jury was asked.")
    started_at: datetime | None = Field(description="When the first juror started.")
    finished_at: datetime | None = Field(description="When the run ended.")

    @model_validator(mode="after")
    def _status_invariants(self) -> JuryRun:
        if self.status == "failed" and not self.error:
            raise ValueError("a failed jury run needs an error")
        if self.status == "done" and self.consensus is None:
            raise ValueError("a done jury run needs a consensus")
        if [juror.model_id for juror in self.jurors] != [model.id for model in self.models]:
            raise ValueError("jurors must list the models in order")
        return self


# ---------------------------------------------------------------------------
# Docking.
# ---------------------------------------------------------------------------


class Ligand(Model):
    comp_id: str = Field(description="PDB chemical component ID of the co-crystal ligand.")
    name: str = Field(description="Ligand name to show, e.g. baricitinib.")
    candidate_id: CandidateId = Field(
        description=(
            "ChEMBL parent ID of the co-crystal ligand. It equals a Candidate's ID when that "
            "drug is the ligand."
        )
    )


class DockingBox(Model):
    center: tuple[float, float, float] = Field(
        description="Box centre in angstroms: the crystal ligand's heavy-atom centroid."
    )
    size: tuple[float, float, float] = Field(description="Box edge lengths in angstroms.")


class StructureControl(Model):
    """The redocking control: the crystal ligand docked back into its own structure."""

    kind: Literal["redock"] = Field(description="Type of control.")
    rmsd: float | None = Field(
        ge=0,
        description=(
            "Distance between the predicted and crystal pose, in angstroms; null until measured."
        ),
    )
    status: ControlStatus = Field(
        description=(
            f"passed when rmsd is at most {REDOCK_SUCCESS_ANGSTROM} angstroms, failed when "
            "above, not_measured when the control has not run."
        )
    )
    success_threshold: float = Field(description="Largest RMSD, in angstroms, that passes.")
    job_id: UUID | None = Field(description="The docking job that measured it, if any.")
    fixture: bool = Field(
        description="True when the value is made-up fixture data rather than a measurement."
    )

    @model_validator(mode="after")
    def _status_matches_rmsd(self) -> StructureControl:
        if self.rmsd is None:
            if self.status != "not_measured":
                raise ValueError("a control without rmsd is not_measured")
        elif self.status != ("passed" if self.rmsd <= self.success_threshold else "failed"):
            raise ValueError("control status must follow from rmsd and the threshold")
        return self


class Structure(Model):
    """A prepared human protein structure that Candidates can be docked into."""

    id: StructureId
    pdb_id: PdbId
    chain: str = Field(description="The chain kept for docking.")
    target_id: TargetId = Field(description="The protein this chain is. Never shown as another.")
    target_symbol: str = Field(description="Gene symbol of that protein, e.g. JAK2.")
    title: str = Field(description="Entry title from RCSB.")
    method: str = Field(description="Experimental method from RCSB, e.g. X-RAY DIFFRACTION.")
    resolution: float = Field(gt=0, description="Resolution in angstroms; lower is sharper.")
    ligand: Ligand = Field(description="The co-crystal ligand, which sets the docking box.")
    box: DockingBox
    control: StructureControl


class StructureList(Model):
    structures: list[Structure] = Field(description="The prepared docking set.")


class DockRequest(Model):
    experiment_id: UUID = Field(description="The Experiment the Candidate belongs to.")
    candidate_id: CandidateId = Field(description="A Candidate on that Experiment's shortlist.")
    structure_id: StructureId = Field(description="A prepared structure of one of its Targets.")


class DockSettings(Model):
    engine: Literal["vina"] = Field(description="Docking program.")
    engine_version: str = Field(description="Version of the docking program.")
    exhaustiveness: int = Field(ge=1, description="How thoroughly Vina searches.")
    seed: int = Field(description="Random seed for the search.")
    n_poses: int = Field(ge=1, description="How many poses are kept.")
    box: DockingBox
    meeko_version: str | None = Field(description="Meeko version used to prepare inputs.")
    rdkit_version: str | None = Field(description="RDKit version used to prepare the ligand.")


class PoseScore(Model):
    pose: int = Field(ge=1, description="Pose number, 1 is the best-scoring pose.")
    score: float = Field(
        description=(
            "Vina docking score: a rough, unitless estimate of fit. Not a measured binding "
            "affinity, and only loosely comparable between ligands."
        )
    )


class DockFile(Model):
    url: str = Field(
        description=(
            "Where to download the file: /api/files/{job_id}/{name}. A job that reuses another "
            "job's result links to that job's files."
        )
    )
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the file's bytes, in hex."
    )


class DockFiles(Model):
    """A finished job's files. Each field's file name is in `DOCK_FILE_NAMES`."""

    receptor: DockFile = Field(
        description="receptor.pdb: the docked protein chain, protein atoms only, PDB format."
    )
    poses: DockFile = Field(
        description=(
            "poses.sdf: the predicted poses, best first, SDF format. In fixture results pose 1 "
            "is a labelled copy of the crystal ligand, not a docking result."
        )
    )
    crystal_ligand: DockFile = Field(
        description=(
            "crystal_ligand.sdf: the structure's co-crystal ligand where the crystal shows it, "
            "SDF format. Draw it over a pose to compare them (the redocking check)."
        )
    )
    scores: DockFile = Field(description="scores.json: the per-pose scores, JSON.")
    log: DockFile = Field(description="log.txt: what was run and how, plain text.")


DOCK_FILE_NAMES: dict[str, DockFileName] = {
    "receptor": "receptor.pdb",
    "poses": "poses.sdf",
    "crystal_ligand": "crystal_ligand.sdf",
    "scores": "scores.json",
    "log": "log.txt",
}
"""The file name of each `DockFiles` field."""


class DockJob(Model):
    """One binding-pose computation (row of `dock_jobs`)."""

    id: UUID
    kind: DockKind = Field(
        description="candidate: a user request. redock_control and negative_control: checks."
    )
    status: DockStatus = Field(description="queued, running, done, or failed.")
    experiment_id: UUID | None = Field(
        description="The Experiment it belongs to; null for controls."
    )
    candidate_id: CandidateId = Field(description="The drug being docked.")
    target_id: TargetId = Field(description="The protein it is docked into.")
    structure_id: StructureId = Field(description="The prepared structure used.")
    settings: DockSettings
    scores: list[PoseScore] | None = Field(description="Per-pose scores; null until done.")
    files: DockFiles | None = Field(
        description=(
            "Result files; null until done. In fixture mode only the precomputed demo jobs "
            "have files; results made up on request have scores only."
        )
    )
    control_rmsd: float | None = Field(
        ge=0, description="Measured RMSD for a redock control job, in angstroms; else null."
    )
    error: str | None = Field(description="Why the job failed, last lines of the log; else null.")
    cached_from: UUID | None = Field(
        description="Job whose identical result this one reuses instead of running again."
    )
    fixture: bool = Field(description="True when scores are made-up fixture data.")
    created_at: datetime = Field(description="When the job was requested.")
    started_at: datetime | None = Field(description="When it started running.")
    finished_at: datetime | None = Field(description="When it ended.")

    @model_validator(mode="after")
    def _status_invariants(self) -> DockJob:
        if (self.kind == "candidate") != (self.experiment_id is not None):
            raise ValueError("candidate jobs belong to an Experiment; controls do not")
        if self.status == "failed" and not self.error:
            raise ValueError("a failed docking job needs an error")
        if self.status == "done" and self.scores is None:
            raise ValueError("a done docking job has scores")
        if self.files is not None and self.status != "done":
            raise ValueError("only a done docking job has result files")
        return self


# ---------------------------------------------------------------------------
# Experiments.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Molecules: 3D conformers for drawing a Candidate (small molecules only).
# ---------------------------------------------------------------------------


class ConformerAtom(Model):
    element: str = Field(description="Element symbol, e.g. C, N, O.")
    x: float = Field(description="Position in angstroms.")
    y: float
    z: float


class ConformerBond(Model):
    a: int = Field(ge=0, description="Index of the first atom in `atoms`.")
    b: int = Field(ge=0, description="Index of the second atom in `atoms`.")
    order: int = Field(ge=1, le=3, description="1 single, 2 double, 3 triple.")


class Conformer(Model):
    """One computed 3D shape of a small molecule, for display only.

    Antibodies and other biologics have no conformer; the API answers 404 for them.
    """

    pubchem_cid: int = Field(gt=0, description="PubChem compound ID.")
    source_url: str = Field(description="Where the conformer came from (PubChem 3D).")
    atoms: list[ConformerAtom]
    bonds: list[ConformerBond]


class ExperimentCreate(Model):
    disease_id: DiseaseId


class Experiment(Model):
    """One exploration of one Disease, with everything the 8 steps show."""

    id: UUID
    status: ExperimentStatus = Field(
        description="queued, building, ready, or failed. Only ready Experiments have results."
    )
    stage: BuildStage | None = Field(description="Current build stage while building; else null.")
    error: str | None = Field(description="Why the build failed; null unless failed.")
    disease: DiseaseRef
    data_releases: list[DataRelease] = Field(
        min_length=1, description="Pinned source releases every result was computed from."
    )
    ranking_method: RankingMethod = Field(
        description=(
            "network: Candidates ranked by network proximity, with direct evidence alongside. "
            "evidence_only: no network was available, so Candidates are ranked by direct Target "
            "evidence alone (show 'Evidence ranking - network unavailable'); network is null and "
            "every Candidate is not_scorable with unscorable_reason network_unavailable."
        )
    )
    ranking_settings: RankingSettings
    jury_config: JuryConfig = Field(description="The fixed Model jury for this Experiment.")
    targets: list[DiseaseTarget] = Field(description="Selected Disease Targets, strongest first.")
    network: NetworkGraph | None = Field(
        description="Protein subgraph to draw; null until built, and always null for evidence_only."
    )
    candidates: list[Candidate] = Field(
        max_length=SHORTLIST_MAX,
        description="The shortlist only, in shortlist order. The full ranking is never sent.",
    )
    jury: JuryRun | None = Field(description="The Model jury review; null until asked.")
    dock_jobs: list[DockJob] = Field(description="Binding-pose jobs requested, newest first.")
    fixture_note: str | None = Field(
        description="Set when the results are fixture data: says which values are made up."
    )
    created_at: datetime = Field(description="When the Experiment was requested.")
    archived_at: datetime | None = Field(description="When it was archived; null when active.")

    @model_validator(mode="after")
    def _invariants(self) -> Experiment:
        if self.status == "failed" and not self.error:
            raise ValueError("a failed Experiment needs an error")
        if (self.stage is not None) != (self.status == "building"):
            raise ValueError("stage is set exactly while building")
        check_shortlist(self.candidates)
        check_ranking_method(
            self.ranking_method, self.ranking_settings, self.network, self.candidates
        )
        return self


def check_ranking_method(
    method: RankingMethod,
    settings: RankingSettings,
    network: NetworkGraph | None,
    candidates: list[Candidate],
) -> None:
    """Raise ValueError unless the results say what the ranking method says, so an
    evidence-only Experiment never shows anything that looks like a network result."""
    network_settings = (settings.randomisations, settings.seed, settings.min_bin_size)
    fallback = [c.unscorable_reason == "network_unavailable" for c in candidates]
    if method == "evidence_only":
        if network is not None:
            raise ValueError("an evidence_only Experiment has no network")
        if any(value is not None for value in network_settings) or settings.network_slots:
            raise ValueError("an evidence_only Experiment has no network ranking settings")
        if not all(fallback):
            raise ValueError("every evidence_only Candidate is not_scorable: network_unavailable")
    else:
        if any(value is None for value in network_settings):
            raise ValueError("a network Experiment needs its network ranking settings")
        if any(fallback):
            raise ValueError("network_unavailable is only for evidence_only Experiments")
        walked = settings.shortlist_method == "physical_rwr"
        if any((c.network.rwr is not None) != walked for c in candidates if c.network):
            raise ValueError("placed Candidates have a random-walk result exactly for physical_rwr")


def check_shortlist(candidates: list[Candidate]) -> None:
    """Raise ValueError unless the Candidates form one consistent shortlist."""
    if len(candidates) > SHORTLIST_MAX:
        raise ValueError(f"the shortlist holds at most {SHORTLIST_MAX} Candidates")
    ids = [candidate.candidate_id for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("Candidate IDs must be unique")
    if [c.shortlist_rank for c in candidates] != list(range(1, len(ids) + 1)):
        raise ValueError("candidates are listed in shortlist order 1..n")
    # One record keeps one evidence ID across the Experiment.
    seen: dict[str, EvidenceItem] = {}
    for candidate in candidates:
        for item in candidate.evidence:
            if seen.setdefault(item.id, item) != item:
                raise ValueError(f"evidence {item.id} differs between Candidates")


class ExperimentSummary(Model):
    """One row of the history list."""

    id: UUID
    status: ExperimentStatus
    disease: DiseaseRef
    data_releases: list[DataRelease] = Field(description="Pinned source releases.")
    juror_count: int = Field(ge=0, description="How many models are on the jury.")
    jury_status: JuryStatus | None = Field(description="State of the jury; null if never asked.")
    candidate_count: int = Field(ge=0, description="Candidates on the shortlist.")
    docked_count: int = Field(ge=0, description="Finished binding-pose jobs.")
    created_at: datetime
    archived_at: datetime | None = Field(description="When it was archived; null when active.")


class ExperimentList(Model):
    items: list[ExperimentSummary] = Field(description="Experiments, newest first.")


# ---------------------------------------------------------------------------
# Evaluation.
# ---------------------------------------------------------------------------


class ConfidenceInterval(Model):
    low: float = Field(description="Lower bound.")
    high: float = Field(description="Upper bound.")


class EvaluationResult(Model):
    """Frozen metrics for one method in one evaluation scope (row of `evaluation_results`)."""

    manifest_hash: str = Field(description="SHA-256 of the frozen evaluation manifest.")
    experiment: EvaluationKind = Field(
        description="retrieval: finding known drugs. reranking: ordering a fixed panel."
    )
    method: str = Field(description="The ranking method measured, e.g. degree_matched_z.")
    scope: EvaluationScope = Field(
        description=(
            "The drugs ranked. full_eligible: every approved drug; one a method can't score "
            "counts as not found. common_scorable: only drugs every method can score."
        )
    )
    data_releases: list[DataRelease] = Field(min_length=1, description="Pinned source releases.")
    metrics: dict[str, float] = Field(
        description="Metric values by name, e.g. recall_at_10. A metric with no value is absent."
    )
    coverage: dict[str, int] = Field(description="Counts of Diseases and pairs covered, by name.")
    confidence_intervals: dict[str, ConfidenceInterval] | None = Field(
        description="Bootstrap 95% intervals by metric name; null when too few Diseases."
    )
    created_at: datetime = Field(description="When the result was frozen.")


class EvaluationDisease(Model):
    """One Disease the evaluation tested, in one scope."""

    disease_id: DiseaseId
    name: str | None = Field(description="Display name; null when unknown.")
    scope: EvaluationScope
    status: EvaluationCaseStatus = Field(
        description=(
            "evaluated: counted in the averages. Otherwise why it was left out: "
            "missing_labels (no known drugs recorded), no_positive_references (an empty list "
            "recorded), no_positive_in_scope (no known drug among the drugs ranked), "
            "empty_universe (no drugs ranked)."
        )
    )
    candidates: int = Field(ge=0, description="Drugs ranked for this Disease in this scope.")
    known: int | None = Field(
        ge=0, description="Known drugs among them; null when no known drugs are recorded."
    )


class Evaluation(Model):
    results: list[EvaluationResult] = Field(description="Every frozen result.")
    diseases: list[EvaluationDisease] = Field(
        description="Every Disease tested, once per scope, including those left out."
    )
    fixture_note: str | None = Field(
        description="Set when the results are fixture data: says the numbers are made up."
    )
