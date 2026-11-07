-- Initial schema for saved Experiments, the Model jury, docking jobs,
-- evaluation results and the source response cache (plan.md section 9.3).
--
-- IDs follow plan.md section 3: one ID per kind of thing, checked here so a
-- wrong ID fails on insert instead of joining silently. Names and symbols are
-- display text only. Large files (graph arrays, Parquet, pose files) stay in
-- file storage; these tables keep only their paths and checksums.
--
-- Apply with: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f db/migrations/0001_initial.sql

create table experiments (
  id               uuid primary key default gen_random_uuid(),
  disease_id       text not null check (disease_id ~ '^[A-Za-z]+_[A-Za-z0-9]+$'),
  disease_name     text not null,
  -- Pinned data releases, e.g. {opentargets-26.09, chembl-37, string-12.5}.
  data_releases    text[] not null check (cardinality(data_releases) > 0),
  -- Fixed Model jury configuration: models, prompt_version, temperature,
  -- max_attempts, shuffle_seed. One configuration per Experiment.
  jury_config      jsonb not null,
  ranking_settings jsonb not null,
  -- The blinded packet the jurors received, kept for traceability. Null until
  -- the jury has been asked.
  jury_packet      jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  -- Archive instead of delete. Null means active.
  archived_at      timestamptz
);

create index experiments_history_idx on experiments (archived_at, created_at desc);

create table candidates (
  experiment_id        uuid not null references experiments (id) on delete cascade,
  candidate_id         text not null check (candidate_id ~ '^CHEMBL[0-9]+$'),
  name                 text not null,
  -- distance_only: zero null spread, so degree_matched_z is null (plan.md 4.3).
  status               text not null check (status in ('scored', 'distance_only', 'not_scorable')),
  selected_by          text[] not null
                         check (cardinality(selected_by) > 0
                                and selected_by <@ array['network', 'evidence']),
  -- {rank, mean_distance, degree_matched_z, graph_version, warning}; null when
  -- not scorable.
  network              jsonb,
  unscorable_reason    text,
  direct_evidence_rank integer check (direct_evidence_rank > 0),
  dockable             boolean not null default false,
  -- The complete Candidate object (plan.md section 9.2): Targets, evidence
  -- items, warnings, safety status. The columns above are copies for querying.
  payload              jsonb not null,
  primary key (experiment_id, candidate_id),
  check (
    (status in ('scored', 'distance_only') and network is not null and unscorable_reason is null)
    or (status = 'not_scorable' and network is null and unscorable_reason is not null)
  )
);

-- One row per juror call. A juror that fails or returns invalid output still
-- gets a row, so failures stay visible and no vote is invented for it.
create table jurors (
  experiment_id   uuid not null references experiments (id) on delete cascade,
  model_id        text not null,
  status          text not null check (status in ('valid', 'invalid', 'failed')),
  attempts        integer not null check (attempts > 0),
  latency_ms      integer check (latency_ms >= 0),
  -- Packet labels in the shuffled order this juror saw, e.g. {C3, C1, C4, C2}.
  presented_order text[] not null,
  -- {schema, unique_ranks, evidence_ids_exist, numbers_match, errors: [...]}
  validation      jsonb not null,
  raw_output      text,
  created_at      timestamptz not null default now(),
  primary key (experiment_id, model_id)
);

-- One row per review from a valid juror.
create table jury_votes (
  experiment_id              uuid not null,
  model_id                   text not null,
  candidate_id               text not null,
  -- Packet-local label the juror used; mapped back to candidate_id after the vote.
  label                      text not null check (label ~ '^C[0-9]+$'),
  rank                       integer not null check (rank > 0),
  decision                   text not null check (decision in ('investigate', 'watch', 'deprioritise')),
  direction                  text not null check (direction in ('supported', 'contradicted', 'unknown')),
  rationale                  text not null,
  objection                  text not null,
  missing_evidence           text[] not null default '{}',
  supporting_evidence_ids    text[] not null default '{}',
  contradicting_evidence_ids text[] not null default '{}',
  -- {status: warnings_recorded | unknown, evidence_ids: [...]}
  safety                     jsonb not null,
  primary key (experiment_id, model_id, candidate_id),
  unique (experiment_id, model_id, rank),
  unique (experiment_id, model_id, label),
  foreign key (experiment_id, model_id) references jurors (experiment_id, model_id) on delete cascade,
  foreign key (experiment_id, candidate_id) references candidates (experiment_id, candidate_id) on delete cascade
);

-- Docking queue and results (docs/build-reference.md steps C6 and C7). The
-- worker claims jobs with FOR UPDATE SKIP LOCKED; no message broker.
create table dock_jobs (
  id              uuid primary key default gen_random_uuid(),
  kind            text not null default 'candidate'
                    check (kind in ('candidate', 'redock_control', 'negative_control')),
  -- Controls belong to a prepared structure, not to an Experiment.
  experiment_id   uuid references experiments (id) on delete cascade,
  candidate_id    text not null check (candidate_id ~ '^CHEMBL[0-9]+$'),
  target_id       text not null check (target_id ~ '^ENSG[0-9]{11}$'),
  structure_id    text not null check (structure_id ~ '^[0-9][A-Z0-9]{3}_[A-Za-z0-9]+$'),
  ligand_smiles   text not null,
  -- box_center, box_size, engine, engine_version, exhaustiveness, seed,
  -- plus the Meeko and RDKit versions shown in the UI.
  settings        jsonb not null,
  -- SHA-256 of (pdb_id, chain, canonical SMILES, box, engine, engine version,
  -- exhaustiveness, seed). A done job with the same key is reused.
  cache_key       text not null check (cache_key ~ '^[0-9a-f]{64}$'),
  -- Set when this row reuses an earlier job's result instead of running again.
  cached_from     uuid references dock_jobs (id),
  session_id      text,
  status          text not null default 'queued'
                    check (status in ('queued', 'running', 'done', 'failed')),
  -- Per-pose scores from scores.json. Not binding affinities.
  scores          jsonb,
  -- {name: {path, sha256}} for receptor.pdb, poses.sdf, scores.json, log.txt.
  files           jsonb,
  -- Measured redocking result; never pre-filled.
  control_rmsd    real check (control_rmsd >= 0),
  posebusters     jsonb,
  -- Last lines of stderr on failure or timeout.
  error           text,
  created_at      timestamptz not null default now(),
  started_at      timestamptz,
  finished_at     timestamptz,
  check ((kind = 'candidate') = (experiment_id is not null)),
  check (status <> 'failed' or error is not null),
  foreign key (experiment_id, candidate_id) references candidates (experiment_id, candidate_id) on delete cascade
);

create index dock_jobs_queue_idx on dock_jobs (created_at) where status = 'queued';
create index dock_jobs_cache_idx on dock_jobs (cache_key) where status = 'done' and cached_from is null;
create index dock_jobs_experiment_idx on dock_jobs (experiment_id, created_at desc);

create table evaluation_results (
  id                   bigint generated always as identity primary key,
  manifest_hash        text not null,
  experiment           text not null check (experiment in ('retrieval', 'reranking')),
  method               text not null,
  data_releases        text[] not null check (cardinality(data_releases) > 0),
  metrics              jsonb not null,
  coverage             jsonb not null,
  confidence_intervals jsonb,
  created_at           timestamptz not null default now(),
  unique (manifest_hash, experiment, method)
);

-- Versioned source responses, so demos survive upstream outages.
create table evidence_cache (
  source       text not null,
  -- source-version, e.g. opentargets-26.09.
  release      text not null check (release ~ '^[a-z]+-[0-9][0-9.]*$'),
  -- SHA-256 of the normalised request.
  request_key  text not null check (request_key ~ '^[0-9a-f]{64}$'),
  request      jsonb not null,
  response     jsonb not null,
  retrieved_at timestamptz not null default now(),
  primary key (source, release, request_key)
);
