-- Which network ranking filled an Experiment's network places (api schemas.py
-- `ShortlistMethod`, `RankingSettings.shortlist_method`, `CandidateNetwork.rwr`).
--
-- physical_rwr: stream B's random walk with restart on the physical network, the
-- application default; each placed Candidate's network result holds its walk rank
-- and mass under `rwr`, and the settings hold `restart_probability`.
-- zscore: the original closeness (degree-matched z-score) shortlist; `rwr` is null.
--
-- Every row saved before this migration used the z-score shortlist, or no network
-- at all (evidence_only, where shortlist_method is null). The keys live in jsonb,
-- so this only fills them in. Apply with db/migrate.py.

update experiments
   set ranking_settings = ranking_settings || jsonb_build_object(
         'shortlist_method', case when ranking_method = 'network' then 'zscore' end,
         'restart_probability', null)
 where not ranking_settings ? 'shortlist_method';

update candidates
   set network = network || '{"rwr": null}'::jsonb
 where network is not null and not network ? 'rwr';

update candidates
   set payload = jsonb_set(payload, '{network,rwr}', 'null'::jsonb)
 where jsonb_typeof(payload -> 'network') = 'object' and not payload -> 'network' ? 'rwr';
