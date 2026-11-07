"""The product rules: what may happen to an Experiment, and when.

- Building is in the background: create returns a queued Experiment at once.
- The Model jury is asked at most once per Experiment, and only when it is ready.
- Jury and docking requests are refused while an Experiment is archived.
- Archiving is refused while the Experiment is building or a docking job is live.
- An identical docking computation is reused instead of run twice, and an
  Experiment has at most `MAX_LIVE_DOCK_JOBS` computations waiting or running
  that a reader asked for.
- Once a reader moves past choosing the Disease, the Experiment's follow-ups
  start (`start_follow_ups`): the jury's review and a binding pose for every
  drug that can be docked, so the later steps are ready sooner.

Each change and the job it needs are made in one `repo.locked()` block, so the
Postgres repo checks the rule, writes the change and queues the job in one
transaction.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID, uuid4

from ..errors import Conflict, NotFound, Unavailable, Unprocessable
from ..jobs import JobRef, Runner, pending_jurors, utcnow
from ..repo import AlreadyExists, DockInputs, DuplicateComputation, Repo
from ..schemas import (
    DOCK_FILE_NAMES,
    DiseaseRef,
    DiseaseSearchResult,
    DockFileName,
    DockFiles,
    DockJob,
    DockRequest,
    Experiment,
    ExperimentSummary,
    JuryRun,
)
from ..settings import Settings
from .docking import DockingBackend, cache_key, structure_for, unsupported_reason
from .jury import JuryBackend, JuryUnavailable
from .source import ExperimentSource, SourceError

log = logging.getLogger(__name__)

LIVE_DOCK_STATUSES = ("queued", "running")
MAX_LIVE_DOCK_JOBS = 3
"""Most binding poses one Experiment may have waiting or computing at once
(build-reference C7). A request that reuses a result does not count."""
_DOCK_FILES: dict[str, DockFileName] = {name: name for name in DOCK_FILE_NAMES.values()}


class ExperimentService:
    def __init__(
        self,
        repo: Repo,
        source: ExperimentSource,
        jury: JuryBackend,
        docking: DockingBackend,
        runner: Runner,
        session_id: str | None = None,
        client_id: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.repo = repo
        self.source = source
        self.jury = jury
        self.docking = docking
        self.runner = runner
        self.session_id = session_id
        self.client_id = client_id
        self.settings = settings or Settings()

    def _quota(self, kind: str, limit: int) -> None:
        if self.session_id is not None:
            self.repo.consume_quota(f"{kind}:session:{self.session_id}", limit, 3600)
            self.repo.consume_quota(f"{kind}:ip:{self.client_id}", limit * 3, 3600)

    # Experiments ------------------------------------------------------------

    def create(self, disease_id: str) -> Experiment:
        self._quota("experiment", self.settings.experiments_per_hour)
        try:
            plan = self.source.plan(disease_id)
        except SourceError as exc:
            raise Unavailable(str(exc)) from exc
        if plan is None:
            raise Unprocessable(
                f"There is no data for the Disease {disease_id}. Search for a Disease and "
                "use one of the results."
            )
        try:
            jury_config = self.jury.configure(plan.jury_config)
        except JuryUnavailable as exc:
            raise Unavailable(str(exc)) from exc
        experiment = Experiment(
            id=uuid4(),
            status="queued",
            stage=None,
            error=None,
            disease=plan.disease,
            data_releases=plan.data_releases,
            ranking_method=plan.ranking_method,
            ranking_settings=plan.ranking_settings,
            jury_config=jury_config,
            targets=[],
            network=None,
            candidates=[],
            jury=None,
            dock_jobs=[],
            fixture_note=plan.fixture_note,
            created_at=utcnow(),
            archived_at=None,
        )
        with self.repo.transaction():
            self.repo.consume_quota("experiment:day", self.settings.experiments_per_day, 86400)
            self.repo.add_experiment(experiment, owner_session=self.session_id)
            self.runner.submit(JobRef("experiment_build", experiment.id))
        return experiment

    def get(self, experiment_id: UUID) -> Experiment:
        if self.session_id is not None and not self.repo.owns_experiment(
            experiment_id, self.session_id
        ):
            raise NotFound("There is no saved Experiment with this ID.")
        experiment = self.repo.get_experiment(experiment_id)
        if experiment is None:
            raise NotFound("There is no saved Experiment with this ID.")
        return experiment.model_copy(
            update={"dock_jobs": [self._present_dock(job) for job in experiment.dock_jobs]}
        )

    def _present_dock(self, job: DockJob) -> DockJob:
        # A reused private computation must be downloaded through this browser's
        # own job. Public redocking controls keep their shared URLs.
        if job.files is None or job.cached_from is None:
            return job
        original = self.repo.get_dock_job(job.cached_from)
        if original is None or original.experiment_id is None:
            return job
        files = job.files.model_dump()
        for field, name in DOCK_FILE_NAMES.items():
            files[field]["url"] = f"/api/files/{job.id}/{name}"
        return job.model_copy(update={"files": DockFiles.model_validate(files)})

    def search(self, query: str, limit: int) -> list[DiseaseSearchResult]:
        try:
            return self.source.search_diseases(query, limit)
        except SourceError as exc:
            raise Unavailable(str(exc)) from exc

    def common_diseases(self) -> list[DiseaseRef]:
        try:
            return self.source.common_diseases()
        except SourceError as exc:
            raise Unavailable(str(exc)) from exc

    def history(self, *, archived: bool, include_building: bool) -> list[ExperimentSummary]:
        return self.repo.list_experiments(
            archived=archived, include_building=include_building, owner_session=self.session_id
        )

    def archive(self, experiment_id: UUID) -> Experiment:
        with self.repo.locked(experiment_id):
            experiment = self.get(experiment_id)
            if experiment.status in ("queued", "building"):
                raise Conflict("This Experiment is still being built. Archive it once it is ready.")
            if any(job.status in LIVE_DOCK_STATUSES for job in experiment.dock_jobs):
                raise Conflict(
                    "A binding pose is still being computed for this Experiment. Archive it "
                    "once the docking job has finished."
                )
            if experiment.archived_at is None:
                self.repo.set_archived_at(experiment_id, utcnow())
            return self.get(experiment_id)

    def restore(self, experiment_id: UUID) -> Experiment:
        with self.repo.locked(experiment_id):
            experiment = self.get(experiment_id)
            if experiment.archived_at is not None:
                self.repo.set_archived_at(experiment_id, None)
            return self.get(experiment_id)

    def _require_active_and_ready(self, experiment: Experiment, action: str) -> None:
        if experiment.archived_at is not None:
            raise Conflict(f"This Experiment is archived. Restore it to {action}.")
        if experiment.status == "failed":
            raise Conflict(f"This Experiment failed to build, so you cannot {action}.")
        if experiment.status != "ready":
            raise Conflict(
                f"This Experiment is still being built. Wait until it is ready to {action}."
            )

    # Model jury -------------------------------------------------------------

    def ask_jury(self, experiment_id: UUID) -> JuryRun:
        with self.repo.locked(experiment_id):
            experiment = self.get(experiment_id)
            self._require_active_and_ready(experiment, "ask the Model jury")
            if experiment.jury is not None:
                raise Conflict("The Model jury has already reviewed this Experiment.")
            self._quota("jury", self.settings.jury_per_hour)
            models = experiment.jury_config.models
            run = JuryRun(
                status="queued",
                models=models,
                jurors=pending_jurors(models),
                votes=[],
                consensus=None,
                agreement=None,
                contested=[],
                error=None,
                created_at=utcnow(),
                started_at=None,
                finished_at=None,
            )
            try:
                self.repo.add_jury_run(experiment_id, run)
                self.runner.submit(JobRef("jury_run", experiment_id))
            except AlreadyExists:
                raise Conflict(
                    "The Model jury has already reviewed this Experiment. Each Experiment has "
                    "one jury review."
                ) from None
        return run

    # Follow-ups ---------------------------------------------------------------

    def start_follow_ups(self, experiment_id: UUID) -> Experiment:
        """Start what a reader will ask for next, once they move past choosing the Disease,
        so the later steps wait less: the Model jury's review, and a binding pose for each drug
        that can be docked (the known-answer drug first, then shortlist order), each into the
        structure the binding-pose step opens on. Not on choosing alone: a reader trying
        Diseases on step 1 shouldn't set the slow work going for each. Anything already asked
        for is left alone, so asking again is harmless, and one follow-up that can't start
        never stops the others. Returns the Experiment with what was started."""
        experiment = self.get(experiment_id)
        self._require_active_and_ready(experiment, "prepare its next steps")
        if experiment.jury is None:
            try:
                self.ask_jury(experiment_id)
            except (Conflict, Unavailable) as exc:
                log.warning("Experiment %s: the jury did not start: %s", experiment_id, exc)
        try:
            self._start_poses(experiment)
        except Exception:
            # The poses are a head start: the reader can still ask for each one.
            log.exception("Experiment %s: its binding poses did not start", experiment_id)
        return self.get(experiment_id)

    def _start_poses(self, experiment: Experiment) -> None:
        experiment_id = experiment.id
        structures = self.docking.structures()
        asked = {(job.candidate_id, job.structure_id) for job in experiment.dock_jobs}
        for candidate in sorted(experiment.candidates, key=lambda c: not c.known_answer):
            structure = structure_for(candidate, structures)
            if structure is None or (candidate.candidate_id, structure.id) in asked:
                continue
            request = DockRequest(
                experiment_id=experiment_id,
                candidate_id=candidate.candidate_id,
                structure_id=structure.id,
            )
            try:
                with self.repo.locked(experiment_id):
                    self._dock(request, capped=False)
            except (Conflict, Unprocessable) as exc:
                log.warning(
                    "Experiment %s: no pose for %s: %s", experiment_id, candidate.candidate_id, exc
                )

    # Docking ----------------------------------------------------------------

    def request_dock(self, request: DockRequest) -> DockJob:
        with self.repo.locked(request.experiment_id):
            return self._dock(request, capped=True)

    def _dock(self, request: DockRequest, *, capped: bool) -> DockJob:
        """Queue or reuse one binding pose; the caller holds the Experiment's lock. `capped`
        applies `MAX_LIVE_DOCK_JOBS`, which limits what a reader may queue at once; the
        follow-ups queue each dockable drug once, so they need no cap."""
        experiment = self.get(request.experiment_id)
        self._require_active_and_ready(experiment, "compute a binding pose")
        if len(experiment.dock_jobs) >= 60:
            raise Conflict("This Experiment has reached its limit of 60 binding-pose requests.")
        candidate = next(
            (c for c in experiment.candidates if c.candidate_id == request.candidate_id), None
        )
        if candidate is None:
            raise Unprocessable(f"{request.candidate_id} is not on this Experiment's shortlist.")
        structure = self.docking.structure(request.structure_id)
        if structure is None:
            raise Unprocessable(f"{request.structure_id} is not one of the prepared structures.")
        smiles = self.docking.ligand_smiles(candidate.candidate_id)
        reason = unsupported_reason(candidate, structure, smiles)
        if reason is not None:
            raise Unprocessable(reason)
        assert smiles is not None  # unsupported_reason refuses a drug without SMILES
        settings = self.docking.settings_for(structure)
        inputs = DockInputs(cache_key(structure, smiles, settings), smiles)
        job = DockJob(
            id=uuid4(),
            kind="candidate",
            status="queued",
            experiment_id=experiment.id,
            candidate_id=candidate.candidate_id,
            target_id=structure.target_id,
            structure_id=structure.id,
            settings=settings,
            scores=None,
            files=None,
            control_rmsd=None,
            error=None,
            cached_from=None,
            fixture=self.docking.fixture,
            created_at=utcnow(),
            started_at=None,
            finished_at=None,
        )
        reused = self.repo.find_reusable_dock_job(inputs.cache_key, job.fixture)
        if reused is None:
            computing = [
                j
                for j in experiment.dock_jobs
                if j.status in LIVE_DOCK_STATUSES and j.cached_from is None
            ]
            if capped and len(computing) >= MAX_LIVE_DOCK_JOBS:
                raise Conflict(
                    f"This Experiment already has {len(computing)} binding poses waiting "
                    "or being computed. Request another once one has finished."
                )
            self.repo.consume_quota("dock:day", 200, 86400)
            try:
                self.repo.add_dock_job(job, inputs)
                self.runner.submit(JobRef("dock", job.id))
                return job
            except DuplicateComputation:
                # Another request started the same computation since we looked.
                reused = self.repo.find_reusable_dock_job(inputs.cache_key, job.fixture)
                if reused is None:
                    raise
        # Identical inputs: reuse the result (or the live run) instead of docking again.
        job = job.model_copy(
            update={
                "status": reused.status,
                "scores": reused.scores,
                "files": reused.files,
                "fixture": reused.fixture,
                "cached_from": reused.id,
                "started_at": reused.started_at,
                "finished_at": job.created_at if reused.status == "done" else None,
            }
        )
        self.repo.add_dock_job(job, inputs)
        return self._present_dock(job)

    def get_dock_job(self, job_id: UUID) -> DockJob:
        job = self.repo.get_dock_job(job_id)
        if job is None:
            raise NotFound("There is no docking job with this ID.")
        if job.experiment_id is not None:
            self.get(job.experiment_id)
        return self._present_dock(job)

    def dock_file(self, job_id: UUID, name: str) -> tuple[Path, DockFileName]:
        """Where one of a docking job's result files is stored, and its name. A job that
        reuses another job's result serves that job's files."""
        job = self.get_dock_job(job_id)
        known = _DOCK_FILES.get(name)
        if known is None:
            raise NotFound(
                "Docking jobs have only these files: receptor.pdb, poses.sdf, "
                "crystal_ligand.sdf, scores.json and log.txt."
            )
        if job.files is None:
            raise NotFound(_no_files_reason(job))
        path = self.docking.result_file(job.cached_from or job.id, known)
        if path is None:
            raise NotFound(f"This docking job's {known} is missing from the results folder.")
        return path, known


def _no_files_reason(job: DockJob) -> str:
    if job.status in LIVE_DOCK_STATUSES:
        return f"This docking job is still {job.status}. Its files appear when it is done."
    if job.status == "failed":
        return "This docking job failed, so it has no result files. Its error says why."
    return "This result has scores only: no files were prepared for it."
