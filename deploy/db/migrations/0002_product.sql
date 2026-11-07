-- Product layer on top of 0001: Experiment build state, the Disease's own
-- Targets, Model jury run state, a background job queue, and archive-only
-- history.
--
-- Apply with db/migrate.py, which records each file in schema_migrations.

-- ---------------------------------------------------------------------------
-- Experiment build state. An Experiment row exists from the moment it is
-- requested, so the UI can poll its progress; history lists only ready ones.
-- ---------------------------------------------------------------------------
alter table experiments
  add column status    text not null default 'ready'
                         check (status in ('queued', 'building', 'ready', 'failed')),
  -- Current build stage while building, e.g. targets, ranking, evidence, saving.
  add column stage     text,
  add column error     text,
  -- Files kept outside the database: {name: {path, sha256}}, e.g. the full
  -- ranking output that the API reduces to the shortlist.
  add column artifacts jsonb not null default '{}'::jsonb,
  -- The small network subgraph the UI draws: {nodes: [...], edges: [...]},
  -- routes from Candidate Targets to the Disease's Targets. Null until built.
  add column network   jsonb,
  add constraint experiments_failed_has_error check (status <> 'failed' or error is not null);

-- Rows that existed before this migration are finished Experiments; new rows
-- must state their status.
alter table experiments alter column status drop default;

create index experiments_ready_history_idx on experiments (created_at desc)
  where status = 'ready' and archived_at is null;

create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger experiments_set_updated_at
  before update on experiments
  for each row execute function set_updated_at();

-- Archive instead of delete (plan.md section 2).
create or replace function forbid_experiment_delete() returns trigger
language plpgsql as $$
begin
  raise exception 'Experiments are archived, never deleted (experiment %)', old.id
    using errcode = 'restrict_violation';
end;
$$;

create trigger experiments_forbid_delete
  before delete on experiments
  for each row execute function forbid_experiment_delete();

-- ---------------------------------------------------------------------------
-- The Disease's own Targets (plan.md section 4.3, step 2). 0001 stored Targets
-- only inside each Candidate's payload.
-- ---------------------------------------------------------------------------
create table experiment_targets (
  experiment_id       uuid not null references experiments (id) on delete restrict,
  target_id           text not null check (target_id ~ '^ENSG[0-9]{11}$'),
  -- Gene symbol shown in the UI, e.g. ACE2; name is the full protein name.
  symbol              text not null,
  name                text not null,
  rank                integer not null check (rank > 0),
  evidence_only_score real not null check (evidence_only_score >= 0 and evidence_only_score <= 1),
  -- Mapped into the protein network and kept for scoring.
  retained            boolean not null,
  -- Why a selected Target was left out of the network, e.g. no STRING protein.
  excluded_reason     text,
  primary key (experiment_id, target_id),
  unique (experiment_id, rank),
  check (retained = (excluded_reason is null))
);

-- ---------------------------------------------------------------------------
-- One Model jury run per Experiment. Jurors and votes (0001) hang off it.
-- ---------------------------------------------------------------------------
create table jury_runs (
  experiment_id uuid primary key references experiments (id) on delete restrict,
  status        text not null check (status in ('queued', 'running', 'done', 'failed')),
  -- Copy of experiments.jury_config at the time of the run.
  config        jsonb not null,
  -- {method, jurors_counted, ranking: [{label, candidate_id, borda_points, rank}]}
  consensus     jsonb,
  -- Agreement between jurors (Kendall's W). Consistency, not a chance of success.
  agreement     real check (agreement >= 0 and agreement <= 1),
  contested     text[] not null default '{}',
  error         text,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  finished_at   timestamptz,
  check (status <> 'failed' or error is not null),
  check (status <> 'done' or consensus is not null)
);

-- ---------------------------------------------------------------------------
-- Background jobs for slow work (building an Experiment, running the jury).
-- Workers claim with FOR UPDATE SKIP LOCKED, as dock_jobs does.
-- ---------------------------------------------------------------------------
create table jobs (
  id            uuid primary key default gen_random_uuid(),
  kind          text not null check (kind in ('experiment_build', 'jury_run')),
  experiment_id uuid not null references experiments (id) on delete restrict,
  status        text not null default 'queued'
                  check (status in ('queued', 'running', 'done', 'failed')),
  -- e.g. {stage: "ranking"} or {jurors_done: 1, jurors_total: 3}
  progress      jsonb not null default '{}'::jsonb,
  attempts      integer not null default 0 check (attempts >= 0),
  -- Updated by the running worker; a stale heartbeat means the worker died.
  heartbeat_at  timestamptz,
  error         text,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  finished_at   timestamptz,
  check (status <> 'failed' or error is not null),
  check (status <> 'running' or (started_at is not null and heartbeat_at is not null))
);

create index jobs_queue_idx on jobs (created_at) where status = 'queued';
-- At most one live job of each kind per Experiment.
create unique index jobs_one_live_per_kind_idx on jobs (experiment_id, kind)
  where status in ('queued', 'running');

-- ---------------------------------------------------------------------------
-- Docking: one live computation per cache key. A second identical request
-- while one is queued, running or done reuses it (cached_from rows are free).
-- ---------------------------------------------------------------------------
drop index dock_jobs_cache_idx;
create unique index dock_jobs_cache_key_live_idx on dock_jobs (cache_key)
  where cached_from is null and status <> 'failed';

-- ---------------------------------------------------------------------------
-- Archive, never delete: child rows block deletion instead of disappearing.
-- ---------------------------------------------------------------------------
alter table candidates
  drop constraint candidates_experiment_id_fkey,
  add constraint candidates_experiment_id_fkey
    foreign key (experiment_id) references experiments (id) on delete restrict;

alter table jurors
  drop constraint jurors_experiment_id_fkey,
  add constraint jurors_experiment_id_fkey
    foreign key (experiment_id) references experiments (id) on delete restrict;

alter table jury_votes
  drop constraint jury_votes_experiment_id_model_id_fkey,
  add constraint jury_votes_experiment_id_model_id_fkey
    foreign key (experiment_id, model_id) references jurors (experiment_id, model_id) on delete restrict,
  drop constraint jury_votes_experiment_id_candidate_id_fkey,
  add constraint jury_votes_experiment_id_candidate_id_fkey
    foreign key (experiment_id, candidate_id) references candidates (experiment_id, candidate_id) on delete restrict;

alter table dock_jobs
  drop constraint dock_jobs_experiment_id_fkey,
  add constraint dock_jobs_experiment_id_fkey
    foreign key (experiment_id) references experiments (id) on delete restrict,
  drop constraint dock_jobs_experiment_id_candidate_id_fkey,
  add constraint dock_jobs_experiment_id_candidate_id_fkey
    foreign key (experiment_id, candidate_id) references candidates (experiment_id, candidate_id) on delete restrict;
