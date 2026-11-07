# Third-party notices

## tree26 (RepoRx), TreeHacks 2026

Structure retrieval and docking runner adopted from reporx
Copyright (c) 2026 Eric Zou, used under the MIT License.

Derived files, all in [core/discovery_pipeline/](core/discovery_pipeline/):

- `agent2.py` (structure retrieval)
- `agent3.py` (DiffDock docking runner)
- `pipeline.py` (orchestration)
- `review.py` (literature review)
- `results.py` (results reporting)
- `final.py` (paper generation)
- `requirements.txt`

Each derived file carries a header comment naming the source. The full licence text is in
[core/discovery_pipeline/LICENSE](core/discovery_pipeline/LICENSE).

## CARD, the Comprehensive Antibiotic Resistance Database

Resistance ontology and detection-model data from McMaster University, downloaded at build time
and not committed to this repository (`data/card/` is gitignored). Code that reads it is in
[core/resistance/](core/resistance/).

- Licence: Creative Commons CC-BY 4.0, as stated on card.mcmaster.ca/download and in the ontology
  README. The README inside the data archive adds that use by any commercial organisation needs
  written permission from McMaster University, so treat the data as non-commercial.
- Citation: Alcock et al. 2023. CARD 2023: expanded curation, support for machine learning, and
  resistome prediction at the Comprehensive Antibiotic Resistance Database. Nucleic Acids Research
  51, D690-D699. https://pubmed.ncbi.nlm.nih.gov/36263822/
- The release used is recorded in each `manifest.json` (version, archive checksums).

## ChEMBL

Drug names, structures, ATC codes, mechanisms and targets for the antibiotic catalogue, from the EMBL-EBI
ChEMBL database release 37, downloaded and not committed (`data/` is gitignored). The catalogue is built by
[core/resistance/htb_resistance/catalogue.py](core/resistance/htb_resistance/catalogue.py).

- Licence: Creative Commons CC-BY-SA 3.0. Attribute ChEMBL and the release number. Any adaptation of the
  data, including the catalogue tables, must be distributed under the same share-alike terms.
- Citation: Zdrazil et al. 2024. The ChEMBL Database in 2023: a drug discovery platform spanning multiple
  bioactivity data types and time periods. Nucleic Acids Research 52, D1180-D1192.
  https://pubmed.ncbi.nlm.nih.gov/37933841/
- The release is recorded in each catalogue `manifest.json`, with the archive checksum.
