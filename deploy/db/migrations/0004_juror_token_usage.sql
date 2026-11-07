-- Token usage per juror attempt, for cost reporting (stream A's jury output).
--
-- One entry per attempt: {"attempt": 1, "input_tokens": 3475, "output_tokens": 1977}.
-- Counts are null when the provider gave none (failed calls, missing usage, mock
-- replies), never estimated zeros, so a null anywhere means the full cost is
-- unknown. Sum every attempt for a juror's usage; no token prices are stored.
--
-- Each model's reasoning effort lives in experiments.jury_config, which is jsonb
-- already.
--
-- Apply with db/migrate.py.

alter table jurors
  add column token_usage jsonb not null default '[]'::jsonb,
  add constraint jurors_token_usage_is_array check (jsonb_typeof(token_usage) = 'array');
