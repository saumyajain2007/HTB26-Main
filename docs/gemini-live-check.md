# Live Gemini check (8 November 2026)

What was actually run against Google's API, so the sponsor claim rests on a record
rather than on the client existing. Read with
[sponsor-mapping.md](sponsor-mapping.md), which this updates.

**Claim this:** one Gemini model answered the real antibiotic evidence packet through
the repository's own provider path, and its reply passed every reply validator.

**Do not claim:** a live three-model jury. The jury refuses a panel that is not three
distinct models from three families (`validate_config`), and only a Gemini key was
available, so no full jury has run live. Vultr and Cortex remain untried.

## What was run

`jury.resistance.build_resistance_packet` on the committed MRSA profile and candidate
result, then `jury.client.build_prompt`, then `jury.providers.ProviderModel` with
`gemini:gemini-3-flash-preview`, then `jury.client.validate_reply`. No step was
stubbed and no validator was relaxed.

| | |
|---|---|
| Model | `gemini-3-flash-preview` |
| Endpoint | `generativelanguage.googleapis.com/v1beta/openai/` (OpenAI-compatible) |
| Response format | JSON schema (`json_schema=True`, the production setting for Gemini) |
| Packet | 3 approved candidates, 17 evidence items |
| Latency | **97.5 s** |
| Validation | `schema ✓ unique_ranks ✓ evidence_ids_exist ✓ numbers_match ✓`, no errors |

### What it said

Blind to our ranking — the packet withholds the rank, the evasion status and the
explanation, and the labels are ordered by a hash:

| Its rank | Drug | Decision |
|---|---|---|
| 1 | Vancomycin | investigate |
| 2 | Linezolid | watch |
| 3 | **Oxacillin** | **deprioritise** |

Oxacillin is the beta-lactam `mecA` defeats. The panel put it last and advised setting
it aside **without being told our evasion verdict**, which is the agreement the blinding
was built to make meaningful. It disagreed with us at the top, preferring vancomycin to
linezolid — which is the point of asking.

One juror's reading is not evidence that the ranking is right, and agreement between
models is consistency, not correctness.

## Two findings that would have broken the demo

1. **`gemini-2.5-pro` is gone.** The model ID this repository configured in the README
   and in `settings.py` examples returns HTTP 404: *"no longer available to new users"*.
   A fresh key cannot use it. The README example is updated; the `settings.py`
   docstrings and `app/api/tests/test_providers.py` still name it and should be revisited.
2. **`gemini-3.1-pro-preview` returns HTTP 429** on this key — quota exhausted, not an
   auth failure. `gemini-3-flash-preview` worked; `gemini-3.8-flash` timed out at 90 s.

So "the client is written" and "a key works" are two different things, and the second
needs a model ID that still exists.

## Latency matters for the app

97.5 s is a reasoning model thinking. `POST /api/resistance/profiles/{id}/jury` is
synchronous, so the button in the candidates step waits that long with only a progress
line. Acceptable to click once in a demo; it is not a fast interaction, and a
three-model panel in turn would be slower still. If it needs to feel quick, the route
should become a background job as the disease flow's jury is.

## Reproducing

Needs a key with quota. Nothing is committed that contains one.

```sh
GEMINI_API_KEY=... JURY_TIMEOUT_SECONDS=180 \
  uv run python -m jury --help   # or drive build_prompt/ProviderModel directly
```

A key pasted into a chat or a shell history should be treated as public and rotated.
