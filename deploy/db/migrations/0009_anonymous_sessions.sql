-- Existing Experiments have no recoverable browser owner. Keep them for internal
-- research, but never expose them to a newly issued anonymous browser session.
alter table experiments add column owner_session text
  check (owner_session is null or owner_session ~ '^[0-9a-f]{64}$');
create index experiments_owner_history on experiments (owner_session, created_at desc);

-- Shared across API and worker processes, including restarts. One row per key;
-- expired rows are removed when a quota is consumed.
create table request_quotas (
  key text primary key,
  expires_at bigint not null,
  used integer not null check (used > 0)
);
create index request_quotas_expiry on request_quotas (expires_at);
