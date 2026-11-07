Recorded on 2026-10-24 from the public Open Targets 26.09 S3 Parquet cache,
the pinned A2 API query, ChEMBL 37 REST and PubChem PUG REST by InChIKey.

http.json contains request envelopes and responses projected to the fields used
by A4. The two association pages are sampled to the six fixture ENSG IDs, with
sample count adjusted; original count was 5341. No measurements were changed.
The ot-*.json files contain projected Parquet records for the five fixture
parents and included salts, plus protein mappings for the recorded ChEMBL
accessions. Missing accessions were checked against the full 78,733-row target
cache. Trial records are excluded from the clinical_report sample; only
APPROVAL rows are needed to verify generic approval provenance. References
and warnings, including records without references, retain their source IDs.

The HTTP envelopes record retrieval time and source release. PubChem has no
numbered release and uses a dated snapshot. The full downloaded Parquet and
HTTP responses, and live run results, remain under ignored data/.

QA regression samples add ivacaftor (CHEMBL2010601), tezacaftor
(CHEMBL3544914) and gemtuzumab ozogamicin (CHEMBL1201506). qa-http.json
contains their projected ChEMBL 37 and PubChem responses;
qa-drug-targets.json uses the drug_targets.json input shape and verified
Open Targets mechanism mappings. The ot-*.json samples include the matching
26.09 records: shared FDA report label/2018/210491lbl.pdf and warning 4457
with its original description, "greater number of deaths". Tests also inject
Disease mentions and a numeric description to check redaction and values.
