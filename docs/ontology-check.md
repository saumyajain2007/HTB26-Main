# Ontology type check (issue #10)

Run 2026-11-07 against CARD 4.0.2 and NCBI Taxonomy, before the contracts are treated as frozen. The aim is the check that [results/ERRATA.md](../results/ERRATA.md) says was missed for diseases: confirm each id is the kind of thing the field means, not just that the name looks right. Code: [typecheck.py](../core/resistance/htb_resistance/typecheck.py). Tests: [test_typecheck.py](../core/resistance/tests/test_typecheck.py). Rerun with `uv run pytest core/resistance/tests/test_typecheck.py` (add `-m network` for the pathogens).

| What | Expected type | Checked | Result |
| --- | --- | --- | --- |
| Pathogens: *S. aureus* 1280, *A. baumannii* 470, *K. pneumoniae* 573 | NCBI rank SPECIES, name matches | NCBI Datasets taxonomy | All three are species with the expected names |
| Genes in the profile fixture (`ARO:3000617` mecA, `ARO:3003296` S. aureus gyrA) | Descends from `ARO:3000000` determinant of antibiotic resistance | `is_a` ancestry | Pass |
| Mechanisms (`ARO:0001001`, `ARO:0001002`) | Resistance Mechanism category | CARD categories | Pass |
| Defeated classes (`ARO:0000001`, `ARO:0000032`, `ARO:3000008`, `ARO:3007157`) | Drug Class category | CARD categories | Pass |
| Drug names: linezolid (CHEMBL126), vancomycin (CHEMBL262777), oxacillin (CHEMBL819) | Small molecule, preferred name matches, ATC J01 antibacterial | ChEMBL 37 directly, and CARD's ChEMBL cross-references (`ARO:0000072`, `ARO:0000028`, `ARO:0000056`) | Pass in both. Phase 4, first approvals 2000, 1964, 1971 |
| Candidate drug classes | Drug Class term with an ARO id | CARD categories | **Two wrong, corrected** |

## Corrected

In `tests/fixtures/antibiotic_candidates.json` the drug classes of linezolid and vancomycin had `aro_id: null` and a name only. The contract says to join on ids, so a null id would have made those classes invisible to the evasion rule. Linezolid's name, "oxazolidinone", was also not CARD's term.

| Candidate | Was | Now |
| --- | --- | --- |
| Linezolid | `null`, "oxazolidinone" | `ARO:3000079`, "oxazolidinone antibiotic" |
| Vancomycin | `null`, "glycopeptide antibiotic" | `ARO:3000081`, "glycopeptide antibiotic" |

Nothing else changed, and evasion statuses are unaffected (neither class is in the profile's `defeated_classes`).

## Notes for later

- Three CARD Drug Class terms are not under `ARO:1000003` antibiotic molecule: `ARO:0000044` cephamycin, `ARO:3000054` acridine dye, `ARO:3005179` diazabicyclooctanes ANT3310. Test drug classes by the Drug Class category, not by ancestry. The checker already does.
- A gene's `ARO:` id from a gene-name lookup can be a determinant or a *variant model* (for example `ARO:3003296` is a gyrA variant model, not the gyrA gene family). Both are determinants. Profiling (#16) should keep the model id and not collapse it to the family.
- Only the ids in the contract fixtures were checked. The pathogen set is still a proposal in tasks.md; if a different species is chosen, add its taxid to `PATHOGENS` and rerun. Species presets, the antibiotic catalogue and the ground-truth table should be run through `check_term`, `check_drug` and `check_taxon` when they exist, before they are frozen.
- Vancomycin's InChIKey in the fixtures is `MYPYJXKWCTUITO-UHFFFAOYSA-N`, from a SMILES without stereochemistry. ChEMBL's is `MYPYJXKWCTUITO-LYRMYLQWSA-N`. The first block matches, so the structure is the same, but a join on the full key between the fixtures and ChEMBL would miss it. Join on the ChEMBL id, or on the first block. Linezolid and oxacillin keys match ChEMBL exactly. Not changed, because the vancomycin certificate is real `core/verify` output for that key.
- The ChEMBL test reads `data/chembl_extract/chembl_37/chembl_37_sqlite/chembl_37.db` (30 GB, gitignored) and is skipped when it is absent: `mkdir data/chembl_extract && tar -xzf data/chembl_37_sqlite.tar.gz -C data/chembl_extract chembl_37/chembl_37_sqlite/chembl_37.db`.
