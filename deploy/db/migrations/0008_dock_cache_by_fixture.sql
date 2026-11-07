-- Keep made-up docking results apart from real ones (api repo
-- `find_reusable_dock_job(cache_key, fixture)`).
--
-- A database used once in fixture mode keeps that mode's precomputed jobs, with
-- made-up scores and result files that exist only in api/oxhack_api/fixtures. A
-- live (Vina) server computing the same inputs got the same cache key, so it
-- reused the made-up job, showed its scores and then failed to load its files.
-- One live computation per cache key now holds per kind: a real job may compute a
-- cache key that a made-up job already holds. Apply with db/migrate.py.

drop index dock_jobs_cache_key_live_idx;
create unique index dock_jobs_cache_key_live_idx on dock_jobs (cache_key, fixture)
  where cached_from is null and status <> 'failed';
