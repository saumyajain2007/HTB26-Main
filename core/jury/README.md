# Model jury

Offline demonstration (all votes are explicitly labelled mock reviews):

```sh
.venv/bin/python -m jury tests/fixtures/evidence_packet.json --out /tmp/jury-mock.json --mock
```

Live use requires `SNOWFLAKE_ACCOUNT` (account identifier only), `SNOWFLAKE_PAT`,
and `SNOWFLAKE_MODELS` (a JSON array of three pinned IDs from distinct model
families, verified in your account). No live IDs are hardcoded. The mock IDs in
`config.json` cannot be used by the live CLI. `--config path.json` overrides the
remaining fixture-shaped settings. Availability, family diversity and cost must
be checked in the account before freezing an Experiment.

```sh
.venv/bin/python -m jury tests/fixtures/evidence_packet.json --out /tmp/jury-live.json
.venv/bin/python -m pytest core/jury/tests -q
.venv/bin/python -m pytest core/jury/tests -q -m network
```

Requests default to a 300-second timeout for slower jurors such as GLM.
Set `SNOWFLAKE_TIMEOUT_SECONDS` or pass `--timeout 420` to override it;
`CortexModel(timeout=420)` provides the same override for Python callers.
The timeout must be positive and finite. It does not add retries.
The CLI creates the output directory before making model calls.

`jury.client.run_jury(packet, config, model_call)` accepts a callable with
`(model, prompt, temperature)` arguments returning the raw reply string.
It also accepts `ModelReply(text, input_tokens, output_tokens)`, which is what
`CortexModel` returns so provider usage survives validation and retries.
`CortexModel` uses the OpenAI SDK as described in the
[Snowflake Cortex REST documentation](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-rest-api).
Retries reuse the same blinded prompt and order, with SDK retries disabled.
Every `claude-*` model uses `/api/v2/cortex/v1/messages`, with the bearer PAT,
`anthropic-version: 2023-06-01`, `max_tokens: max(4096, 1024 * Candidate count)`,
and the review schema in
`output_config.format`. Other models use `/api/v2/cortex/v1/chat/completions`
with `response_format: json_schema`. The same client transport handles both
endpoints; no Anthropic SDK dependency is needed.
Claude requests omit sampling parameters because Opus 5.5 rejects them;
the shared configuration's `temperature` is sent only to chat completions.
See the [Opus 5.5 migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide).
Snowflake documents schema
enforcement for OpenAI and Claude; other families (including GLM) ignore the
chat response format. Every response still passes the same local
schema, rank, citation, safety and exact-number checks. A Markdown fence or prose
around exactly one JSON object is accepted; competing objects, arrays, duplicate
keys, malformed JSON and non-finite JSON numbers are rejected.
Provider `stop_reason: refusal` is recorded as `refused` in per-attempt errors,
with all validation flags null (not checked). Its partial output is retained for
audit and never parsed or counted as a vote, even if it happens to be valid JSON.
The juror remains `invalid` unless a later bounded attempt validates; the status
enum is unchanged. Refusal retries reuse the original prompt and order, without
misleading JSON-error feedback. Stop reasons are recorded even when a custom
`ModelReply` omits a token cap.

Failed calls record exception types only, since exception text can expose secrets.
An invalid reply yields no reviews; its last raw reply and per-attempt errors are
retained. If any reply arrived but none validated, the juror is invalid; failed
means every attempt failed to return a reply. Successful replies have null raw output.

Each juror adds `token_usage` to the original fixture contract: one entry per
attempt, with `attempt`, `input_tokens` and `output_tokens`. Messages usage is
copied from the provider's input/output token counts; chat usage maps
`prompt_tokens`/`completion_tokens` to those names. Invalid replies retain their
counts too. Failed calls, missing usage and string-only mock/custom replies
record null counts, never estimated zeros. Sum all attempts for review usage;
null means the full cost inputs are unknown. No token prices are hardcoded.
The fixture includes the additive consensus failure metadata described below.

Prompt `jury-v2` makes qualitative comparisons explicit: a review must not
repeat another Candidate's measurements that its own citations cannot support.
`core/jury/tests/data/gpt_cross_candidate_vote.json` records a live reply rejected
for exactly that reason; the exact-number check is unchanged.

Only the fixture allowlist enters the evidence payload. `rank` appears solely
in output instructions; input ranks and identifiers remain hidden. Candidate IDs
are restored using exact packet labels after validation. Numeric literals are
checked using exact decimal equality against cited evidence `values`; protein
identifiers such as JAK1, Bcl-2 and E12 are excluded from numeric parsing. Hyphen
and nonbreaking-hyphen typography is normalized for packet identifiers only;
invented identifiers still have their numbers checked. Structural
checks do not establish biological truth; reasoning still needs manual audit.

For future runs, consensus uses **every valid juror, with at least two required**.
Borda points and Kendall's W use only those complete validated ballots. The
summary records `jurors_counted`, `failed_jurors` (model IDs for named jurors),
and `reason` (null when consensus exists). The result also keeps those three
fields in `consensus_status`, independently of the nullable `consensus`.
With fewer than two valid jurors, `run_jury` writes `consensus: null` and
`consensus_status.reason: "fewer_than_two_valid_jurors"`; no lone vote supplies
a ranking. A6 comparisons keep null Borda ranks/points and W in that case,
and record the count, excluded jurors and reason.
The internal `consensus()` summary helper retains an empty ranking and null W
below two jurors for frozen legacy callers. Those legacy callers may omit model
IDs and cannot supply failed identities; `run_jury` always supplies them.
Equal Borda totals share the higher rank, with labels in numerical order for
deterministic display. W is also null with fewer than two Candidates (zero
denominator). Each juror's
shuffle uses `shuffle_seed + its configuration index`; independent shuffles may
coincidentally match, particularly for small panels. Mock consensus has no
scientific meaning and must remain labelled when displayed.

`core/jury/tests/data/live_recording.json` preserves the supplied 2026-10-24 pilot's
retained replies and failure metadata without request headers or credentials.
Claude's retained reply is fenced JSON. GLM returned no reply before two
60-second SDK timeouts. GPT's failed first reply was not retained, so its exact
numeric failure cannot be reconstructed; tests replay its retained successful
ballot and explicitly vary Bcl-2 typography to cover the reproduced parser bug.
The GLM timeout test also replays its recovered live ballot (serialized from
validated reviews with the local `candidate_id` enrichment removed), simulating
its recorded 178.768-second latency without sleeping or calling Cortex.

Prompt `jury-v7` states that this is a retrospective evidence-review exercise on
public data, provides no advice for any patient, and ranks investigation
priorities rather than making recommendations. Only the opening framing changed;
all schema, rank, citation, safety and exact-number validators remain strict.
The bounded diagnostics still observed provider `bio` refusals on large saved
packets with this framing: **v7 is not a demonstrated refusal cure**. Details and
limits are in [the reliability notes](../../results/jury_reliability/notes.md).

This combining rule is a **design change for future runs only**. Published pilot,
A6, Experiment B and replication results and their frozen all-three scoring
policies have not been changed or rescored. The frozen experiment wrappers in
`jury/pilot.py` retain their original policies; future work must preregister the
new combining rule and use the shared jury runner. No new experiment was run.
