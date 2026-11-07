# Stream A sample contracts

Live A2 outputs may include `approval.overrides` (Disease IDs and regulator URLs); coverage counts these verified additions separately.

One illustrative Experiment for the Disease **plasma cell myeloma**
(`MONDO_0009693`). These small files let Streams A, B and C build together.

| File | Deliverable that produces it | Who uses it | Plan section |
| --- | --- | --- | --- |
| `disease_targets.json` | A1: Disease resolution and evidence-only Targets | Zaid / Stream B | §3, §4.3 |
| `drug_targets.json` | A2: approved Candidate universe and Target mapping | Stream B, Worker 4 | §3, §4.2 |
| `string_id_map.json` | A3: STRING protein → Target mapping | Stream B | §3, §4.1 |
| `candidates.json` | Candidate result, assembled by Stream B | Abudi / Stream C, Worker 4 | §9.2 |
| `evidence_packet.json` | A4: blinded evidence packet | Worker 5, Stream C | §5, §6.3 |
| `jury_result.json` | A5: Model jury validation and consensus | Stream C, Stream B Experiment B | §5, §6.2 |

**IDs and source text are real; every score, rank, distance, z-score,
pChEMBL, activity count and latency is fictional.** They are examples, not
research results. Coverage counts and jury summaries are calculated exactly
from these rows. IDs, release versions and configuration settings are not
measurements. The six Disease Target rows are a small sample, not the actual
top 50; direct-evidence ranks illustrate a larger eligible universe.

Stream B owns `network`, `direct_evidence_rank`, `selected_by` and
`unscorable_reason`. Their fixture values are fictional assignments, not
computed from the other files. In particular, BCL2 is deliberately absent
from the fictional network despite having a verified STRING mapping; this
lets venetoclax exercise the evidence-only, `not_scorable` path.

Use the ID and mapping rules in plan §3 (the removed `plan.md`, in the Git history): current
Open Targets Disease IDs with underscores, ENSG Target IDs, ChEMBL parent
Candidate IDs, Experiment UUIDs, Experiment-local `E#` evidence IDs, packet-local
`C#` labels and `source-version` releases. STRING `9606.ENSP…` IDs are lookup
columns only. Names and symbols are display text; never join on them.

Salts are merged into their verified parents. Ruxolitinib includes its
phosphate `CHEMBL1795071`; exclude the erroneous deuruxolitinib links
`CHEMBL4594381` and `CHEMBL4594382` described in plan §3. Their JAK3/TYK2
mechanisms must not enter ruxolitinib. Melphalan's parent and hydrochloride
have the same DNA mechanism, collapsed to one `non_protein_target` item.
Melphalan stays only in `drug_targets.json`: it has no protein Targets and
cannot enter this shortlist through direct Target evidence. Venetoclax,
which inhibits the Disease Target BCL2, replaces it in the Candidate result,
evidence packet and Model jury. TP53 and CCND1 are Disease Targets that no
fixture Candidate acts on. Baricitinib includes TYK2 through bioactivity
only, with null action type; JAK1 has both mechanism and bioactivity support.

**One record gets one E ID within the Experiment.** JAK1 and JAK2 association
items are shared unchanged by baricitinib and ruxolitinib. Each Candidate
cites an association item for every one of its Targets present in the
Disease Target sample. `values` holds numbers only (or is `{}`); source
names, Target names, action types and warning classes belong in `statement`.
Statements use the same source-naming templates as real data; the fixture
numbers remain fictional. A bioactivity item's `source_id` identifies the
molecule/ChEMBL-target pair, and its URL queries activities for that pair
with non-null pChEMBL values.

Enums: Candidate `status` is `scored`, `distance_only` or `not_scorable`.
`distance_only` has a network distance but a null `degree_matched_z` because
the degree-matched null has no spread; its `network` stays populated.
`not_scorable` has null `network` and a nonempty `unscorable_reason`.
`selected_by` contains
`network` and/or `evidence`; Target `support` contains `mechanism` and/or
`bioactivity`. Mapping `status` is `mapped`, `unmapped` or `ambiguous`, with a
reason for either non-mapped status. Evidence `source` is `open_targets`, `chembl`, `string` or `reactome`; `kind` is
`target_association`, `mechanism`, `bioactivity`, `approval`, `warning` or
`network_path` or `pathway`. Safety is `warnings_recorded` or `unknown`, never safe.
Juror `status` is `valid`, `invalid` or `failed`; `decision` is `investigate`,
`watch` or `deprioritise`; `direction` is `supported`, `contradicted` or `unknown`.
The live mechanism action type here is `INHIBITOR`.

The saved `jury` object is the database's `jury_config`: `models`,
`prompt_version`, `temperature`, `max_attempts`, `shuffle_seed` and
`reasoning_effort`. The existing keys keep their types and meanings.
`reasoning_effort` maps every configured model ID to its explicit provider
setting (for example `{"kimi-k3": "low"}`) or null when no override was sent.
Null means the provider default, not an inferred effort level. The live CLI
accepts `SNOWFLAKE_REASONING_EFFORT` as an override of the config file and
saves the effective settings. Older input configs may omit this mapping.

Each juror's `token_usage` is an array with one object per attempt, including
failed and invalid attempts: `{"attempt": 1, "input_tokens": 3475,
"output_tokens": 1977}`. Counts are nonnegative integers or null when the
provider supplied none (including failures and mock replies), never estimated
zeros. Sum all attempts for usage; any missing count makes the full cost
unknown. Anthropic attempts may also record `max_output_tokens` and
`stop_reason` when supplied by the adapter. The illustrative fixture uses
null counts because it contains no model calls.

Jurors see only `disease.name`; each Candidate's `label`, `name`, Target
`name` and `mechanism`, `evidence_ids` and `safety_status`; and each evidence
item's `id`, `kind`, `statement` and `values`. `candidate_id`, Target IDs,
`source_id` and `url` are never sent to jurors. The stored packet preserves
those identifiers for traceability. It contains no network result, selection
reason or baseline/overall rank. Approval Disease IDs in `drug_targets.json`
are complete A6 unions across each parent and its included salts, used only
as display/evaluation labels. Approval evidence states only that an
approval exists; no evidence item asserts a Candidate–Disease indication or
trial relationship. Missing warning records mean `unknown`; recorded warnings
are not an exhaustive safety assessment. Each warning stores `evidence_id`,
`type`, `toxicity_class` and the source's own `description` (null for these
records). Model jury reviews cite warnings only in `safety`, never as
supporting or contradicting biological evidence.

With n Candidates, Borda gives rank r exactly n − r points, summed over valid
jurors. Ties share the higher rank, skipping subsequent positions (1, 2, 2, 4).
For m valid jurors, Rᵢ is Candidate i's rank sum,
S = Σᵢ(Rᵢ − m(n+1)/2)² and Kendall's W = 12S / [m²(n³ − n)], rounded to four
decimals; W is null below two valid jurors. `contested` means valid jurors gave
different decisions. Here the points are 6, 3, 3, 0, W is 0.9000, and C3 is
contested. The invalid juror supplies no vote. Reviews are examples, not model
calls. **All three model IDs were checked in the team's Snowflake account: each
answered through `AI_COMPLETE`** (Anthropic, OpenAI and Zhipu `glm-5.3`;
`glm-5.3` replaced `llama3.1-8b`, which is too small for this review).

Live verification on 2026-10-24 (no credentials):

- Disease IDs and six ENSG associations: POST [Open Targets GraphQL](https://api.platform.opentargets.org/api/v4/graphql), `diseases(efoIds: ["MONDO_0009693", "EFO_0001378"]) { id name obsoleteTerms }` and both `associatedTargets` pages of size 3000; the old EFO ID is in `obsoleteTerms`. BCL2, TP53 and CCND1 each have non-excluded association evidence in 26.09.
- Parent and salt IDs: [ChEMBL molecule REST](https://www.ebi.ac.uk/chembl/api/data/molecule.json), `molecule_hierarchy__parent_chembl_id=<parent>&limit=100`, for all five parents; check `molecule_hierarchy.parent_chembl_id`. No pages remained. Venetoclax's parent is `CHEMBL3137309`.
- Approval Disease IDs and report IDs: Open Targets A6 `drugs(chemblIds: ...) { indications { rows { maxClinicalStage disease { id } clinicalReports { id source clinicalStage url } } } }`, requiring `APPROVAL` plus a regulator report. All included parent/salt IDs were queried; each fixture list includes every qualifying Disease returned, deduplicated after merging salts.
- Mechanism IDs: [ChEMBL mechanisms](https://www.ebi.ac.uk/chembl/api/data/mechanism.json), `parent_molecule_chembl_id=<parent>&limit=100`; retain records 7379, 5293, 5294, 934, 936 and 5516 for shortlisted Candidates. Open Targets confirms all four FGFR mappings and venetoclax → BCL2. Melphalan mechanism 1858 targets [CHEMBL2311221](https://www.ebi.ac.uk/chembl/api/data/target/CHEMBL2311221.json), `NUCLEIC-ACID` DNA.
- Bioactivity pairs: human `SINGLE PROTEIN` [JAK1 CHEMBL2835](https://www.ebi.ac.uk/chembl/api/data/target/CHEMBL2835.json) / P23458 and [TYK2 CHEMBL3553](https://www.ebi.ac.uk/chembl/api/data/target/CHEMBL3553.json) / P29597 map through Open Targets `proteinIds`. ChEMBL `activity.json?molecule_chembl_id=CHEMBL2105759&target_chembl_id=<target>&pchembl_value__isnull=false` returns real human activities for both pairs; the fixture medians and counts are invented.
- Warning IDs and text: Open Targets `drugs { drugWarnings { id description warningType toxicityClass references { id source url } } }`, including ruxolitinib phosphate; preserve record IDs, type, class and null description. Exclude the ruxolitinib parent warning inherited from the known bad deuruxolitinib link.
- STRING IDs: [current version API](https://string-db.org/api/json/version) returned 12.5. Downloaded the complete [human protein.info 12.5](https://stringdb-downloads.org/download/protein.info.v12.5/9606.protein.info.v12.5.txt.gz) into `data/string/` and all three Parquet parts of the [Open Targets 26.09 target dataset](https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/?list-type=2&prefix=platform/26.09/output/target/) into `data/ot/target/`. The complete listing was not truncated. Across 78,733 Target rows, 370,886 distinct `ensembl_PRO` IDs were compared with all 19,699 human STRING proteins. The difference has 487 proteins, including `9606.ENSP00000053469`, now an `unmapped` row with null `target_id`. The other ten fixture Targets map exactly after dropping only `9606.`. These verification counts describe downloaded source data; fixture coverage counts describe fixture rows.
- PubChem IDs: read each parent's ChEMBL `molecule_structures.standard_inchi_key`, then call [PUG REST by InChIKey](https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/OLAHOMJCDNXHFI-UHFFFAOYSA-N/cids/JSON). Verified erdafitinib `OLAHOMJCDNXHFI-UHFFFAOYSA-N` → 67462786; baricitinib `XUZMWHLSFXCVMG-UHFFFAOYSA-N` → 44205240; ruxolitinib `HFNKQEVNSGCOJV-OAHLLOKOSA-N` → 25126798; venetoclax `LQBVNQSMGBZMKD-UHFFFAOYSA-N` → 49846579. CIDs are lookup IDs, not join keys or scores.
- Releases: Open Targets `meta { dataVersion { year month } }` returned 26.09; [ChEMBL status](https://www.ebi.ac.uk/chembl/api/data/status.json) returned ChEMBL_37; STRING returned 12.5. The Experiment UUID and E/C IDs are local fixture identifiers.

Run `.venv/bin/python -m pytest -q`. No live APIs or model calls are needed
for the fixture tests. Only Snowflake model availability remains unverified.
Fictional numerical values and network outcomes are deliberately not verified
against measurements. Downloaded source datasets remain under ignored `data/`.

`network_path` evidence uses source `string`, release `string-12.5`, and
`values: {"hops": n}`. One item represents one ID-resolved representative
path; identical paths share an E ID. `source_id` is the ordered Ensembl gene
IDs joined with `>`, then `@` and the pinned graph's SHA256. Symbols come from
Open Targets target records joined by Ensembl ID. STRING links use mapped
`9606.ENSP…` protein IDs and its documented `/cgi/network` endpoint
([STRING API documentation](https://string-db.org/help/api/)). These pages show
a network view; they do not reproduce the direct-experiment filter or provide
individual edge citations. The graph artifact establishes the filtered path.

E22 is a real zero-hop FGFR3 overlap from Zaid's myeloma path export
(`data/a6_paths/MONDO_0009693/paths/shortlist.json`, nintedanib's FGFR3
representative). Erdafitinib has the same ID-mapped Target. Its hop count and
graph hash are measured, unlike the illustrative ranking numbers above.
The graph is undirected, filtered at combined score ≥700 and direct
experiments ≥400. A connection is an association, not a proven mechanism,
causal direction, benefit or treatment evidence. Missing symbol/protein
mappings are counted as unmapped outside the packet, never name-matched.
No mean distance, z-score, rank or path-count metadata enters a packet.
`jury-v5` explains these limits while retaining strict citation, numeric,
complete-ballot and safety checks. No packet keys or value types changed.


`pathway` evidence uses `source: reactome`, `release: reactome-97`, the
R-HSA pathway ID as `source_id`, its Reactome detail page as `url`, and
`values: {"pathway_gene_count": n}`. E23 is real: R-HSA-9006335,
“Signaling by Erythropoietin”, has **5 distinct ENSG gene members** in the
complete release-97 lowest-level Ensembl2Reactome mapping, including the
fixture drug/Disease Target JAK2 (ENSG00000096968). This measured count is
an exception to the fictional-measurements notice above. The six Disease
Targets here remain a sample, standing in for a live top-50 set.
Membership is joined by ENSG only. Protein/transcript identifiers are
counted as unmapped; no symbol matching or All_Levels propagation occurs.
Live selection excludes pathways with more than 300 genes and retains at
most three per Candidate, smallest first then pathway ID. A shared pathway
is not evidence of effect, causality, direction, benefit or treatment.
The fixed statement can serve several Candidates sharing a pathway.
`jury-v6` explains this while keeping all validators strict.

Source: [Reactome release 97 mapping](https://reactome.org/download/97/Ensembl2Reactome.txt);
[download format](https://reactome.org/download-data/);
[data licence: CC0](https://reactome.org/license), checked 2026-10-25.
The complete raw download hash and human-filtered hash, retrieval timestamp,
URL, version and licence are in `data/reactome/97/manifest.json`.


### Jury reliability contract (future runs)

`jury-v7` clarifies retrospective public-data evidence review, no advice for any
patient, and investigation priorities rather than recommendations. The validators
and `valid` / `invalid` / `failed` status enum are unchanged. A provider refusal
is recorded as `Attempt N: refused (provider stop_reason=refusal)` in validation
errors; its flags are null because its output was not validated. It supplies no
reviews. Per-attempt token usage may additionally include `max_output_tokens`
and `stop_reason`, independently when supplied.

Consensus uses every valid juror; at least two are required. Both Borda points
and Kendall's W use only those valid ballots. `jurors_counted` records their
number; `failed_jurors` lists excluded model IDs; `reason` is null when a
consensus exists. The top-level `consensus_status` object always records those
three metadata fields, including when `consensus` is null. Below two valid
ballots `run_jury` writes `consensus: null` and reason
`fewer_than_two_valid_jurors` in `consensus_status`. It supplies no ranking from
a lone vote. The internal summary helper retains an empty ranking and null W
for legacy callers; persisted future jury results use the nullable contract.
The fixture already has two valid jurors and one invalid juror: its existing
Borda points, ranks, contested Candidates and W (0.9) are unchanged.

This is a design change for future runs only. Historical results retain their
published schema and frozen combining/scoring rules; they must not be migrated
or rescored to make them conform to this newer fixture.
