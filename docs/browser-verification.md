# WS6/WS10 — browser verification of the top candidates

For each of the top 10 ranked candidates, an agent opens a PubMed search and a
ClinicalTrials.gov search **in a real browser** and answers three questions from the page:
was the scaffold tested, what was the outcome, and why did it fail. Every answer carries the
URL and the exact text on that page that supports it. A question the page does not answer is
recorded as `no record found` and is never filled in from anywhere else.

```
evidence/session.py   the browser, the allowlist, record/replay, the per-step figures
evidence/extract.py   the prompt, strict parsing, the quote check, no-record handling
evidence/run.py       the loop over candidates and sources, the record, the CLI
```

## What was actually run, and what was not

Stated plainly, because the Done-when for this task is partly about a live run.

| Part | Status |
| --- | --- |
| Real Chromium driving real pages | **run** — 51 tests drive an actual browser |
| The allowlist, in the route handler | **run** — off-allowlist requests are aborted |
| Offline replay through the same code path | **run** — a recorded cache replays end to end |
| A cache miss being an error, not a blank | **run** |
| Per-step token, model and time figures | **run** — `StepLog.render()` |
| Quote-must-be-on-the-page gate | **run** — an invented quote is dropped |
| Injected instructions in page content | **run** — against a planted page |
| Navigating **live** PubMed / ClinicalTrials.gov | **not run** — both are blocked from my sandbox (`net::ERR_TUNNEL_CONNECTION_FAILED`) |
| A **live** model call | **not run** — tests use a stub and a recorded transcript |
| `browser-use` as the agent framework | **not used** — not installed and I could not install it; this drives Playwright directly |

So the harness is complete and tested; the one recorded run that produces `record.md` has to
be made on a machine that can reach the two sites. That is `--mode record`, below.

## Running it

```bash
# 1. record: live browser, live model, writes the page cache and the model transcript
uv run python -m evidence.run --result results/phase2/antibiotic_candidates.json \
    --mode record --cache data/evidence/run1 --out results/ws6_evidence

# 2. replay: same browser, same code path, no network at all
uv run python -m evidence.run --result results/phase2/antibiotic_candidates.json \
    --mode replay --cache data/evidence/run1 --out results/ws6_evidence
```

The CLI only replays, because `record` needs a model and the CLI will not guess which one.
Wire one in with a callable — the same shape as the jury's `model_call`:

```python
from evidence.run import Reply, Recorder, run

def my_model(prompt, *, key):
    out = client.chat(model="...", messages=[{"role": "user", "content": prompt}])
    return Reply(out.text, out.model, out.usage.prompt_tokens, out.usage.completion_tokens)

recorder = Recorder(my_model)
record = run(candidates, "data/evidence/run1", recorder, mode="record")
Path("data/evidence/run1/transcript.json").write_text(json.dumps(recorder.transcript()))
```

`Recorder` keeps every reply so the replay in step 2 reproduces the run exactly. Replay with
no transcript is an error, not an empty answer.

## Why this is genuine browser use

Playwright launches Chromium, navigates, and the page is parsed by the browser —
`page.inner_text("body")`, which is what a reader sees, not an API response. Replay does not
take a shortcut around the browser either: recorded response bodies are served through
Playwright's own `route.fulfill`, so the offline demo runs the same navigation, the same
rendering and the same extraction as the live run. An offline path that merely read JSON off
disk would demonstrate nothing about the live one.

## Why page content cannot change what the agent does

Four structural defences. None of them is "the model noticed".

1. **The allowlist is in the route handler.** `ALLOWED` is two hosts. Every request Chromium
   makes — navigation, redirect, subresource, a link an injected instruction asks it to
   follow — passes `Session._route` and is aborted if the host is not on the list. A page
   cannot walk the agent anywhere, because the block is not a decision the model gets to make.
2. **Page content is a delimited data block.** The prompt puts it between
   `----- BEGIN PAGE CONTENT <nonce> -----` markers with a fresh per-request nonce, and names
   it as data from an untrusted website that cannot change the rules. The nonce means the page
   cannot close the block and write outside it.
3. **The reply is parsed strictly.** `parse_reply` requires JSON, requires the question to be
   one of the three, and **discards every field it does not expect**, so a reply cannot
   smuggle a field the rest of the pipeline might read. An unparseable reply is recorded as
   unusable; it never becomes a claim.
4. **Every claim must quote the page.** `accept` checks that the quote occurs verbatim in the
   page's visible text (whitespace normalised, nothing else). This is the load-bearing one:
   the worst a successful injection can do is propose a claim, and a proposed claim still has
   to be supported by text that is actually on the page. A dropped claim is recorded with its
   reason rather than vanishing.

`find_injections` additionally *records* recognised injection phrasings in the run log. That
is observability only. A pattern list always misses something, so nothing depends on it —
which is why the injection test asserts that a planted claim is rejected by the quote check,
not that the pattern matched.

## Why `no record found` is a result

A search that returns nothing produces `answer: "no record found"`, the search URL, and no
quote. `fill_unanswered` then adds that row for every question the page did not answer, so
the output has a row per question per source and a missing answer is an explicit negative.

Three things could have turned a missing answer into an invented one, and each is an error
instead:

- a cache miss in replay — `route.abort()`, then `SessionError`, counted in `errors`
- a model call that fails — `ModelError`, counted in `errors`, no substituted answer
- a recorded transcript with no reply for a candidate — `ModelError`

The counts in `record.json` separate these: `with_citation`, `no_record_found`, `rejected`
and `errors` are four different numbers. "No record found" means the page was read and said
nothing. It never means the page could not be read.

## The on-screen figures

`StepLog` records action, URL, model, prompt and completion tokens, and elapsed seconds for
every step, and `render()` prints the table into the terminal and into `record.md`:

```
  #  action                 model                      tok       s  url
  1  open                   -                            0    0.41  https://pubmed.ncbi.nlm.nih.gov/?term=LI
  2  model                  claude-...                1050    1.96  https://pubmed.ncbi.nlm.nih.gov/?term=LI
  ...
8 steps, 4200 tokens, 9.14s, models: claude-...
```

## Tests

```bash
uv run pytest tests/test_evidence_extract.py tests/test_evidence_session.py -q
```

51 tests. The ones worth reading, because they are the claims above:

| Test | What it pins down |
| --- | --- |
| `test_an_invented_quote_is_rejected` | A fabricated citation is dropped |
| `test_an_injected_claim_still_has_to_quote_the_page` | Injection gets no further than the quote check |
| `test_a_link_in_page_content_cannot_walk_the_agent_off_the_allowlist` | The block is in the route handler |
| `test_the_prompt_puts_page_content_in_a_delimited_data_block` | Nonce-delimited untrusted data |
| `test_unknown_fields_in_a_reply_are_discarded` | No smuggled fields |
| `test_replay_serves_the_recorded_page_through_the_real_browser` | Offline, same code path |
| `test_a_cache_miss_in_replay_is_an_error_not_an_empty_page` | A missing recording is not a result |
| `test_a_candidate_with_no_recorded_pages_is_an_error_not_a_blank` | Errors are not `no record found` |
| `test_the_recorded_model_replays_and_refuses_a_miss` | Replay cannot invent a reply |
| `test_the_step_table_shows_action_model_tokens_and_time` | The required figures |

`tests/test_evidence_session.py` skips cleanly if Playwright is missing; it does not pass
vacuously, because it drives a real browser when it is there.

## Known gaps

- **No recorded run is committed.** `data/evidence/run1/` and `results/ws6_evidence/` are
  produced by step 1 on a machine with network access. Nothing in this branch claims a
  result, for the same reason as the WS5 protocol: a shipped `record.md` I could not produce
  live would be fiction.
- **PubMed's and ClinicalTrials.gov's real markup is unverified.** The extraction reads
  `inner_text("body")`, which is markup-agnostic, but the first live run is the first time the
  prompt meets a real results page. Expect to adjust the question wording, not the defences.
- **Rate limits.** Ten candidates × two sources is 20 page loads. PubMed tolerates that at a
  human pace; add a delay in `verify_candidate` if a live run gets throttled.
- **`browser-use` is not used.** If the sponsor requirement is specifically that framework,
  `Session` is the only file that would change: `open()` and `_route` are the whole surface.
