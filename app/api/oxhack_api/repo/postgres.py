"""Postgres storage on the tables in `db/migrations/` (0001 to 0006). psycopg 3, plain SQL.

How the contract maps onto the tables:

- `Experiment`: one `experiments` row (disease, releases, settings, build
  state, network, archive time), its `experiment_targets` rows, and its
  `candidates` rows. Each Candidate is stored whole in `candidates.payload`;
  the other columns are copies for querying.
- `JuryRun`: the `jury_runs` row (status, consensus, agreement, contested; the
  jury config is copied into `config`, whose `models` are the run's models),
  one `jurors` row per model from the moment the jury is asked, and one
  `jury_votes` row per review from a valid juror. Juror errors are kept in
  `jurors.validation.errors`.
- `DockJob`: one `dock_jobs` row; every field has a column of the same name.

The app never migrates. `open()` refuses a database older than
`SCHEMA_VERSION`; run `uv run db/migrate.py` first.

Every method runs in the caller's transaction when there is one (inside
`transaction()` or `locked()`), and in its own transaction otherwise.
"""

from __future__ import annotations

import math
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, LiteralString
from uuid import UUID

from psycopg import Connection, errors, sql
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..errors import Conflict, TooManyRequests
from ..schemas import (
    BuildStage,
    Candidate,
    DiseaseRef,
    DiseaseTarget,
    DockJob,
    Experiment,
    ExperimentStatus,
    ExperimentSummary,
    JuryModel,
    JuryRun,
    JuryVote,
    NetworkGraph,
)
from .base import AlreadyExists, DockInputs, DuplicateComputation

SCHEMA_VERSION = "0010"
"""The newest file in `db/migrations/` this code needs applied."""

Conn = Connection[DictRow]

# Triggers in 0003 that refuse a change the API refuses too. Their message is
# written for the person using the app, so it becomes a 409 as it is.
_GUARDS = frozenset({"experiments_archive_guard", "dock_jobs_experiment_active"})

_DOCK_COLUMNS: LiteralString = (
    "id, kind, status, experiment_id, candidate_id, target_id, structure_id, settings, "
    "scores, files, control_rmsd, error, cached_from, fixture, created_at, started_at, "
    "finished_at"
)


class SchemaOutOfDate(RuntimeError):
    """The database is missing migrations this code needs."""


def _json(value: Any) -> Jsonb | None:
    """A jsonb parameter, or SQL null (never JSON null) for None."""
    return None if value is None else Jsonb(value)


def _configure(conn: Conn) -> None:
    # Timestamps come back in UTC, as the API writes them.
    conn.execute("set time zone 'UTC'")
    conn.execute("set statement_timeout = '15s'")
    conn.execute("set lock_timeout = '5s'")
    conn.commit()


def _check(conn: Conn) -> None:
    """Make sure a pooled connection still works before handing it out."""
    conn.autocommit = True
    try:
        conn.execute("")
    finally:
        conn.autocommit = False


def _refusal(exc: errors.CheckViolation) -> Conflict | None:
    if exc.diag.constraint_name in _GUARDS:
        return Conflict(exc.diag.message_primary or str(exc))
    return None


class PostgresRepo:
    """Implements `Repo` on a connection pool. Thread-safe."""

    def __init__(self, conninfo: str, *, max_connections: int = 10) -> None:
        self._conninfo = conninfo
        self._pool: ConnectionPool[Conn] = ConnectionPool(
            conninfo,
            connection_class=Connection[DictRow],
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=max_connections,
            timeout=5,
            max_waiting=32,
            configure=_configure,
            check=_check,
            open=False,
            name="oxhack",
        )
        # The connection of the transaction the current thread is in, if any.
        self._current: ContextVar[Conn | None] = ContextVar(
            f"oxhack_pg_connection_{id(self)}", default=None
        )

    @property
    def conninfo(self) -> str:
        return self._conninfo

    @classmethod
    def connect(cls, conninfo: str, *, max_connections: int = 10) -> PostgresRepo:
        repo = cls(conninfo, max_connections=max_connections)
        repo.open()
        return repo

    def open(self, timeout: float = 10) -> None:
        """Connect and check the schema version. Raises if either fails."""
        try:
            self._pool.open(wait=True, timeout=timeout)
            self._check_schema()
        except BaseException:
            self._pool.close()
            raise

    def close(self) -> None:
        self._pool.close()

    def _check_schema(self) -> None:
        with self.connection() as conn:
            row = conn.execute(
                "select to_regclass('public.schema_migrations') is not null as present"
            ).fetchone()
            version = None
            if row and row["present"]:
                found = conn.execute("select max(version) as version from schema_migrations")
                version = (found.fetchone() or {}).get("version")
        if version is None or version < SCHEMA_VERSION:
            raise SchemaOutOfDate(
                f"The database schema is at {version or 'nothing'}, and this API needs "
                f"{SCHEMA_VERSION}. Run `uv run db/migrate.py` against it first."
            )

    # Transactions -----------------------------------------------------------

    @contextmanager
    def connection(self) -> Generator[Conn]:
        """The current transaction's connection, or a new transaction that commits
        when the block ends (and rolls back if it raises)."""
        current = self._current.get()
        if current is not None:
            yield current
            return
        with self._pool.connection() as conn:
            token = self._current.set(conn)
            try:
                yield conn
            finally:
                self._current.reset(token)

    @contextmanager
    def transaction(self) -> Generator[None]:
        with self.connection():
            yield

    @contextmanager
    def locked(self, experiment_id: UUID) -> Generator[None]:
        with self.connection() as conn:
            conn.execute("select 1 from experiments where id = %s for update", (experiment_id,))
            yield

    # Experiments ------------------------------------------------------------

    def consume_quota(self, key: str, limit: int, seconds: int) -> None:
        now = time.time()
        expires = (int(now) // seconds + 1) * seconds
        with self.connection() as conn:
            conn.execute("delete from request_quotas where expires_at <= %s", (int(now),))
            row = conn.execute(
                """
                insert into request_quotas (key, expires_at, used) values (%s, %s, 1)
                on conflict (key) do update set
                  used = case when request_quotas.expires_at = excluded.expires_at
                    then request_quotas.used + 1 else 1 end,
                  expires_at = excluded.expires_at
                returning used
                """,
                (key, expires),
            ).fetchone()
            assert row is not None
            if row["used"] > limit:
                raise TooManyRequests(max(1, math.ceil(expires - now)))

    def owns_experiment(self, experiment_id: UUID, owner_session: str) -> bool:
        with self.connection() as conn:
            return (
                conn.execute(
                    "select 1 from experiments where id = %s and owner_session = %s",
                    (experiment_id, owner_session),
                ).fetchone()
                is not None
            )

    def add_experiment(self, experiment: Experiment, *, owner_session: str | None = None) -> None:
        network = experiment.network.model_dump(mode="json") if experiment.network else None
        with self.connection() as conn:
            try:
                with conn.transaction():
                    conn.execute(
                        """
                        insert into experiments (
                          id, disease_id, disease_name, data_releases, jury_config,
                          ranking_method, ranking_settings, status, stage, error, network,
                          fixture_note, created_at, archived_at, owner_session
                        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            experiment.id,
                            experiment.disease.id,
                            experiment.disease.name,
                            experiment.data_releases,
                            Jsonb(experiment.jury_config.model_dump(mode="json")),
                            experiment.ranking_method,
                            Jsonb(experiment.ranking_settings.model_dump(mode="json")),
                            experiment.status,
                            experiment.stage,
                            experiment.error,
                            _json(network),
                            experiment.fixture_note,
                            experiment.created_at,
                            experiment.archived_at,
                            owner_session,
                        ),
                    )
            except errors.UniqueViolation as exc:
                raise AlreadyExists(f"Experiment {experiment.id}") from exc
            self._write_targets_and_candidates(
                conn, experiment.id, experiment.targets, experiment.candidates
            )

    def get_experiment(self, experiment_id: UUID) -> Experiment | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                select id, status, stage, error, disease_id, disease_name, data_releases,
                       ranking_method, ranking_settings, jury_config, network, fixture_note,
                       created_at, archived_at
                from experiments where id = %s
                """,
                (experiment_id,),
            ).fetchone()
            if row is None:
                return None
            targets = conn.execute(
                """
                select rank, target_id, symbol, name, evidence_only_score, retained,
                       excluded_reason
                from experiment_targets where experiment_id = %s order by rank
                """,
                (experiment_id,),
            ).fetchall()
            candidates = conn.execute(
                """
                select payload from candidates where experiment_id = %s
                order by (payload ->> 'shortlist_rank')::int
                """,
                (experiment_id,),
            ).fetchall()
            jury = self._read_jury(conn, experiment_id)
            dock_jobs = conn.execute(
                f"""
                select {_DOCK_COLUMNS} from dock_jobs where experiment_id = %s
                order by created_at desc, id
                """,
                (experiment_id,),
            ).fetchall()
        return Experiment.model_validate(
            {
                "id": row["id"],
                "status": row["status"],
                "stage": row["stage"],
                "error": row["error"],
                "disease": {"id": row["disease_id"], "name": row["disease_name"]},
                "data_releases": row["data_releases"],
                "ranking_method": row["ranking_method"],
                "ranking_settings": row["ranking_settings"],
                "jury_config": row["jury_config"],
                "targets": targets,
                "network": row["network"],
                "candidates": [c["payload"] for c in candidates],
                "jury": jury,
                "dock_jobs": dock_jobs,
                "fixture_note": row["fixture_note"],
                "created_at": row["created_at"],
                "archived_at": row["archived_at"],
            }
        )

    def list_experiments(
        self, *, archived: bool, include_building: bool, owner_session: str | None = None
    ) -> list[ExperimentSummary]:
        # Literal predicates, so the partial history index applies.
        where = [sql.SQL("e.archived_at is not null" if archived else "e.archived_at is null")]
        if not include_building:
            where.append(sql.SQL("e.status = 'ready'"))
        if owner_session is not None:
            where.append(sql.SQL("e.owner_session = %s"))
        query = sql.SQL(
            """
            select e.id, e.status, e.disease_id, e.disease_name, e.data_releases,
                   jsonb_array_length(e.jury_config -> 'models') as juror_count,
                   j.status as jury_status,
                   (select count(*) from candidates c where c.experiment_id = e.id)
                     as candidate_count,
                   (select count(*) from dock_jobs d
                     where d.experiment_id = e.id and d.status = 'done') as docked_count,
                   e.created_at, e.archived_at
            from experiments e
            left join jury_runs j on j.experiment_id = e.id
            where {where}
            order by e.created_at desc, e.id
            """
        ).format(where=sql.SQL(" and ").join(where))
        with self.connection() as conn:
            rows = conn.execute(
                query, (owner_session,) if owner_session is not None else ()
            ).fetchall()
        return [
            ExperimentSummary(
                id=row["id"],
                status=row["status"],
                disease=DiseaseRef(id=row["disease_id"], name=row["disease_name"]),
                data_releases=row["data_releases"],
                juror_count=row["juror_count"],
                jury_status=row["jury_status"],
                candidate_count=row["candidate_count"],
                docked_count=row["docked_count"],
                created_at=row["created_at"],
                archived_at=row["archived_at"],
            )
            for row in rows
        ]

    def set_build_state(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        stage: BuildStage | None,
        error: str | None,
    ) -> None:
        with self.connection() as conn:
            self._update_one(
                conn,
                "update experiments set status = %s, stage = %s, error = %s where id = %s",
                (status, stage, error, experiment_id),
            )

    def save_build_result(
        self,
        experiment_id: UUID,
        targets: list[DiseaseTarget],
        network: NetworkGraph | None,
        candidates: list[Candidate],
    ) -> None:
        with self.connection() as conn:
            self._update_one(
                conn,
                "update experiments set network = %s where id = %s",
                (_json(network and network.model_dump(mode="json")), experiment_id),
            )
            # A rerun after an interrupted build replaces what it left. Votes and
            # docking jobs only exist once the Experiment is ready, so nothing
            # refers to these rows yet.
            conn.execute("delete from candidates where experiment_id = %s", (experiment_id,))
            conn.execute(
                "delete from experiment_targets where experiment_id = %s", (experiment_id,)
            )
            self._write_targets_and_candidates(conn, experiment_id, targets, candidates)

    def set_archived_at(self, experiment_id: UUID, archived_at: datetime | None) -> None:
        with self.connection() as conn:
            try:
                self._update_one(
                    conn,
                    "update experiments set archived_at = %s where id = %s",
                    (archived_at, experiment_id),
                )
            except errors.CheckViolation as exc:
                raise (_refusal(exc) or exc) from exc

    def _write_targets_and_candidates(
        self,
        conn: Conn,
        experiment_id: UUID,
        targets: list[DiseaseTarget],
        candidates: list[Candidate],
    ) -> None:
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into experiment_targets (
                  experiment_id, target_id, symbol, name, rank, evidence_only_score,
                  retained, excluded_reason
                ) values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        experiment_id,
                        t.target_id,
                        t.symbol,
                        t.name,
                        t.rank,
                        t.evidence_only_score,
                        t.retained,
                        t.excluded_reason,
                    )
                    for t in targets
                ],
            )
            cur.executemany(
                """
                insert into candidates (
                  experiment_id, candidate_id, name, status, selected_by, network,
                  unscorable_reason, direct_evidence_rank, dockable, payload
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        experiment_id,
                        c.candidate_id,
                        c.name,
                        c.status,
                        list(c.selected_by),
                        _json(c.network and c.network.model_dump(mode="json")),
                        c.unscorable_reason,
                        c.direct_evidence_rank,
                        c.dockable,
                        Jsonb(c.model_dump(mode="json")),
                    )
                    for c in candidates
                ],
            )

    # Model jury -------------------------------------------------------------

    def add_jury_run(self, experiment_id: UUID, run: JuryRun) -> None:
        models = [model.model_dump(mode="json") for model in run.models]
        with self.connection() as conn:
            try:
                with conn.transaction():
                    conn.execute(
                        """
                        insert into jury_runs (
                          experiment_id, status, config, consensus, agreement, contested,
                          error, created_at, started_at, finished_at
                        ) values (
                          %s, %s,
                          (select jury_config from experiments where id = %s)
                            || jsonb_build_object('models', %s::jsonb),
                          %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            experiment_id,
                            run.status,
                            experiment_id,
                            Jsonb(models),
                            _json(run.consensus and run.consensus.model_dump(mode="json")),
                            run.agreement,
                            list(run.contested),
                            run.error,
                            run.created_at,
                            run.started_at,
                            run.finished_at,
                        ),
                    )
            except errors.UniqueViolation as exc:
                raise AlreadyExists(f"jury run for Experiment {experiment_id}") from exc
            self._write_jurors_and_votes(conn, experiment_id, run)

    def update_jury_run(self, experiment_id: UUID, run: JuryRun) -> None:
        with self.connection() as conn:
            self._update_one(
                conn,
                """
                update jury_runs set status = %s, consensus = %s, agreement = %s,
                  contested = %s, error = %s, started_at = %s, finished_at = %s
                where experiment_id = %s
                """,
                (
                    run.status,
                    _json(run.consensus and run.consensus.model_dump(mode="json")),
                    run.agreement,
                    list(run.contested),
                    run.error,
                    run.started_at,
                    run.finished_at,
                    experiment_id,
                ),
            )
            self._write_jurors_and_votes(conn, experiment_id, run)

    def _write_jurors_and_votes(self, conn: Conn, experiment_id: UUID, run: JuryRun) -> None:
        with conn.cursor() as cur:
            # Votes are rewritten whole (at most 15 per juror): a rerun starts again.
            cur.execute("delete from jury_votes where experiment_id = %s", (experiment_id,))
            cur.executemany(
                """
                insert into jurors (
                  experiment_id, model_id, status, attempts, latency_ms, validation, token_usage
                ) values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (experiment_id, model_id) do update set
                  status = excluded.status,
                  attempts = excluded.attempts,
                  latency_ms = excluded.latency_ms,
                  validation = jurors.validation || excluded.validation,
                  token_usage = excluded.token_usage
                """,
                [
                    (
                        experiment_id,
                        juror.model_id,
                        juror.status,
                        juror.attempts,
                        juror.latency_ms,
                        Jsonb({"errors": juror.errors}),
                        Jsonb([usage.model_dump(mode="json") for usage in juror.token_usage]),
                    )
                    for juror in run.jurors
                ],
            )
            cur.executemany(
                """
                insert into jury_votes (
                  experiment_id, model_id, candidate_id, rank, decision, direction,
                  rationale, objection, missing_evidence, supporting_evidence_ids,
                  contradicting_evidence_ids, safety
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        experiment_id,
                        vote.model_id,
                        vote.candidate_id,
                        vote.rank,
                        vote.decision,
                        vote.direction,
                        vote.rationale,
                        vote.objection,
                        list(vote.missing_evidence),
                        list(vote.supporting_evidence_ids),
                        list(vote.contradicting_evidence_ids),
                        Jsonb(vote.safety.model_dump(mode="json")),
                    )
                    for vote in run.votes
                ],
            )

    def _read_jury(self, conn: Conn, experiment_id: UUID) -> JuryRun | None:
        run = conn.execute(
            """
            select status, config, consensus, agreement, contested, error, created_at,
                   started_at, finished_at
            from jury_runs where experiment_id = %s
            """,
            (experiment_id,),
        ).fetchone()
        if run is None:
            return None
        models = [JuryModel.model_validate(m) for m in run["config"]["models"]]
        order = {model.id: i for i, model in enumerate(models)}
        jurors = conn.execute(
            """
            select model_id, status, attempts, latency_ms,
                   coalesce(validation -> 'errors', '[]'::jsonb) as errors, token_usage
            from jurors where experiment_id = %s
            """,
            (experiment_id,),
        ).fetchall()
        votes = conn.execute(
            """
            select model_id, candidate_id, rank, decision, direction, rationale, objection,
                   missing_evidence, supporting_evidence_ids, contradicting_evidence_ids, safety
            from jury_votes where experiment_id = %s
            """,
            (experiment_id,),
        ).fetchall()
        return JuryRun.model_validate(
            {
                "status": run["status"],
                "models": models,
                "jurors": sorted(jurors, key=lambda j: order.get(j["model_id"], len(order))),
                "votes": sorted(
                    (JuryVote.model_validate(v) for v in votes),
                    key=lambda v: (order.get(v.model_id, len(order)), v.rank),
                ),
                "consensus": run["consensus"],
                "agreement": run["agreement"],
                "contested": run["contested"],
                "error": run["error"],
                "created_at": run["created_at"],
                "started_at": run["started_at"],
                "finished_at": run["finished_at"],
            }
        )

    # Docking ----------------------------------------------------------------

    def add_dock_job(self, job: DockJob, inputs: DockInputs) -> None:
        with self.connection() as conn:
            try:
                # A savepoint: the caller's transaction survives a duplicate and can
                # reuse the job that won.
                with conn.transaction():
                    conn.execute(
                        """
                        insert into dock_jobs (
                          id, kind, status, experiment_id, candidate_id, target_id,
                          structure_id, ligand_smiles, settings, cache_key, scores, files,
                          control_rmsd, error, cached_from, fixture, created_at, started_at,
                          finished_at
                        ) values (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s
                        )
                        """,
                        (
                            job.id,
                            job.kind,
                            job.status,
                            job.experiment_id,
                            job.candidate_id,
                            job.target_id,
                            job.structure_id,
                            inputs.ligand_smiles,
                            Jsonb(job.settings.model_dump(mode="json")),
                            inputs.cache_key,
                            _json(job.scores and [s.model_dump(mode="json") for s in job.scores]),
                            _json(job.files and job.files.model_dump(mode="json")),
                            job.control_rmsd,
                            job.error,
                            job.cached_from,
                            job.fixture,
                            job.created_at,
                            job.started_at,
                            job.finished_at,
                        ),
                    )
            except errors.UniqueViolation as exc:
                if exc.diag.constraint_name == "dock_jobs_cache_key_live_idx":
                    raise DuplicateComputation(
                        f"a live docking job computes {inputs.cache_key}"
                    ) from exc
                raise AlreadyExists(f"docking job {job.id}") from exc
            except errors.CheckViolation as exc:
                raise (_refusal(exc) or exc) from exc

    def get_dock_job(self, job_id: UUID) -> DockJob | None:
        with self.connection() as conn:
            row = conn.execute(
                f"select {_DOCK_COLUMNS} from dock_jobs where id = %s", (job_id,)
            ).fetchone()
        return None if row is None else DockJob.model_validate(row)

    def dock_inputs(self, job_id: UUID) -> DockInputs | None:
        with self.connection() as conn:
            row = conn.execute(
                "select cache_key, ligand_smiles from dock_jobs where id = %s", (job_id,)
            ).fetchone()
        return None if row is None else DockInputs(row["cache_key"], row["ligand_smiles"])

    def update_dock_job(self, job: DockJob) -> None:
        with self.connection() as conn:
            self._update_one(
                conn,
                """
                update dock_jobs set status = %s, scores = %s, files = %s, control_rmsd = %s,
                  error = %s, fixture = %s, started_at = %s, finished_at = %s
                where id = %s
                """,
                (
                    job.status,
                    _json(job.scores and [s.model_dump(mode="json") for s in job.scores]),
                    _json(job.files and job.files.model_dump(mode="json")),
                    job.control_rmsd,
                    job.error,
                    job.fixture,
                    job.started_at,
                    job.finished_at,
                    job.id,
                ),
            )

    def save_dock_files(self, job_id: UUID, files: Mapping[str, bytes]) -> None:
        with self.connection() as conn:
            conn.execute("delete from dock_files where job_id = %s", (job_id,))
            with conn.cursor() as cursor:
                cursor.executemany(
                    "insert into dock_files (job_id, name, content) values (%s, %s, %s)",
                    [(job_id, name, content) for name, content in files.items()],
                )

    def dock_file(self, job_id: UUID, name: str) -> bytes | None:
        with self.connection() as conn:
            row = conn.execute(
                "select content from dock_files where job_id = %s and name = %s",
                (job_id, name),
            ).fetchone()
        return None if row is None else bytes(row["content"])

    def find_reusable_dock_job(self, cache_key: str, fixture: bool) -> DockJob | None:
        with self.connection() as conn:
            row = conn.execute(
                f"""
                select {_DOCK_COLUMNS} from dock_jobs
                where cache_key = %s and fixture = %s
                  and cached_from is null and status <> 'failed'
                """,
                (cache_key, fixture),
            ).fetchone()
        return None if row is None else DockJob.model_validate(row)

    def list_dock_jobs_cached_from(self, job_id: UUID) -> list[DockJob]:
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                select {_DOCK_COLUMNS} from dock_jobs where cached_from = %s
                order by created_at, id
                """,
                (job_id,),
            ).fetchall()
        return [DockJob.model_validate(row) for row in rows]

    # Helpers ----------------------------------------------------------------

    @staticmethod
    def _update_one(conn: Conn, query: LiteralString, params: tuple[Any, ...]) -> None:
        if conn.execute(query, params).rowcount != 1:
            raise KeyError(f"no row to update for {params[-1]}")
