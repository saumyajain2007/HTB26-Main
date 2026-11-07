-- What the API's Postgres repo (api/oxhack_api/repo/postgres.py) needs on top
-- of 0001 and 0002: fields of the API contract that had no column, juror
-- progress while a jury runs, a heartbeat for docking jobs, and the archive
-- rule enforced by the database as well as by the API.
--
-- Apply with db/migrate.py.

-- ---------------------------------------------------------------------------
-- Experiments: the note saying which values are made-up fixture data.
-- ---------------------------------------------------------------------------
alter table experiments
  add column fixture_note text;

-- ---------------------------------------------------------------------------
-- Jurors: one row per juror from the moment the jury is asked, so the UI can
-- follow progress (pending, then running, then valid, invalid or failed). A
-- juror that never got an answer stays visible as failed; no vote is invented
-- for it. Rows of finished jurors keep the 0001 meaning.
-- ---------------------------------------------------------------------------
alter table jurors
  drop constraint jurors_status_check,
  add constraint jurors_status_check
    check (status in ('pending', 'running', 'valid', 'invalid', 'failed')),
  drop constraint jurors_attempts_check,
  add constraint jurors_attempts_check check (attempts >= 0),
  -- A juror that replied was asked at least once. A failed one may never have
  -- been asked (the run failed before its turn).
  add constraint jurors_replied_after_asking
    check (status not in ('valid', 'invalid') or attempts > 0),
  alter column presented_order set default '{}',
  alter column validation set default '{}'::jsonb;

-- The packet label is known only to the live jury (phase 6); recorded fixture
-- reviews have none. Null means not recorded, never a made-up label.
alter table jury_votes
  alter column label drop not null;

-- ---------------------------------------------------------------------------
-- Docking jobs: whether the scores are made-up fixture data, and a heartbeat
-- so a job whose worker died is put back in the queue, as for jobs.
-- ---------------------------------------------------------------------------
alter table dock_jobs
  add column fixture       boolean not null default false,
  add column attempts      integer not null default 0 check (attempts >= 0),
  add column heartbeat_at  timestamptz;

create index dock_jobs_running_idx on dock_jobs (heartbeat_at) where status = 'running';
create index jobs_running_idx on jobs (heartbeat_at) where status = 'running';

-- ---------------------------------------------------------------------------
-- Archive is refused while the Experiment is building or a docking job for it
-- is queued or running, and a docking job is refused for an Experiment that is
-- archived or not ready. Both sides lock the Experiment row (the update takes
-- a row lock, the insert a share lock), so the two cannot race.
-- ---------------------------------------------------------------------------
create or replace function guard_experiment_archive() returns trigger
language plpgsql as $$
begin
  if new.status in ('queued', 'building') then
    raise exception 'This Experiment is still being built. Archive it once it is ready.'
      using errcode = 'check_violation', constraint = 'experiments_archive_guard';
  end if;
  if exists (
    select 1 from dock_jobs
    where experiment_id = new.id and status in ('queued', 'running')
  ) then
    raise exception 'A binding pose is still being computed for this Experiment. Archive it once the docking job has finished.'
      using errcode = 'check_violation', constraint = 'experiments_archive_guard';
  end if;
  return new;
end;
$$;

create trigger experiments_archive_guard
  before update of archived_at on experiments
  for each row
  when (old.archived_at is null and new.archived_at is not null)
  execute function guard_experiment_archive();

create or replace function guard_dock_job_experiment() returns trigger
language plpgsql as $$
declare
  experiment record;
begin
  if new.experiment_id is null then
    return new;
  end if;
  select status, archived_at into experiment
    from experiments where id = new.experiment_id
    for share;
  if experiment.archived_at is not null then
    raise exception 'This Experiment is archived. Restore it to compute a binding pose.'
      using errcode = 'check_violation', constraint = 'dock_jobs_experiment_active';
  end if;
  if experiment.status is distinct from 'ready' and experiment.status is not null then
    raise exception 'This Experiment is not ready, so a binding pose cannot be computed yet.'
      using errcode = 'check_violation', constraint = 'dock_jobs_experiment_active';
  end if;
  return new;
end;
$$;

create trigger dock_jobs_experiment_active
  before insert on dock_jobs
  for each row execute function guard_dock_job_experiment();
