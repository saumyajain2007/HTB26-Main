"""The API contract: every request and response body, as Pydantic v2 models.

This module is the single source of truth for the shapes the API sends and
accepts. `python -m htb_api.export_openapi` turns it into `api/openapi.json`,
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
    version: str = Field(description="Version of the htb-api package.")


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


# ---------------------------------------------------------------------------
# Antibiotic resistance: the three frozen contracts of docs/contracts.md
# (version 1). These models mirror those JSON shapes field for field, so the
# reference fixtures in tests/fixtures/ parse as-is. The cross-field rules live
# in tests/test_resistance_contracts.py; a contract change goes there, then
# here, then through `python -m htb_api.export_openapi` and `npm run gen:api`.
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "1"
"""Version of the resistance contracts this API speaks (docs/contracts.md)."""

AroId = Annotated[
    str,
    Field(
        pattern=r"^ARO:[0-9]{7}$",
        description="CARD Antibiotic Resistance Ontology term ID, e.g. ARO:3000617 (mecA).",
        examples=["ARO:3000617"],
    ),
]
ProfileId = Annotated[
    UUID, Field(description="ID of a ResistanceProfile.", examples=[UUID(int=0xA1)])
]
InchiKey = Annotated[
    str,
    Field(
        pattern=r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$",
        description="Standard InChIKey of a molecule.",
        examples=["TYZROVQLWOKYKF-ZDUSSCGKSA-N"],
    ),
]
AntibioticId = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$",
        description=(
            "ID of a ranked molecule: a ChEMBL parent molecule ID for an approved drug, "
            "or the generator's own ID for a generated one."
        ),
        examples=["CHEMBL126", "GEN-0001"],
    ),
]
ProfileEvidenceId = Annotated[
    str,
    Field(
        pattern=r"^P[0-9]+$",
        description="Evidence item ID, unique within one ResistanceProfile, e.g. P2.",
        examples=["P2"],
    ),
]
MutationLabel = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        description="A point mutation as CARD writes it: wild-type residue, position, variant.",
        examples=["S84L"],
    ),
]
GeneQuery = Annotated[
    str,
    Field(
        min_length=1,
        max_length=120,
        description=(
            "A resistance determinant as typed: a gene name, a gene name with a mutation, "
            "or an ARO ID."
        ),
        examples=["mecA", "gyrA S84L", "ARO:3000617"],
    ),
]

ProfileInputKind = TypeAliasType(
    "ProfileInputKind", Literal["species_preset", "gene_list", "amrfinderplus"]
)
ConfidenceLevel = TypeAliasType("ConfidenceLevel", Literal["low", "medium", "high"])
EvasionStatus = TypeAliasType(
    "EvasionStatus", Literal["unaffected", "partly_affected", "defeated", "unknown"]
)
CandidateSource = TypeAliasType("CandidateSource", Literal["approved", "generated"])
CertificateStatus = TypeAliasType(
    "CertificateStatus", Literal["not_run", "certified", "failed", "unavailable"]
)
RuleSet = TypeAliasType("RuleSet", Literal["oral_druglike", "antibiotic_relaxed"])
PropertyRule = TypeAliasType(
    "PropertyRule", Literal["mw", "logp", "hbd", "hba", "rot_bonds", "psa"]
)
ViolationRule = TypeAliasType(
    "ViolationRule", Literal["mw", "logp", "hbd", "hba", "rot_bonds", "psa", "alert", "sa"]
)
FeatureName = TypeAliasType("FeatureName", Literal["activity", "target_hit", "docking", "safety"])
RankingFeature = TypeAliasType(
    "RankingFeature", Literal["evasion", "activity", "target_hit", "docking", "safety"]
)
ResistanceEvidenceSource = TypeAliasType("ResistanceEvidenceSource", Literal["card"])
CandidateEvidenceKind = TypeAliasType(
    "CandidateEvidenceKind",
    Literal["activity", "target_hit", "docking", "safety", "smoke_test", "approval"],
)
CandidateEvidenceSource = TypeAliasType(
    "CandidateEvidenceSource", Literal["chembl", "card", "pdb", "htb_verify", "htb_docking"]
)

PROPERTY_RULES: tuple[PropertyRule, ...] = ("mw", "logp", "hbd", "hba", "rot_bonds", "psa")
"""The property rules a Certificate carries, in the order it lists them."""


class Pathogen(Model):
    name: str = Field(description="Species name, e.g. Staphylococcus aureus.")
    ncbi_taxid: int = Field(gt=0, description="NCBI taxonomy ID of the species, e.g. 1280.")


class AroTerm(Model):
    """A CARD term. Join on `aro_id`; `name` is display text only."""

    aro_id: AroId
    name: str = Field(description="The term's name in CARD's vocabulary.")


# ResistanceProfile ---------------------------------------------------------


class ProfileInput(Model):
    """What was asked for, kept exactly as received."""

    kind: ProfileInputKind = Field(description="How the determinants were given.")
    species: Pathogen
    requested: list[GeneQuery] = Field(
        description="The determinant strings as typed, unchanged and in order."
    )


class UnresolvedInput(Model):
    """An input that matched nothing. Reported, never silently dropped."""

    text: GeneQuery = Field(description="The requested string that could not be resolved.")
    reason: str = Field(min_length=1, description="Why it resolved to nothing, in plain words.")


class AffectedTarget(Model):
    """The sensitive form of the protein a determinant alters or replaces."""

    name: str = Field(description="Target name as CARD gives it.")
    pdb_ids: list[PdbId] = Field(
        description="Structures for this target, empty until the structure set names them."
    )


class ProfileGeneVariant(Model):
    mutation: MutationLabel
    param_type: str = Field(
        description="How CARD classifies the variant, e.g. single resistance variant."
    )


class ProfileGene(Model):
    """One resolved resistance determinant."""

    aro_id: AroId
    name: str = Field(description="Determinant name as CARD gives it.")
    model_type: str = Field(
        description="CARD detection model behind it, e.g. protein homolog model."
    )
    mechanisms: list[AroTerm] = Field(
        min_length=1, description="Resistance mechanisms CARD links to this determinant."
    )
    defeated_classes: list[AroTerm] = Field(
        description="Drug classes CARD links to it. Class-level: read as ruled out, not ruled in."
    )
    variants: list[ProfileGeneVariant] = Field(
        description="Point mutations found, for a variant model. Empty for a homolog model."
    )
    affected_target: AffectedTarget | None = Field(
        description=(
            "The sensitive target this determinant alters or replaces, or null where CARD "
            "names none (enzymes, pumps and most regulators)."
        )
    )
    evidence_ids: list[ProfileEvidenceId] = Field(
        min_length=1, description="Evidence items in this profile that support the row."
    )


class MechanismSummary(Model):
    """A mechanism present in the isolate, with the determinants behind it."""

    aro_id: AroId
    name: str = Field(description="Mechanism name in CARD's vocabulary.")
    gene_aro_ids: list[AroId] = Field(
        min_length=1, description="Determinants in this profile that carry the mechanism."
    )


class DefeatedClass(Model):
    """A drug class the isolate is expected to resist."""

    aro_id: AroId
    name: str = Field(description="Drug-class name in CARD's vocabulary.")
    gene_aro_ids: list[AroId] = Field(
        min_length=1, description="Determinants in this profile linked to the class."
    )
    evidence_ids: list[ProfileEvidenceId] = Field(
        min_length=1, description="Evidence items behind the link."
    )


class AffectedTargetSummary(Model):
    name: str = Field(description="Target name as CARD gives it.")
    gene_aro_ids: list[AroId] = Field(
        min_length=1, description="Determinants in this profile that affect the target."
    )
    pdb_ids: list[PdbId] = Field(description="Structures for the target, empty when none are set.")


class ProfileEvidence(Model):
    """One cited statement behind a row of the profile."""

    id: ProfileEvidenceId
    source: ResistanceEvidenceSource = Field(description="Where the statement comes from.")
    release: DataRelease = Field(description="The pinned release it was read from.")
    aro_id: AroId = Field(description="The term the statement is about.")
    statement: str = Field(min_length=1, description="What the source says, in one sentence.")


class ProfileConfidence(Model):
    level: ConfidenceLevel = Field(description="How much weight the profile carries.")
    basis: str = Field(min_length=1, description="Why that level, in plain words.")


class ResistanceProfile(Model):
    """What an isolate is expected to resist, and why (docs/contracts.md).

    Gene presence in CARD is not proof of expression, and `defeated_classes` is
    class-level, so it rules drugs out rather than in.
    """

    contract_version: Literal["1"] = Field(description="Version of the profile contract.")
    profile_id: ProfileId
    input: ProfileInput
    unresolved_inputs: list[UnresolvedInput] = Field(
        description="Requested names that matched nothing, each with a reason."
    )
    releases: list[DataRelease] = Field(
        min_length=1, description="The pinned releases the profile was built from."
    )
    genes: list[ProfileGene] = Field(description="One row per resolved determinant.")
    mechanisms: list[MechanismSummary] = Field(
        description="Mechanisms across the determinants. Derivable from `genes`."
    )
    defeated_classes: list[DefeatedClass] = Field(
        description="Drug classes across the determinants. Derivable from `genes`."
    )
    affected_targets: list[AffectedTargetSummary] = Field(
        description="Targets across the determinants. Derivable from `genes`."
    )
    evidence: list[ProfileEvidence] = Field(description="Every cited statement, by ID.")
    confidence: ProfileConfidence
    caveats: list[str] = Field(
        min_length=1, description="How to read the profile. There is always at least one."
    )


class PathogenPreset(Model):
    """A pathogen the app can profile without typing gene names."""

    id: str = Field(
        pattern=r"^[a-z0-9_]+$",
        description="Preset ID used in requests, e.g. s_aureus_mrsa.",
        examples=["s_aureus_mrsa"],
    )
    label: str = Field(description="What to show in the picker, e.g. MRSA (S. aureus).")
    pathogen: Pathogen
    profile_id: ProfileId | None = Field(
        description="The profile already built for this preset, or null when none is."
    )
    note: str | None = Field(
        description="What the preset stands for, or null. Says so when it is fixture data."
    )


class PathogenPresets(Model):
    items: list[PathogenPreset] = Field(description="Every preset this API can profile.")


class ProfileList(Model):
    items: list[ResistanceProfile] = Field(description="Every profile this API holds.")


# Certificate ---------------------------------------------------------------


class RuleOutcome(Model):
    """One property rule, with how far the value sits from its limit."""

    rule: PropertyRule
    passed: bool = Field(description="True when `margin` is at or below zero.")
    value: float = Field(description="The molecule's value for the rule.")
    limit: float = Field(description="The rule's limit in this rule set.")
    margin: float = Field(description="`value - limit`. Positive means the limit was exceeded.")


class Certificate(Model):
    """A Lean 4 proof that the encoded property rules hold for one molecule.

    It says nothing about safety, selectivity or activity. `certified` is never
    true unless Lean actually `ran`.
    """

    inchikey: InchiKey
    rule_set: RuleSet = Field(description="Which limits were proved against.")
    ran: bool = Field(
        description="False when Lean was missing, timed out, or the input was unusable."
    )
    certified: bool = Field(description="True only when Lean ran and every rule passed.")
    rules: list[RuleOutcome] = Field(description="One row per property rule, in a fixed order.")
    failed_rules: list[PropertyRule] = Field(
        description="Rules that failed, without the Lean rule_ prefix. Empty when Lean did not run."
    )
    lean_version: str | None = Field(description="Lean version used, or null when it did not run.")
    seconds: float | None = Field(
        ge=0, description="How long the proof took, or null when it did not run."
    )
    detail: str | None = Field(
        description=(
            "Why it did not run, or which theorem failed. Null when there is nothing to say."
        )
    )

    @model_validator(mode="after")
    def _check_outcome(self) -> Certificate:
        if [r.rule for r in self.rules] != list(PROPERTY_RULES):
            raise ValueError(f"rules must be {list(PROPERTY_RULES)}, in that order")
        if not self.ran:
            if self.certified:
                raise ValueError("certified cannot be true when Lean did not run")
            if self.failed_rules:
                raise ValueError("failed_rules must be empty when Lean did not run")
            if not self.detail:
                raise ValueError("detail must say why Lean did not run")
            return self
        failed = [r.rule for r in self.rules if not r.passed]
        if self.failed_rules != failed:
            raise ValueError(f"failed_rules must be {failed}")
        if self.certified != (not failed):
            raise ValueError("certified must be true exactly when no rule failed")
        return self


class CertificateList(Model):
    contract_version: Literal["1"] = Field(description="Version of the certificate contract.")
    certificates: list[Certificate] = Field(description="Every certificate this API holds.")


# AntibioticCandidate ------------------------------------------------------


class SmokeDescriptors(Model):
    """RDKit descriptors the smoke test measured."""

    mw: float = Field(description="Molecular weight, in daltons.")
    logp: float = Field(description="Crippen logP.")
    hbd: int = Field(ge=0, description="Hydrogen-bond donors.")
    hba: int = Field(ge=0, description="Hydrogen-bond acceptors.")
    rot_bonds: int = Field(ge=0, description="Rotatable bonds.")
    psa: float = Field(ge=0, description="Topological polar surface area, in square angstroms.")
    heavy_atoms: int = Field(ge=0, description="Heavy-atom count.")


class SmokeViolation(Model):
    rule: ViolationRule = Field(
        description="The rule broken: a property rule, a structural alert or synthetic access."
    )
    value: float
    limit: float
    margin: float = Field(description="`value - limit`, so positive.")


class SmokeTest(Model):
    """Output of `htb_verify.smoke` for one molecule: the Python check Lean then proves."""

    rule_set: RuleSet
    valid: bool = Field(description="False when RDKit could not read the SMILES.")
    passed: bool = Field(description="True exactly when `violations` is empty.")
    strict_alerts: bool = Field(
        description="Whether a structural alert counted as a violation in this run."
    )
    descriptors: SmokeDescriptors | None = Field(
        description="What was measured, or null when the molecule could not be read."
    )
    violations: list[SmokeViolation] = Field(description="Every rule broken, with its margin.")
    alerts: list[str] = Field(
        description="PAINS and Brenk alerts matched. Recorded whether or not they count."
    )
    sa_score: float | None = Field(
        description="Synthetic accessibility, 1 (easy) to 10 (hard), or null when not computed."
    )


class EvasionHit(Model):
    """A determinant that defeats a candidate, and the mechanism it uses."""

    gene_aro_id: AroId = Field(description="The determinant in the profile.")
    mechanism_aro_id: AroId = Field(description="One of that determinant's mechanisms.")


class Evasion(Model):
    """Whether the profile's determinants are known to defeat this candidate.

    `unaffected` means no link in CARD, which is not a measured result.
    `unknown` means CARD cannot say, which is not the same as `unaffected`.
    """

    status: EvasionStatus
    defeated_by: list[EvasionHit] = Field(
        description="Determinants that defeat it. Empty unless the status says otherwise."
    )
    profile_evidence_ids: list[ProfileEvidenceId] = Field(
        description="Evidence in the ResistanceProfile behind this call."
    )
    rationale: str = Field(min_length=1, description="Why that status, in one sentence.")

    @model_validator(mode="after")
    def _check_hits(self) -> Evasion:
        if self.status in ("unaffected", "unknown") and self.defeated_by:
            raise ValueError(f"a {self.status} candidate cannot name a determinant")
        if self.status in ("defeated", "partly_affected") and not self.defeated_by:
            raise ValueError(f"a {self.status} candidate must name the determinant")
        return self


class CandidateEvidence(Model):
    """One cited statement behind a candidate's row, local to this result."""

    id: EvidenceId
    kind: CandidateEvidenceKind
    source: CandidateEvidenceSource
    release: str = Field(
        min_length=1, description="The pinned release, or the rule set for a local check."
    )
    source_id: str = Field(min_length=1, description="The record's ID in that source.")
    statement: str = Field(min_length=1, description="What the source says, in one sentence.")


class CandidateFeature(Model):
    """One feature, kept on its own and never blended into a score.

    Missing data is `available: false`, never zero.
    """

    available: bool = Field(description="False when there is no data for this feature.")
    value: float | str | None = Field(
        description="The measurement, or a coded word for a non-numeric one. Null when unavailable."
    )
    unit: str | None = Field(description="Unit of `value`, or null when it has none.")
    evidence_ids: list[EvidenceId] = Field(
        description="This candidate's evidence behind the value. Empty when unavailable."
    )

    @model_validator(mode="after")
    def _check_availability(self) -> CandidateFeature:
        if not self.available and (self.value is not None or self.evidence_ids):
            raise ValueError("an unavailable feature carries no value and no evidence")
        return self


class CandidateFeatures(Model):
    """The four features, each separate (docs/contracts.md)."""

    activity: CandidateFeature = Field(description="Measured activity against the pathogen.")
    target_hit: CandidateFeature = Field(description="Evidence the drug hits an unaffected target.")
    docking: CandidateFeature = Field(
        description="Docking score, a supporting signal only, never the headline."
    )
    safety: CandidateFeature = Field(description="Safety flags and structural alerts recorded.")


class CandidateExplanation(Model):
    """Why the candidate sits where it does, and what is not known."""

    summary: str = Field(min_length=1, description="One or two sentences on the placement.")
    mechanisms_evaded: list[str] = Field(
        description="Mechanisms in the profile this candidate is not linked to."
    )
    missing: list[str] = Field(description="Data that would change the placement, but is absent.")
    caveats: list[str] = Field(description="How to read the row.")


class GeneratedProvenance(Model):
    """Where a generated molecule came from. Hypotheses only, never ranked with approved drugs."""

    model: str = Field(min_length=1, description="The generator that proposed the molecule.")
    model_version: str = Field(description="Pinned version of that generator.")
    seed: int = Field(description="Random seed, so the proposal can be reproduced.")
    pocket_pdb_id: PdbId | None = Field(
        description="The pocket it was generated into, or null when none was used."
    )
    parent_candidate_id: AntibioticId | None = Field(
        description="The approved drug it was derived from, or null."
    )


class CandidateTargetRef(Model):
    """What a candidate acts on, linked to the profile's determinants where it is one."""

    name: str = Field(description="Target name, display text only.")
    gene_aro_ids: list[AroId] = Field(
        description="Determinants in the profile that affect this target, empty when none do."
    )


class AntibioticCandidate(Model):
    """One molecule in a ranking, with its evasion call, features and verification."""

    candidate_id: AntibioticId
    name: str = Field(description="Display name of the molecule.")
    source: CandidateSource = Field(
        description="approved: a licensed drug. generated: a proposal, never ranked."
    )
    smiles: str = Field(min_length=1, description="The structure, as SMILES.")
    inchikey: InchiKey
    drug_class: AroTerm | None = Field(
        description=(
            "CARD drug class, or null when the molecule has none (any generated one). "
            "`aro_id` is null when the class is known by name but unmapped."
        )
    )
    mechanism_of_action: str | None = Field(
        description="How the drug acts, or null when it is not recorded."
    )
    target: CandidateTargetRef | None = Field(
        description="What it acts on, or null when that is not recorded."
    )
    rank: int | None = Field(
        ge=1,
        description="Place among the approved candidates, 1 best. Null for a generated molecule.",
    )
    evasion: Evasion
    features: CandidateFeatures
    explanation: CandidateExplanation
    smoke_test: SmokeTest
    certificate_status: CertificateStatus = Field(
        description="not_run: Lean was not asked. unavailable: it was, and could not run."
    )
    certificate: Certificate | None = Field(
        description="The proof, or null when the status is not_run."
    )
    generated: GeneratedProvenance | None = Field(
        description="Provenance of a generated molecule; null for an approved drug."
    )
    evidence: list[CandidateEvidence] = Field(
        description="Every cited statement for this candidate, by ID."
    )

    @model_validator(mode="after")
    def _check_source_and_certificate(self) -> AntibioticCandidate:
        if (self.source == "generated") != (self.generated is not None):
            raise ValueError("a generated molecule carries provenance, an approved drug none")
        if self.source == "generated" and self.rank is not None:
            raise ValueError("a generated molecule is never ranked with approved drugs")
        if (self.certificate_status == "not_run") != (self.certificate is None):
            raise ValueError("a certificate is present for every status but not_run")
        if self.certificate is None:
            return self
        if self.certificate.inchikey != self.inchikey:
            raise ValueError("the certificate must be for this molecule")
        if self.certificate.rule_set != self.smoke_test.rule_set:
            raise ValueError("the certificate and the smoke test must use one rule set")
        expected = {
            "certified": self.certificate.ran and self.certificate.certified,
            "failed": self.certificate.ran and not self.certificate.certified,
            "unavailable": not self.certificate.ran,
        }[self.certificate_status]
        if not expected:
            raise ValueError(f"the certificate does not match the status {self.certificate_status}")
        return self


class RankingMethodInfo(Model):
    """How the ranks were made, recorded so a result can be reproduced."""

    method: str = Field(min_length=1, description="The ranking method, e.g. ordered_rule_v0.")
    order: list[RankingFeature] = Field(
        min_length=1, description="Features in the order the rule applies them, evasion first."
    )
    weights: dict[RankingFeature, float] | None = Field(
        description="Per-feature weights, or null for an ordered rule that blends nothing."
    )
    note: str | None = Field(description="Anything else needed to read the ranking, or null.")


class AntibioticCandidateResult(Model):
    """A ranking of antibiotics against one ResistanceProfile (docs/contracts.md).

    The strongest claims allowed are "predicted to evade known mechanisms" and
    "passes the encoded rules". A computational hit is not a working antibiotic.
    """

    contract_version: Literal["1"] = Field(description="Version of the candidate contract.")
    result_id: UUID = Field(description="ID of this ranking run.")
    profile_id: ProfileId = Field(description="The profile that was ranked against.")
    pathogen: Pathogen
    releases: list[DataRelease] = Field(
        min_length=1, description="The pinned releases the ranking was built from."
    )
    ranking: RankingMethodInfo
    candidates: list[AntibioticCandidate] = Field(
        description="Approved drugs in rank order, then any generated proposals."
    )
    fixture_note: str | None = Field(
        default=None,
        description="Set when this is fixture data: says the numbers are made up.",
    )

    @model_validator(mode="after")
    def _check_ranks(self) -> AntibioticCandidateResult:
        ranks = sorted(c.rank for c in self.candidates if c.rank is not None)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("ranks must run 1..n over the approved candidates")
        order = {"unaffected": 0, "partly_affected": 1, "defeated": 2, "unknown": 3}
        ranked = sorted(
            (c for c in self.candidates if c.rank is not None), key=lambda c: c.rank or 0
        )
        levels = [order[c.evasion.status] for c in ranked]
        if levels != sorted(levels):
            raise ValueError(
                "evasion comes first: no defeated candidate outranks an unaffected one"
            )
        return self
