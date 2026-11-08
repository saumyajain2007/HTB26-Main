"""Tests for the generation wrapper (#86). SyntheMol itself is not run here."""

import csv
import json
from pathlib import Path

import pytest

from htb_wholecell import generate, leakage

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"
ANALOGUE = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)Cl)cc3)CC2)O1"
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
CAFFEINE = "Cn1cnc2c1c(=O)n(C)c(=O)n2C"


def _tsv(path: Path, rows: list[dict]):
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def release(tmp_path):
    t = tmp_path / "tables"
    t.mkdir()
    liu = [{"inchikey": "K1", "smiles": ASPIRIN, "label": "0"},
           {"inchikey": "K2", "smiles": CAFFEINE, "label": "1"},
           {"inchikey": "K3", "smiles": ANALOGUE, "label": "1"},       # an analogue of the held-out compound
           {"inchikey": "K4", "smiles": "CCCCO", "label": "0"}]        # in the calibration set
    _tsv(t / "liu_train.tsv", liu)
    _tsv(t / "splits.tsv", [{"source": "liu_train", "inchikey": r["inchikey"], "scaffold": "",
                             "scaffold_split": "calibration" if r["inchikey"] == "K4" else "train",
                             "random_split": "train", "year_split": ""} for r in liu])
    _tsv(t / "hub_pool.tsv", [{"inchikey": "H1", "smiles": ABAUCIN, "names": "RS-102895;abaucin", "broad_ids": "b",
                               "n_samples": "1", "in_liu_sd2": "1", "source": "hub_samples"}])
    return tmp_path


def test_held_out_lookup_by_hub_name_and_unknown_name_is_an_error(release):
    assert generate.held_out_smiles(release, ["RS-102895"]) == {"RS-102895": ABAUCIN}
    with pytest.raises(ValueError, match="not in the Hub pool"):
        generate.held_out_smiles(release, ["nonsense"])


def test_training_rows_are_train_split_only_and_purged_of_analogues(release):
    held = generate.held_out_smiles(release, ["RS-102895"])
    kept, removed = generate.training_rows(release, held)
    assert [r["inchikey"] for r in kept] == ["K1", "K2"]            # K4 is calibration, K3 purged
    assert [r["inchikey"] for r in removed] == ["K3"]


def test_planted_leak_in_the_building_blocks_stops_generation():
    held = {"RS-102895": ABAUCIN}
    generate.assert_generator_inputs_clean(held, [ASPIRIN], ["CCO", "NCCN"])
    with pytest.raises(leakage.LeakageError, match="generator_seeds"):
        generate.assert_generator_inputs_clean(held, [ASPIRIN], ["CCO", ANALOGUE])
    with pytest.raises(leakage.LeakageError, match="training"):
        generate.assert_generator_inputs_clean(held, [ASPIRIN, ABAUCIN + ".Cl"], ["CCO"])


def _molecules(path: Path, smiles: list[str]):
    with path.open("w", newline="") as h:
        w = csv.writer(h)
        w.writerow(["smiles", "score", "building_block_smiles"])
        for i, s in enumerate(smiles):
            w.writerow([s, f"0.{i}", "x;y"])


def test_import_dedupes_drops_invalid_and_leaks_and_adds_novelty(tmp_path):
    csvp = tmp_path / "molecules.csv"
    _molecules(csvp, [CAFFEINE, "OC(=O)C", "OCC", "CCO", "not a molecule", ANALOGUE, ABAUCIN])
    train = [{"smiles": CAFFEINE, "label": "1"}, {"smiles": ASPIRIN, "label": "0"}]
    rows, counts = generate.import_generated(csvp, held_out={"RS-102895": ABAUCIN}, train_rows=train,
                                             batch="t1", seed=3)
    assert counts == {"raw": 7, "invalid": 1, "duplicate": 1, "leak_removed": 2, "kept": 3}
    assert all(r["source"] == "generated" and r["rng_seed"] == 3 and r["batch"] == "t1" for r in rows)
    assert [r["id"] for r in rows] == ["gen-t1-000000", "gen-t1-000001", "gen-t1-000002"]
    from htb_wholecell.chem import standardise
    caf = next(r for r in rows if r["inchikey"] == standardise(CAFFEINE)[1])
    assert caf["max_sim_train"] == 1.0                      # identical to a training molecule: novelty 1.0 means "not novel"


def test_import_is_deterministic(tmp_path):
    csvp = tmp_path / "m.csv"
    _molecules(csvp, ["OCC", "NCCN", "CCCl"])
    a = generate.import_generated(csvp, held_out={"h": ABAUCIN}, train_rows=[{"smiles": ASPIRIN, "label": "0"}], batch="b", seed=0)
    b = generate.import_generated(csvp, held_out={"h": ABAUCIN}, train_rows=[{"smiles": ASPIRIN, "label": "0"}], batch="b", seed=0)
    assert a == b


def test_write_batch_records_provenance_and_table_checksum(tmp_path):
    csvp = tmp_path / "m.csv"
    _molecules(csvp, ["OCC", "NCCN"])
    rows, _ = generate.import_generated(csvp, held_out={"h": ABAUCIN}, train_rows=[{"smiles": ASPIRIN, "label": "0"}], batch="b", seed=0)
    generate.write_batch(tmp_path / "out", rows, {"synthemol": "1.0.4", "n_rollout": 20})
    prov = json.loads((tmp_path / "out" / "provenance.json").read_text())
    assert prov["rows"] == 2 and prov["synthemol"] == "1.0.4" and len(prov["table_sha256"]) == 64
    assert (tmp_path / "out" / "generated.tsv").read_text().splitlines()[0].split("\t")[:4] == ["id", "inchikey", "smiles", "source"]
