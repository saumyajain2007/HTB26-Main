Recorded A6 Snowflake replies from 2026-10-25, without further model calls.
`results.json` records the saved post-replay status and original attempt numbers
for each model/Disease. Replies retain the exact raw text and provider usage.

Packets preserve all Candidates, Targets, statements, values and local IDs.
Evidence source metadata (`source`, `source_id`, `url`, `release`) is omitted
from these test snapshots to keep each file below 200 KB. Original packets and
Target `symbolSynonyms` snapshots are in `data/a6/MONDO_*/`. Releases are
Open Targets 26.09, ChEMBL 37 and STRING 12.5, as recorded in each packet.
Aliases used by the regression: PIK3CA (ENSG00000121879) → PI3K and
KDR (ENSG00000128052) → VEGFR2, from Open Targets 26.09 `symbolSynonyms`.

Tests call `jury.client.validate_reply` directly, with no external lexicon and
no prose substitution. Mutations verify that names cannot hide measurements,
unknown citations or standalone E IDs.
