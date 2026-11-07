-- How an Experiment's Candidates were ranked (api schemas.py `RankingMethod`).
--
-- network: by network proximity, with the direct-evidence ranking alongside.
-- evidence_only: no network was available (plan.md section 4.4, "Evidence ranking
-- - network unavailable"): Candidates are ranked by direct Target evidence alone,
-- `network` is null and every Candidate is not_scorable with unscorable_reason
-- network_unavailable. Rows saved before this migration were all network fixtures.
--
-- Apply with db/migrate.py.

alter table experiments
  add column ranking_method text not null default 'network'
    check (ranking_method in ('network', 'evidence_only'));

-- New rows must state it, like status (0002).
alter table experiments alter column ranking_method drop default;
