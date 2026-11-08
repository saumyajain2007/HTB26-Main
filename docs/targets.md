# Bacterial targets and structures (WS3, issues #20 and #21)

Which bacterial enzymes the docking set covers, why, and how each candidate PDB entry did in the redocking control. Measured on 7 and 8 November 2026 with the pinned toolchain (Vina 1.2.7, Meeko 0.8.0, RDKit 2026.09.1; exhaustiveness 8, seed 42, 9 poses, 25 Å box on the crystal ligand) in the amd64 container described in [app/worker/README.md](../app/worker/README.md). The control passes when the top pose is within 2.0 Å of the crystal pose (heavy atoms, symmetry-aware, no alignment).

## Chosen targets

| Target | Organism | UniProt | Why it is a good antibacterial target | Essentiality evidence |
|---|---|---|---|---|
| DNA gyrase subunit B (GyrB, ATPase domain) | *Staphylococcus aureus* | P0A0K8 | Target of the aminocoumarins; bacterial gyrase has no human counterpart. Links to the quinolone story in the resistance profile (gyrA, ARO:3003296), though see "Gaps" below | Review of gyrase as an essential drug target: Collin, Karkare and Maxwell 2011, *Appl Microbiol Biotechnol* 92:479 (PMID 21904817). Genome-wide screen: Chaudhuri et al. 2009, *BMC Genomics* 10:291 (PMID 19570206) |
| LpxC (UDP-3-O-acyl-GlcNAc deacetylase) | *Pseudomonas aeruginosa* | P47205 | Commits the first step of lipid A synthesis; no human homologue. A Gram-negative target, which the *S. aureus* GyrB entries do not cover | Mdluli et al. 2006, *Antimicrob Agents Chemother* 50:2178, "Molecular validation of LpxC as an antibacterial drug target in *Pseudomonas aeruginosa*" (PMID 16723580). Genome-wide: Jacobs et al. 2003, *PNAS* 100:14339 (PMID 14617778) |

**What was and was not checked.** All five references exist (looked up on PubMed). For the two genome-wide screens and the LpxC paper I confirmed the reference and title, not the gene-level entry. **The Database of Essential Genes (DEG) was not queried.** Before the writeup quotes "essential", look up *gyrB* and *lpxC* in DEG or the screens' supplementary tables and replace this paragraph with what they say.

## Structures that pass the redocking control

All four are in `app/worker/structures/`, prepared by the repo's own `htb_worker.prepare` from [structures.json](../app/api/htb_api/fixtures/structures.json) and re-measured on those committed files (same RMSDs).

| PDB | Target | Resolution | Co-crystal ligand | Top-pose RMSD | Score | Best of 9 | Result | Primary paper |
|---|---|---|---|---|---|---|---|---|
| 3G7B | *S. aureus* GyrB | 2.30 Å | B47, pyrazolylthiazole | 1.60 Å | -7.64 | 1.45 Å (pose 4) | passed | Ronkin 2010, BMCL 20:2828 (PMID 20356737) |
| 3U2K | *S. aureus* GyrB | 1.64 Å | 087, pyrrolamide | 1.72 Å | -8.63 | 1.72 Å (pose 1) | passed | Eakin 2012, AAC 56:1240 (PMID 22183167) |
| 2VES | *P. aeruginosa* LpxC | 1.90 Å | GVR, BB-78485 (hydroxamate) | 0.92 Å | -9.84 | 0.92 Å (pose 1) | passed | Mochalkin 2008, Protein Sci 17:450 (PMID 18287278) |
| 3P3E | *P. aeruginosa* LpxC | 1.28 Å | 3P3, LPC-009 (hydroxamate) | 0.68 Å | -9.47 | 0.68 Å (pose 1) | passed | Lee 2011, Chem Biol 18:38 (PMID 21167751) |

Read these with care:

- That is **four structures but only two targets**. The issue's "at least three bacterial structures pass" is met by count, not by target diversity.
- 3G7B and 3U2K are the same protein from the same species and so are 2VES and 3P3E, so they are not independent tests.
- 3G7B passes by a margin (1.60 Å) and its pose 3 sits right on the 2.0 Å line; 3U2K also sits at 1.72 Å. A different seed could move either across.
- The LpxC controls are easier than they look: the hydroxamate chelates the active-site zinc, and the prepare step deletes the zinc (and all ions, waters and cofactors). Vina has no metal model, so a good RMSD says the pocket shape is enough to place this ligand, not that the zinc binding was modelled.
- A passed control means "this ligand redocks into its own crystal structure", not that Vina scores unrelated drugs correctly.
- **The constructs are not pure wild type.** Read from RCSB's records on 8 November 2026: 3P3E has Cys40 replaced by Ser (labelled an engineered mutation) and 2VES has the same change (labelled a conflict); 3G7B lacks UniProt residues 105 to 127 in both chains; 3U2K has only an added initiating methionine. None is a resistance mutation. Why the changes were made, and whether any touches the pocket, were not checked.
- **The LpxC structures are from *P. aeruginosa*,** which is not one of the candidate organisms for LpxC in the target registry (*A. baumannii*, *K. pneumoniae*). Whether they stand in for those organisms' LpxC has not been assessed.
- **Checked against RCSB on 8 November 2026** (`HTB_CHECK_RCSB=1`): for all four, the organism and the named co-crystallised ligand match RCSB's records. The redocking numbers above were not re-run for that check.

## Structures tried and dropped (failed or not usable)

Dropped from the committed set, as the issue asks. Files were removed; the result is recorded here.

| PDB | Target | Top-pose RMSD | Best of 9 | Result | Likely reason (not tested) |
|---|---|---|---|---|---|
| 4DUH | *E. coli* GyrB, 1.50 Å | 7.22 Å | 3.31 Å | failed | Not investigated |
| 6F86 | *E. coli* GyrB, 1.90 Å | 2.45 Å | 2.33 Å | failed | Close to the line; prepare cut three side chains back (not checked whether any line the pocket) |
| 5D6Q | *S. aureus* GyrB, 1.50 Å | 5.15 Å | 3.14 Å | failed | Not investigated |
| 3GR6 | *S. aureus* FabI + triclosan, 2.28 Å | 6.33 Å | 3.96 Å | failed | Triclosan binds together with the NADP cofactor, which prepare removes |
| 6Y6U | *P. aeruginosa* PBP3, 1.55 Å | 6.31 Å | 3.67 Å | failed | Small flexible ligand with a weak score (-5.9); not investigated |
| 2W9H | *S. aureus* DHFR (wild type) + trimethoprim, 1.48 Å | 3.60 Å | 1.54 Å | failed | Trimethoprim packs against the NADPH cofactor, which prepare removes |
| 3TTZ | *S. aureus* GyrB, 1.63 Å | 1.93 Å | 1.93 Å | passed, **not kept** | Passes by 0.07 Å; left out as too fragile, and it duplicates 3U2K's series |

Not prepared at all:

- **6CAX** (*P. aeruginosa* LpxC, 1.25 Å): the prepare step stops because the ligand EUY appears twice in chain A. Fixing that needs a change to `prepare.py`.
- **3FRB** (*S. aureus* DHFR F98Y, the trimethoprim-resistance mutant, chain X): the prepare step stops with a 404 because it asks RCSB's chain API with the author chain letter, and this entry's chain X is not found that way. This is the one real wild-type and resistance-mutant pair I found, and it is why the wild type (2W9H) was tried; with the wild type failing, there is no usable pair.
- **PBP2a** (3ZFZ and other MRSA entries) and the **PBP3** acyl-enzymes (4KQO): the ligand is covalently bound to the active-site serine, which Vina cannot model, so a redocking control is not meaningful.

## Gaps against the resistance profiles

The fixture profile ([resistance_profile.json](../app/api/htb_api/fixtures/resistance/resistance_profile.json)) names two sensitive targets, **GyrA** (`gyrA S84L`) and a **beta-lactam-sensitive PBP** (`mecA`).

- **No PBP structure passes.** Beta-lactams bind covalently (see above) and the one non-covalent PBP3 entry tried failed.
- **No GyrA structure was tried.** Fluoroquinolones bind in a complex of gyrase, DNA and a metal ion, which the one-chain receptor in this docking setup cannot represent. GyrB (ATPase site) is the nearest feasible target; it is not where S84L sits.
- **Mutant handling:** no resistance-mutant structure is in the set. The only candidate found was DHFR F98Y (3FRB, above), blocked by the prepare step. Nothing mutant is claimed.

## Decision: bacterial structures in the shared contract

Decided 8 November 2026 (Kanish H R, in the session that did #20 and #21): add the four passing structures to the committed set and widen the contract just enough to hold them, rather than keeping them out of the app until the wider pivot (WS9). This touches files that [tasks.md](../tasks.md) marks as shared, so the other lanes need a heads-up.

What changed, and why each is the smallest change that works:

| Change | Why |
|---|---|
| `StructureTargetId` in [schemas.py](../app/api/htb_api/schemas.py) for `Structure.target_id` and `DockJob.target_id`: an Ensembl gene ID **or** a UniProt accession | The old `^ENSG[0-9]{11}$` rejects bacterial proteins. Every other `TargetId` (networks, candidates, rankings) stays human-only |
| [Migration 0011](../deploy/db/migrations/0011_dock_bacterial_targets.sql) widens the `dock_jobs.target_id` check the same way; `SCHEMA_VERSION` is now `0011`; a parametrised test covers accepted and rejected values | The database repeats the pattern, so the schema change alone would fail on insert |
| Four entries appended to [structures.json](../app/api/htb_api/fixtures/structures.json), with `control.status: not_measured` | Existing entries are untouched. Measured controls come from the docking worker, which seeds one queued control per structure; the table above is the manual measurement |
| `app/api/openapi.json` and `app/web/src/api/schema.d.ts` regenerated | Generated, not hand-edited. The only diff is the new pattern and descriptions |
| `Ligand.candidate_id` **stays required** | I first proposed making it nullable because ChEMBL's API returned server errors for two ligands. UniChem then returned ChEMBL IDs for all four, and ChEMBL confirmed each is its own parent molecule, so no schema change was needed |
| [prepare.py](../app/worker/htb_worker/prepare.py): the listing path pointed at `api/` at the repo root, which no longer exists after the move to `app/` | Prepare could not start. Fixed so the committed `meta.json` files come from a real run, not hand edits |
| Expected structure lists and the queue test's job counts (4 to 8) updated | They hard-coded the old set |

ChEMBL parent IDs of the co-crystal ligands: B47 CHEMBL1094382, 087 CHEMBL1923431, GVR CHEMBL261713, 3P3 CHEMBL1230182 (looked up by InChIKey, 8 November 2026).

**What "appear in the app" means today.** The structures are in `GET /api/structures`
(fixture and Vina modes), and the docking worker queues a redock control for each.
The resistance flow is now the default app and can display saved real rankings.
The candidate 3D view and bacterial structure matching are in PR #99; until that
lands, the resistance shortlist does not offer these bacterial structures. A
prepared crystal structure is not a docked candidate pose.

**Test status after the change.** API 362 passed, worker 36, web 165, migrations 34 passed. Three failures remain and are on clean `main` too: two resistance fixture comparisons (`test_resistance.py`) and `test_candidates_cannot_be_dropped_out_from_under_votes_or_docking`.

## Reproduce

Prepare (writes `structures/{PDB}/`; restore `settings.json` afterwards if the container's Python patch version differs), then the control, per structure:

```bash
docker run --rm --platform linux/amd64 -v "$PWD":/repo -w /repo -e PYTHONPATH=/repo/app/worker \
  htb-docking:local python -m htb_worker.prepare 3G7B
docker run --rm --platform linux/amd64 -v "$PWD":/repo -w /repo -e PYTHONPATH=/repo/app/worker \
  htb-docking:local python -m htb_worker.control 3G7B
```

`htb-docking:local` is built from `.devcontainer/docking.Dockerfile`. Its Python is 3.11.18 while `settings.json` records 3.11.17; only the Vina, Meeko and RDKit versions are checked, so I left `settings.json` as committed.
