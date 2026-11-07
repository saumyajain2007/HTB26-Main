"""Every route of plan.md section 9.1, plus /api/health."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, status
from fastapi.responses import FileResponse

from .. import __version__
from ..deps import ComponentsDep, ResistanceDep, ServiceDep
from ..errors import NotFound, Unavailable, responses
from ..schemas import (
    AntibioticCandidateResult,
    CertificateList,
    CommonDiseases,
    Conformer,
    DiseaseSearchResponse,
    DockJob,
    DockRequest,
    Evaluation,
    Experiment,
    ExperimentCreate,
    ExperimentList,
    Health,
    JuryRun,
    PathogenPresets,
    ProfileList,
    ResistanceProfile,
    StructureList,
)
from ..services.docking import FILE_MEDIA_TYPES
from ..services.molecules import MoleculesUnavailable

router = APIRouter(prefix="/api")


@router.get("/health", tags=["health"], summary="Check that the API is up")
def health(components: ComponentsDep) -> Health:
    return Health(status="ok", source=components.settings.source, version=__version__)


# Diseases --------------------------------------------------------------------


@router.get(
    "/diseases/search",
    tags=["diseases"],
    summary="Search Diseases this API can build an Experiment for",
    responses=responses(422, 503),
)
def search_diseases(
    service: ServiceDep,
    q: Annotated[str, Query(min_length=1, max_length=200, description="Search text.")],
    limit: Annotated[int, Query(ge=1, le=50, description="Most results to return.")] = 10,
) -> DiseaseSearchResponse:
    return DiseaseSearchResponse(query=q, results=service.search(q, limit))


@router.get(
    "/diseases/common",
    tags=["diseases"],
    summary="Well-known Diseases to offer before a search, the one to show first leading",
    responses=responses(503),
)
def common_diseases(service: ServiceDep) -> CommonDiseases:
    return CommonDiseases(items=service.common_diseases())


# Experiments -------------------------------------------------------------------


@router.post(
    "/experiments",
    tags=["experiments"],
    summary="Create an Experiment and start building it",
    status_code=status.HTTP_202_ACCEPTED,
    responses=responses(422, 503),
)
def create_experiment(body: ExperimentCreate, service: ServiceDep) -> Experiment:
    """Returns the queued Experiment at once. Poll it until `status` is ready or failed."""
    return service.create(body.disease_id)


@router.get(
    "/experiments",
    tags=["experiments"],
    summary="List saved Experiments (history)",
    responses=responses(422),
)
def list_experiments(
    service: ServiceDep,
    archived: Annotated[
        bool, Query(description="List archived Experiments instead of active ones.")
    ] = False,
    include_building: Annotated[
        bool,
        Query(description="Also list Experiments that are queued, building or failed."),
    ] = False,
) -> ExperimentList:
    return ExperimentList(
        items=service.history(archived=archived, include_building=include_building)
    )


@router.get(
    "/experiments/{experiment_id}",
    tags=["experiments"],
    summary="Get an Experiment with its Targets, Candidates, jury and docking jobs",
    responses=responses(404, 422),
)
def get_experiment(experiment_id: UUID, service: ServiceDep) -> Experiment:
    return service.get(experiment_id)


@router.post(
    "/experiments/{experiment_id}/jury",
    tags=["experiments"],
    summary="Ask the Model jury to review the shortlist",
    status_code=status.HTTP_202_ACCEPTED,
    responses=responses(404, 409, 422),
)
def ask_jury(experiment_id: UUID, service: ServiceDep) -> JuryRun:
    """Once per Experiment. Poll the Experiment to follow each juror's progress."""
    return service.ask_jury(experiment_id)


@router.post(
    "/experiments/{experiment_id}/follow-ups",
    tags=["experiments"],
    summary="Start the jury and every binding pose the reader will look at next",
    responses=responses(404, 409, 422),
)
def start_follow_ups(experiment_id: UUID, service: ServiceDep) -> Experiment:
    """The web app asks once the reader moves past choosing the Disease. Asking again starts
    nothing new. Poll the Experiment to follow the jury and the poses."""
    return service.start_follow_ups(experiment_id)


@router.post(
    "/experiments/{experiment_id}/archive",
    tags=["experiments"],
    summary="Archive an Experiment: hide it from history, keeping it recoverable",
    responses=responses(404, 409, 422),
)
def archive_experiment(experiment_id: UUID, service: ServiceDep) -> Experiment:
    return service.archive(experiment_id)


@router.post(
    "/experiments/{experiment_id}/restore",
    tags=["experiments"],
    summary="Restore an archived Experiment to history",
    responses=responses(404, 422),
)
def restore_experiment(experiment_id: UUID, service: ServiceDep) -> Experiment:
    return service.restore(experiment_id)


# Docking -----------------------------------------------------------------------


@router.get(
    "/structures",
    tags=["docking"],
    summary="List the prepared protein structures and their redocking controls",
)
def list_structures(components: ComponentsDep) -> StructureList:
    return StructureList(structures=components.docking.structures())


@router.post(
    "/dock",
    tags=["docking"],
    summary="Request a binding pose for one Candidate in one prepared structure",
    status_code=status.HTTP_202_ACCEPTED,
    responses=responses(404, 409, 422),
)
def request_dock(body: DockRequest, service: ServiceDep) -> DockJob:
    """An identical earlier computation is reused: the job is then already done and
    `cached_from` names the job it reuses. Otherwise poll `GET /api/dock/{job_id}`."""
    return service.request_dock(body)


@router.get(
    "/dock/{job_id}",
    tags=["docking"],
    summary="Get a docking job's status and results, including failures",
    responses=responses(404, 422),
)
def get_dock_job(job_id: UUID, service: ServiceDep) -> DockJob:
    return service.get_dock_job(job_id)


_FILE_CONTENT: dict[str, dict[str, object]] = {
    media_type.split(";")[0]: {
        "schema": {"type": "object"} if media_type == "application/json" else {"type": "string"}
    }
    for media_type in FILE_MEDIA_TYPES.values()
}


@router.get(
    # `:path` lets names holding a slash reach the allow-list, so they get a plain 404.
    "/files/{job_id}/{name:path}",
    tags=["docking"],
    summary="Download one result file of a finished docking job",
    response_class=FileResponse,
    responses={
        200: {"description": "The file, in its own format.", "content": _FILE_CONTENT},
        **responses(404, 422),
    },
)
def get_dock_file(
    job_id: UUID,
    service: ServiceDep,
    name: Annotated[
        str,
        Path(
            description=(
                "receptor.pdb, poses.sdf, crystal_ligand.sdf, scores.json or log.txt. "
                "The URLs are listed in the job's `files`."
            )
        ),
    ],
) -> FileResponse:
    """A job that reuses another job's result (`cached_from`) serves that job's files."""
    path, known = service.dock_file(job_id, name)
    return FileResponse(
        path,
        media_type=FILE_MEDIA_TYPES[known],
        filename=known,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


# Molecules ---------------------------------------------------------------------


@router.get(
    "/molecules/{pubchem_cid}/conformer",
    tags=["molecules"],
    summary="Get a small molecule's 3D conformer for drawing",
    responses=responses(404, 422, 503),
)
def get_conformer(
    components: ComponentsDep,
    pubchem_cid: Annotated[int, Path(gt=0, description="PubChem compound ID.")],
) -> Conformer:
    """Display only. A compound with no 3D model (antibodies and other biologics have none)
    answers 404; 503 means PubChem couldn't be asked, not that there is no model."""
    try:
        conformer = components.molecules.conformer(pubchem_cid)
    except MoleculesUnavailable as exc:
        raise Unavailable(
            f"PubChem isn't answering, so the 3D model of compound {pubchem_cid} can't be loaded."
        ) from exc
    if conformer is None:
        raise NotFound(f"No 3D structure is available for PubChem compound {pubchem_cid}.")
    return conformer


# Evaluation --------------------------------------------------------------------


@router.get("/evaluation", tags=["evaluation"], summary="Get the frozen evaluation metrics")
def get_evaluation(components: ComponentsDep) -> Evaluation:
    return components.evaluation.evaluation()


# Resistance ----------------------------------------------------------------
#
# The antibiotic flow of docs/contracts.md: pick a pathogen, read its
# ResistanceProfile, then read the antibiotics ranked against it. Fixture-backed
# until the profiling and ranking pipelines land (#16, #23).


@router.get(
    "/resistance/pathogens",
    tags=["resistance"],
    summary="List the pathogens a profile can be built for",
)
def list_pathogens(resistance: ResistanceDep) -> PathogenPresets:
    """A preset with `profile_id: null` has no profile built yet."""
    return PathogenPresets(items=resistance.presets())


@router.get(
    "/resistance/profiles",
    tags=["resistance"],
    summary="List the resistance profiles this API holds",
)
def list_profiles(resistance: ResistanceDep) -> ProfileList:
    return ProfileList(items=resistance.profiles())


@router.get(
    "/resistance/profiles/{profile_id}",
    tags=["resistance"],
    summary="Get a resistance profile: determinants, mechanisms and defeated drug classes",
    responses=responses(404, 422),
)
def get_resistance_profile(profile_id: UUID, resistance: ResistanceDep) -> ResistanceProfile:
    """`defeated_classes` is class-level: read it as ruling drugs out, not in. A gene
    in CARD can confer resistance; it does not show the gene is expressed."""
    profile = resistance.profile(profile_id)
    if profile is None:
        raise NotFound(f"No resistance profile {profile_id}.")
    return profile


@router.get(
    "/resistance/profiles/{profile_id}/candidates",
    tags=["resistance"],
    summary="Get the antibiotics ranked against a profile, with evasion and verification",
    responses=responses(404, 422),
)
def get_antibiotic_candidates(
    profile_id: UUID, resistance: ResistanceDep
) -> AntibioticCandidateResult:
    """Approved drugs in rank order, then any generated proposals, which are never
    ranked with them. `unaffected` means no known link in CARD, not a measured result."""
    result = resistance.candidates(profile_id)
    if result is None:
        if resistance.profile(profile_id) is None:
            raise NotFound(f"No resistance profile {profile_id}.")
        raise NotFound(f"No antibiotics have been ranked against profile {profile_id} yet.")
    return result


@router.get(
    "/resistance/certificates",
    tags=["resistance"],
    summary="List the Lean certificates this API holds",
)
def list_certificates(resistance: ResistanceDep) -> CertificateList:
    """A certificate confirms the encoded property rules hold. It does not show a
    molecule is safe, selective or active."""
    return resistance.certificates()
