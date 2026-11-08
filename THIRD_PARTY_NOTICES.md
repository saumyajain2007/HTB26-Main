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
and not committed to this repository (`data/card/` is gitignored), with one exception: a small excerpt of
CARD 4.0.2 (18 determinants and the ontology terms they need, 389 rows) is committed under
[core/resistance/tests/fixtures/card_slice/](core/resistance/tests/fixtures/card_slice/) so tests can run in CI. It is
CARD's own rows, unedited, and its `manifest.json` says it is an excerpt. The licence and the caveat below apply to it too.
Code that reads the data is in [core/resistance/](core/resistance/).

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

## RCSB PDB and the wwPDB archive

Crystal structures used for docking. The committed files are in
[app/worker/structures/](app/worker/structures/): 3G7B, 3U2K, 2VES and 3P3E (bacterial
targets) and 6O0K, 6WTN, 6WTO and 7BQU (the earlier human set). Each directory holds a
receptor PDB, a prepared PDBQT, and the co-crystal ligand SDF. The PDBQT is this repo's
preparation of the deposited coordinates, not a wwPDB file.

- Licence: CC0 1.0 for PDB archive data files and for RCSB programmatic-API data, as stated
  on [RCSB's usage policy](https://www.rcsb.org/pages/usage-policy), which points at the
  [wwPDB policy](https://www.wwpdb.org/about/usage-policies). Checked 2026-11-08.
- Cite the PDB id and the structure's primary paper. The four bacterial entries and their
  papers are listed in [docs/targets.md](docs/targets.md). RCSB site text and Molecule of
  the Month articles are not under CC0 and are not reused here.

## Disease-pipeline data (still in the repo, not the antibiotic ranking)

These feed `core/pipeline/` and the human-disease flow. Full downloads live under `data/`,
which is gitignored. Licences below are the ones already recorded in this repo. They were
not re-checked for this notice.

| Source | Where the licence is recorded | Licence |
| --- | --- | --- |
| Open Targets | [core/pipeline/manifest.py](core/pipeline/manifest.py), checked 2026-10-24 | CC0 1.0. Cite Open Targets. |
| ChEMBL, when used by that pipeline | same file, release 37 | CC-BY-SA 3.0, as in the ChEMBL section above |
| STRING | same file, checked 2026-10-24 | CC-BY 4.0. Attribute STRING. Third-party material inside STRING keeps its own terms. A saved distance bundle can lack its own download URL and licence record; [core/ranking/README.md](core/ranking/README.md) says those fields are missing on purpose and must be added before that bundle is redistributed. |
| PubChem | same file, checked 2026-10-24 | No single licence. NCBI does not grant blanket rights in contributor-submitted records. |
| Reactome release 97 | [tests/fixtures/README.md](tests/fixtures/README.md), checked 2026-10-25 | CC0. https://reactome.org/license |

## Scientific toolchain

Libraries, not copied source. Versions are the ones pinned in this repo. Application
frameworks (FastAPI, React, Postgres, and the rest of the lockfiles) are not listed.

| Tool | Version | Where | Licence |
| --- | --- | --- | --- |
| RDKit | 2026.9.1 | `core/verify`, docking venv | BSD 3-Clause. Copyright 2006-2015 Rational Discovery LLC, Greg Landrum, and Julie Penzotti and others. https://github.com/rdkit/rdkit/blob/master/license.txt |
| AutoDock Vina | 1.2.7 | `.devcontainer/docking-requirements.txt` | Apache 2.0. https://github.com/forlilab/AutoDock-Vina |
| Meeko | 0.8.0 | same file | LGPL-2.1. The tag `v0.8.0` ships that licence. https://github.com/forlilab/Meeko |
| gemmi | 0.7.5 | same file | Mozilla Public License 2.0. https://github.com/project-gemmi/gemmi |
| PoseBusters | 0.6.5 | same file | MIT. Copyright (c) 2025 Martin Buttenschoen. https://github.com/maabuu/posebusters |
| Lean 4 | v4.35.0 (`core/verify/lean/lean-toolchain`) | certificate check | Apache 2.0. https://github.com/leanprover/lean4 |
| 3Dmol.js | 2.5.5 (`app/web`) | pose viewer | BSD 3-Clause. Copyright (c) 2014 University of Pittsburgh and contributors. It incorporates GLmol (MIT or LGPL-3.0), Three.js and jQuery. https://github.com/3dmol/3Dmol.js |
| Three.js | 0.186.1 (`app/web`) | direct dependency as well as via 3Dmol | MIT. https://github.com/mrdoob/three.js |

## Fonts

- DM Sans, files under [app/web/src/intro/assets/](app/web/src/intro/assets/). SIL Open Font
  License 1.1. Copyright 2014 The DM Sans Project Authors. The licence text is in
  `dm-sans-LICENSE.txt` next to the files.
- Instrument Sans and Source Serif 4, loaded from the `@fontsource-variable` packages named
  in [app/web/package.json](app/web/package.json). Both are published under the SIL Open
  Font License 1.1. The font files are not committed; the packages bring them in at build.
