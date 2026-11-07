-- Which drugs an evaluation result ranked (api schemas.py `EvaluationScope`).
--
-- full_eligible: every approved drug; one a method can't score counts as not found.
-- common_scorable: only the drugs every method can score.
-- Stream B's Stage 3 freezes both for each method, so a result is one row per
-- (manifest, experiment, method, scope). The table was empty before this migration;
-- any older row is a full_eligible result, the only scope there was.
--
-- Apply with db/migrate.py.

alter table evaluation_results
  add column scope text not null default 'full_eligible'
    check (scope in ('full_eligible', 'common_scorable'));

alter table evaluation_results alter column scope drop default;

alter table evaluation_results
  drop constraint evaluation_results_manifest_hash_experiment_method_key,
  add constraint evaluation_results_one_per_scope
    unique (manifest_hash, experiment, method, scope);
