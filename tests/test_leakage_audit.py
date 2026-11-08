"""Each audit, run on small synthetic inputs with a planted leak that must flip it to `fail`."""
import csv
import sqlite3
from pathlib import Path

import pytest

from eval import leakage_audit as la
from eval import phenotype_validation as pv

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"
ANALOGUE = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)Cl)cc3)CC2)O1"
POOL = ["CCO", "CCN", "c1ccccc1", "CC(=O)Oc1ccccc1C(=O)O", "CCCCCC(=O)O", "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
        "OC(=O)c1ccccc1O", "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "NCCc1ccc(O)c(O)c1", "OCC1OC(O)C(O)C(O)C1O",
        "CCCCCCCC", "CC(C)O", "CCOC(C)=O", "c1ccncc1", "CC(=O)N"]


def key(smiles):
    from htb_wholecell import leakage
    return leakage._key(smiles)


def write(path: Path, header, rows, delimiter="\t"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h, delimiter=delimiter, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def make_model(tmp_path, *, cal_overlap=False, test_in_train=False):
    model = tmp_path / "model"
    test_smiles, train_smiles, cal_smiles = POOL[:5], POOL[5:12], POOL[12:]
    if test_in_train:
        train_smiles = train_smiles + [test_smiles[0]]
    cal_rows = [(key(s), s, i % 2, 0.5, 0.1) for i, s in enumerate(cal_smiles)]
    if cal_overlap:
        cal_rows.append((key(test_smiles[1]), test_smiles[1], 0, 0.5, 0.1))
    test_rows = [(key(s), s, i % 2, 0.2 + 0.6 * (i % 2), 0.1) for i, s in enumerate(test_smiles)]
    write(model / "predictions_test.tsv", ["inchikey", "smiles", "label", "mean", "std"], test_rows)
    write(model / "predictions_calibration.tsv", ["inchikey", "smiles", "label", "mean", "std"], cal_rows)
    write(model / "member_0" / "train.csv", ["smiles", "label", "split"],
          [(s, i % 2, "train") for i, s in enumerate(train_smiles)], ",")
    return model


# ----------------------------------------------------------------------------- ensemble

def test_ensemble_clean_inputs_do_not_fail(tmp_path):
    r = la.audit_ensemble(make_model(tmp_path), n_boot=20)
    assert r["status"] in ("pass", "warn") and r["problems"] == []
    assert r["performance"]["all"]["n"] == 5


def test_ensemble_calibration_test_overlap_fails(tmp_path):
    r = la.audit_ensemble(make_model(tmp_path, cal_overlap=True), n_boot=20)
    assert r["status"] == "fail" and "calibration and test" in r["problems"][0]


def test_ensemble_test_compound_in_training_fails(tmp_path):
    r = la.audit_ensemble(make_model(tmp_path, test_in_train=True), n_boot=20)
    assert r["status"] == "fail" and "training and test" in r["problems"][0]


def test_ensemble_a_close_analogue_makes_it_a_warning_not_a_pass(tmp_path):
    model = make_model(tmp_path)
    rows = [(key(ANALOGUE), ANALOGUE, 1, 0.9, 0.1)]
    write(model / "predictions_test.tsv", ["inchikey", "smiles", "label", "mean", "std"], rows)
    write(model / "member_0" / "train.csv", ["smiles", "label", "split"], [(ABAUCIN, 1, "train")], ",")
    assert la.audit_ensemble(model, n_boot=20)["status"] == "warn"


def test_ensemble_missing_files_are_skipped_with_a_reason(tmp_path):
    r = la.audit_ensemble(tmp_path / "nope")
    assert r["status"] == "skipped" and "predictions_test.tsv" in r["reason"]


# ----------------------------------------------------------------------------- cluster split

def test_cluster_split_writes_a_file_and_asserts_no_close_neighbour(tmp_path):
    smiles = [ABAUCIN, ANALOGUE, *POOL]
    table = tmp_path / "t" / "mic.tsv"
    write(table, ["inchikey", "smiles", "label"], [(key(s), s, i % 2) for i, s in enumerate(smiles)])
    write(table.with_name("splits.tsv"), ["inchikey", "scaffold_split"],
          [(key(s), "train" if i % 2 else "test") for i, s in enumerate(smiles)])
    r = la.audit_cluster_split(table, out_dir=tmp_path / "out")
    assert r["status"] == "pass"
    assert (tmp_path / "out" / "splits_cluster.tsv").exists()
    # the analogue pair (indices 0 and 1) went to different sets under the scaffold split: a leak
    assert r["test_share_with_training_neighbour"]["scaffold_split"] > 0
    assert r["test_share_with_training_neighbour"]["similarity_group_split"] == 0.0
    rows = list(csv.DictReader((tmp_path / "out" / "splits_cluster.tsv").open(), delimiter="\t"))
    by_key = {x["inchikey"]: x["cluster_split"] for x in rows}
    assert by_key[key(ABAUCIN)] == by_key[key(ANALOGUE)]


def test_cluster_split_missing_input_is_skipped(tmp_path):
    assert la.audit_cluster_split(tmp_path / "none.tsv")["status"] == "skipped"


# ----------------------------------------------------------------------------- ground truth

def chembl_with(tmp_path, doi, with_mic):
    db = tmp_path / "chembl.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE docs (doc_id INTEGER, doi TEXT, pubmed_id INTEGER)")
        c.execute("CREATE TABLE activities (activity_id INTEGER, doc_id INTEGER, standard_type TEXT)")
        c.execute("INSERT INTO docs VALUES (1, ?, NULL)", (doi,))
        if with_mic:
            c.execute("INSERT INTO activities VALUES (1, 1, 'MIC'), (2, 1, 'IC50')")
    return db


def ground_truth_with(tmp_path, doi):
    import json
    path = tmp_path / "gt.json"
    path.write_text(json.dumps({"sources": {"a": {"type": "doi", "id": doi}, "b": {"type": "citation", "id": "x"}}}))
    return path


def test_ground_truth_source_with_mic_records_fails(tmp_path):
    r = la.audit_ground_truth(ground_truth_with(tmp_path, "10.1/ABC"), chembl_with(tmp_path, "10.1/abc", True))
    assert r["status"] == "fail" and r["mic_records_in_those_documents"] == 1


def test_ground_truth_source_without_mic_records_passes(tmp_path):
    r = la.audit_ground_truth(ground_truth_with(tmp_path, "10.1/abc"), chembl_with(tmp_path, "10.1/abc", False))
    assert r["status"] == "pass" and r["chembl_documents_matched"] == 1


def test_ground_truth_unmatched_source_passes(tmp_path):
    r = la.audit_ground_truth(ground_truth_with(tmp_path, "10.9/zzz"), chembl_with(tmp_path, "10.1/abc", True))
    assert r["status"] == "pass" and r["chembl_documents_matched"] == 0


# ----------------------------------------------------------------------------- generated

def hub_release(tmp_path):
    rel = tmp_path / "release"
    write(rel / "tables" / "hub_pool.tsv", ["names", "smiles"], [("RS-102895", ABAUCIN), ("SU3327", "CCO")])
    return rel


def test_generated_batch_with_an_analogue_fails(tmp_path):
    survivors = tmp_path / "s.tsv"
    write(survivors, ["id", "smiles"], [("g1", "CCCCCCCC"), ("g2", ANALOGUE)])
    r = la.audit_generated(survivors, hub_release(tmp_path))
    assert r["status"] == "fail" and r["leaks"][0]["member"] == ANALOGUE


def test_generated_clean_batch_passes(tmp_path):
    survivors = tmp_path / "s.tsv"
    write(survivors, ["id", "smiles"], [("g1", "CCCCCCCC"), ("g2", "c1ccncc1")])
    assert la.audit_generated(survivors, hub_release(tmp_path))["status"] == "pass"


# ----------------------------------------------------------------------------- phenotype

def synthetic_ast(tmp_path, projects_per_species=8):
    for key_, (binomial, filename) in pv.SPECIES.items():
        rows = []
        for p in range(projects_per_species):
            for k in range(5):
                rows.append((binomial, "x=R", f"{key_}-{p}-{k}", f"PRJ-{key_}-{p}", "mecA", "1"))
        write(tmp_path / filename, ["scientific_name", "AST_phenotypes", "biosample_acc", "bioproject_acc",
                                    "AMR_genotypes_core", "number_core_amr_genes"], rows)
    return tmp_path


def test_phenotype_split_is_disjoint_by_bioproject(tmp_path):
    r = la.audit_phenotype(synthetic_ast(tmp_path))
    assert r["isolates"] == 120 and r["status"] in ("pass", "warn")
    for v in r["by_species"].values():
        assert v["dev"] + v["test"] == 40


def test_phenotype_one_dominant_bioproject_is_a_warning(tmp_path):
    synthetic_ast(tmp_path, projects_per_species=1)
    assert la.audit_phenotype(tmp_path)["status"] == "warn"


def test_phenotype_missing_data_is_skipped(tmp_path):
    assert la.audit_phenotype(tmp_path / "none")["status"] == "skipped"


# ----------------------------------------------------------------------------- the runner

def test_a_raised_control_is_reported_as_a_failed_audit_and_exit_code_one(tmp_path, monkeypatch):
    from htb_wholecell import controls

    def boom():
        raise controls.ControlError("planted")
    monkeypatch.setitem(la.AUDITS, "ground_truth", boom)
    report = la.run(["ground_truth"], tmp_path)
    assert report["audits"]["ground_truth"] == {"status": "fail", "problems": ["planted"]}
    assert la.main(["--only", "ground_truth", "--out", str(tmp_path)]) == 1


def test_skipped_audits_do_not_fail_the_run(tmp_path, monkeypatch):
    monkeypatch.setitem(la.AUDITS, "generated", lambda: {"status": "skipped", "reason": "no data"})
    assert la.main(["--only", "generated", "--out", str(tmp_path)]) == 0
    assert "skipped" in (tmp_path / "report.md").read_text()
