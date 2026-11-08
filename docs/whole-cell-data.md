# Whole-cell data, splits and leakage (issues #83 and #84)

What the whole-cell pipeline trains and tests on, how it is labelled and split, and what is **not** as the build spec assumed. Code: [core/wholecell](../core/wholecell). Rebuild: `uv run python -m htb_wholecell build`; check: `uv run python -m htb_wholecell verify data/wholecell/releases/<release>`. Measured 8 November 2026.

## Fetching the raw files

The build reads files that are not committed (`data/` is gitignored). SD1 and SD2 come from the paper authors' GitHub repository, the Hub file from Broad's public bucket; the manifest records each file's checksum, and the commit of the repository used was `GaryLiu152/chemprop_abaucin` at the time of download.

```bash
mkdir -p data/liu2023_abaucin/raw data/repurposing_hub/raw
for f in SD1_training_set.csv SD2_raw_prediction_set.csv; do
  gh api "repos/GaryLiu152/chemprop_abaucin/contents/data/$f" --jq .content | base64 -d > "data/liu2023_abaucin/raw/$f"
done
curl -fL -o data/repurposing_hub/raw/repurposing_samples_20200324.txt \
  https://s3.amazonaws.com/data.clue.io/repurposing/downloads/repurposing_samples_20200324.txt
```

ChEMBL 37 is the local file described in [data-layout.md](data-layout.md).

## What differs from the spec

| Spec | What was done | Why |
|---|---|---|
| CO-ADD bulk file, about 300k compounds, MIC <= 8 ug/mL | Not used | The bulk download on db.co-add.org was not reachable (certificate error) and its terms were not found. ChEMBL 37 carries a CO-ADD deposit for *A. baumannii* (about 23,000 molecules) but every one of its single-dose values is below 50% inhibition and nearly all its MICs are censored (">"), so it has almost no actives. Mixing it with literature actives would teach a model the source, not the activity. It is counted in the manifest and left out |
| One label rule | Two tables with two rules, never merged | The abaucin paper's screen is single-dose growth, not an MIC |
| ZINC subset or Drug Repurposing Hub | Hub (2020-03-24 samples file) | It holds both validation compounds: RS-102895 (abaucin) and SU3327 (halicin) |

## Tables (data/wholecell/releases/liu2023_hub20200324_chembl-37/tables)

| Table | Rows | Actives | Rule |
|---|---|---|---|
| `liu_train.tsv` | 7,624 | 108 (1.42%) | Replicate mean growth <= 0.2 (>= 80% inhibition at one dose) against *A. baumannii* ATCC 17978. Source: the training set of Liu et al., Nat Chem Biol 2023 (Supplementary Data 1) |
| `chembl_mic.tsv` | 8,418 | 1,704 (20.2%); 427 flagged as conflicts | Majority of usable ChEMBL 37 MICs <= 8 ug/mL. Censored values count only when they settle the call (`MIC < 16` says nothing about 8). nM is converted with the freebase mass |
| `hub_pool.tsv` | 6,605 | n/a | Hub compounds by parent structure; 6,506 also appear in Liu et al.'s prediction set (98.5%) |
| `splits.tsv` | both labelled tables | n/a | scaffold, random and year split |
| `drop_log.tsv` | every dropped record with its reason | n/a | |

The 0.2 threshold was fixed from the value histogram (a valley after the 0.2 bin) and replicate agreement (7,666 of 7,684 molecules agree at 0.2), before any model was trained. It is not the paper's own cut, which I could only find in a secondary summary (">80% inhibition at 50 uM").

The active rates differ by a factor of fourteen between the two tables. The literature MICs are mostly published analogue series of known actives, so a model that scores well on `chembl_mic` may be recognising chemical series. Treat `liu_train` as the primary table.

## Splits

All deterministic (`SPLIT_SEED = 0`). Scaffold: whole Bemis-Murcko groups go to train 70%, calibration 10%, test 20%, placed so actives are shared out in the same proportions as molecules. Random: label-stratified. Year: train before 2023, test from 2023, on `chembl_mic` only. `liu_train` has no per-compound dates, so it has no year split.

| `liu_train` | rows | actives |
|---|---|---|
| train | 5,334 | 75 |
| calibration | 764 | 12 |
| test | 1,526 | 21 |

**Twenty-one test actives is few.** Any AUC on this test set will have a wide interval; report it with one. Calibration has 12 actives, which limits the conformal step.

**A scaffold split is not a similarity split.** The share of test molecules whose nearest training molecule is above 0.5 Tanimoto (Morgan radius 2, 2048 bits):

| | random split | scaffold split |
|---|---|---|
| `liu_train` | 64.7% | 51.6% |
| `chembl_mic` | 87.6% | 80.5% |

So scaffold splitting removes part of the similarity, not most of it. Publish these numbers beside every score. A clustering split at 0.5 would be stricter; it has not been built.

Year coverage in `chembl_mic`: 995 of 8,418 molecules have no record year and are left out of the year split (they hold 2 actives).

## The leakage assertion

[leakage.py](../core/wholecell/htb_wholecell/leakage.py): `assert_no_leakage(held_out, sets)` raises if the held-out compound, or anything above 0.5 Tanimoto, is in the training set, calibration set, generator seeds or the baseline reference set. It fails closed (all four sets are required, even if empty), also matches by InChIKey, and `purge` builds the clean sets. Tests plant a leak in each of the four sets.

Measured on the real tables for the two validation compounds:

| Held out | `liu_train` | `chembl_mic` |
|---|---|---|
| Abaucin (RS-102895) | no analogue above 0.5 | **the compound itself, as an active (MIC 2 ug/mL, year 2024)** |
| Halicin (SU3327) | no analogue above 0.5 | one inactive analogue |

So training on `liu_train` needs no purge for these two, and training on `chembl_mic` does. This is the leak the assertion exists to catch: ChEMBL holds the paper's own result.

## Not verified

- Licences. The abaucin repository has no licence file, and the Hub's terms were not read. The manifest records both as NOT VERIFIED. Do not redistribute the raw files until checked.
- That RS-102895 is abaucin's structure. It matches the name widely reported (Liu et al. 2023) and the Hub entry; the paper's own structure figure was not compared.
- That the Liu et al. screen concentration and cut (">80% at 50 uM") are as the summary said.
