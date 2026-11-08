# Sponsor mapping

Written 2026-11-08 for issue #54. This page says which sponsor tracks the project can enter, and only with claims the repository already supports. It is not a writeup.

## Judging criteria

[hacktheburgh.com](https://hacktheburgh.com/) says sponsors set the challenge tracks, and that sponsors look for entries that match the spirit of the challenge and show technical ability and creativity. It does not publish a scored rubric for any sponsor.

The challenge names in [scope.md](../scope.md) section 9 were read from the sponsor slide. Nobody has confirmed those names, or any scoring sheet, with the sponsors. Until that happens, treat the names below as the slide text, not as a confirmed rubric.

Tracks with no natural fit, and which this project does not enter: JetBrains (Help the Developer), Instalily (a coding agent that adapts to its user), Bank of Scotland (Smart Cost of Living), Viridien (lithology and well logs).

## HRT: predictions and decision making

**Claim we can make.** The tool turns a resistance profile into an ordered list of approved antibiotics, with a separate reason for each place, so a person can see which drugs CARD does not link to the genes they gave. The order is a written rule (evasion, then a species-level median MIC when one exists, then the property smoke test). It is not a trained model and it is not a clinical recommendation.

**What is in the repo.**

- Real profiles for *A. baumannii*, *K. pneumoniae* and *S. aureus* are ranked against the ChEMBL catalogue. The saved run is in [pathogen-integration.md](pathogen-integration.md): 126 drugs each, from CARD 4.0.2 and ChEMBL 37. Lean was not run on that bundle.
- A cited ground-truth table exists ([ground-truth.md](ground-truth.md), six rows). It has not been scored. The protocol is not frozen (#35) and the retrospective test has not been run (#37), so there is no hits@k, mean reciprocal rank, or confidence interval.
- The browser still serves fixture candidates. `app/api/htb_api/services/resistance.py` says the real profiling and ranking replace that fixture later. The numbers on the candidate screen are not the saved pathogen run.

**What we do not claim.** A validated accuracy. A hidden-drug result (#91, #92). A whole-cell activity model (#83 to #85). Any of those would be a prediction claim, and none of them exists yet.

## G-Research: make the invisible visible

**Claim we can make.** The resistance map and the candidate page show CARD's links, which are otherwise a set of tables: which mechanisms are present, which drug classes those mechanisms are tied to, and why each drug sits where it sits. The smoke-test panel and the Lean certificate view show the property rules as pass or fail, not as a safety badge.

**What is on screen.** The antibiotic flow is the pathogen input, then [ResistanceMap.tsx](../app/web/src/steps/ResistanceMap.tsx), then [ResistanceCandidates.tsx](../app/web/src/steps/ResistanceCandidates.tsx) (explanation, evidence, smoke test, certificate). It runs on the fixture profile and the fixture ranking.

**What is computed and not on that screen.** Four bacterial structures (3G7B, 3U2K, 2VES, 3P3E) passed a redocking control and are served by `GET /api/structures` ([targets.md](targets.md)). The web app still matches structures through a candidate's human targets, so those poses are not opened from a bacterial candidate (#41). The older human-disease network view is behind `VITE_DISEASE_FLOW` and is not this track's picture.

## Wordsmith

Issue #7 is in, and the browser agent is #95 (PubMed and ClinicalTrials.gov over the approved-drug shortlist). That agent is not built. Do not describe the project as an agentic browser workflow.

## Sponsor integrations

All four are optional. The app runs on fixtures with none of them. Setup is in the [README](../README.md#sponsor-integrations). Status below is what this repository shows, not a fresh call to each service.

| Integration | What exists | What is proven |
| --- | --- | --- |
| Google Gemini | A juror client, selected with `gemini:` model ids | Unit tests with fakes. The README says the client has not been run against the live service. Do not claim a live Gemini jury. |
| Vultr | An inference juror (`vultr:` model ids) and [deploy/vultr/setup.sh](../deploy/vultr/setup.sh) for a VM | Same as Gemini: fakes only, not tried live. The VM script is in the repo and has not been shown running here. |
| Tiger Data | Plain Postgres. No Timescale feature is used, so a Tiger Cloud connection string is a normal `DATABASE_URL` | [deploy/db/README.md](../deploy/db/README.md) records that the Tiger Cloud service `htb` already held migration `0001`. This page did not reconnect to that service. |
| Entire | Install and `entire enable` are written in the README | Not enabled in this checkout. Nothing is committed for it. `tasks.md` still has that step open. Do not claim Entire as a working integration. |

Snowflake Cortex is a third juror family in the same client. It is not one of the four sponsor names above, and the same "fakes, not a live call" limit applies to it.
