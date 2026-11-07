# Calibrated property limits (`antibiotic_relaxed`)

The smoke test and the Lean certificates check six molecular properties against a rule set. `antibiotic_relaxed` was a set of placeholder numbers. It is now calibrated on the approved antibiotics in the catalogue. This page records the method and the result so they can be rebuilt and challenged.

```
uv run python -m htb_verify.calibrate data/antibiotics/releases/chembl-37_card-4.0.2
```

Code: [core/verify/htb_verify/calibrate.py](../core/verify/htb_verify/calibrate.py). The numbers live in [rules.py](../core/verify/htb_verify/rules.py) and [Rules.lean](../core/verify/lean/HtbVerify/Rules.lean); a test fails if they differ from each other, and from the committed record [calibration/antibiotic_relaxed.json](../core/verify/calibration/antibiotic_relaxed.json) (written by the command above with `--record`). Another test, which needs the catalogue data, checks that record against a fresh run.

## Method

1. Take the approved antibiotics in the catalogue: ChEMBL `max_phase` 4, not withdrawn, with a structure. That is 126 drugs in ChEMBL 37.
2. Compute each descriptor with the RDKit functions the smoke test uses.
3. Per descriptor, take the 95th percentile by the nearest-rank method.
4. Round up to a clean step: 50 Da, 0.5 logP, 1 donor, 1 acceptor, 1 rotatable bond, 10 Å².
5. Never go below the oral Lipinski and Veber limit. The Lean file proves the antibiotic limits are no stricter than the oral ones.

Choosing cutoffs that cover most of a reference set of drugs is the idea behind Lipinski et al. 2001; the percentile (95) and the steps are our choices. O'Shea and Moser 2008 (*J. Med. Chem.* 51, 2871) is the background for why antibacterial property space differs from other drugs. Both citations were written from memory and have not been re-read for this page. Check them before the writeup.

## Result

| Rule | 95th percentile | Rounded up | Oral floor | Limit | Old placeholder |
|---|---|---|---|---|---|
| Molecular weight (Da) | 834.5 | 850 | 500 | **850** | 1200 |
| Crippen logP | 3.62 | 4.0 | 5.0 | **5.0** (oral floor) | 5.0 |
| H-bond donors | 13 | 13 | 5 | **13** | 12 |
| H-bond acceptors | 17 | 17 | 10 | **17** | 20 |
| Rotatable bonds | 13 | 13 | 10 | **13** | 15 |
| Polar surface area (Å²) | 336.4 | 340 | 140 | **340** | 250 |

The synthetic-accessibility ceiling (6.5, soft, never a failure) was not calibrated.

Joint pass rate (all six rules): the calibrated limits pass 119 of the 126 approved drugs; the old placeholders passed 112. For the 76 phase 2 and 3 antibiotics in the same catalogue, which are not used to set the limits, 73 pass (placeholders: 68).

## What this does and does not say

- It describes where 95% of approved antibiotics sit on each property. It is a "looks like an approved antibiotic" filter.
- It is not a validation. The approved set sets the limits, so most of it passes by construction. The phase 2 and 3 drugs are a rough check only: they are mostly analogues of the approved classes, so they are not independent.
- It says nothing about safety, selectivity, activity or Gram-negative entry. A failure flags an outlier (vancomycin, daptomycin and the other large glycopeptides and lipopeptides), not a bad drug.
- Large natural-product antibiotics are rare in the set, so the limits are tighter for them than the old placeholders. Passing is not required to be ranked: the property check is the last of the three ranking keys.
- The set is dominated by older drug classes. Novel chemotypes may sit outside it for good reasons.
