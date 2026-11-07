-- A docking job's result files, so every API instance can serve them. Serverless
-- instances share no disk: the instance that ran a job saves its files here, and
-- any other instance reads them back. Files of a job reusing another's result
-- (cached_from) are read from that job.
create table dock_files (
  job_id uuid not null references dock_jobs (id) on delete cascade,
  name text not null
    check (name in ('receptor.pdb', 'poses.sdf', 'crystal_ligand.sdf', 'scores.json', 'log.txt')),
  content bytea not null,
  primary key (job_id, name)
);
