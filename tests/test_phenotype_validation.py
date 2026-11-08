"""WS5b scoring logic on synthetic pairs: counts, metrics, the cluster bootstrap and the freeze."""
import json

import numpy as np
import pytest

from eval import phenotype_validation as pv


def pair(species, cluster, drug, pheno, a="unaffected", b=None):
    status = {arm: a for arm in pv.ARMS}
    if b:
        status["B"] = status["B-intact"] = b
    return {"species": species, "cluster": cluster, "drug": drug, "pheno": pheno, "pool": True, "status": status}


def test_parse_ast_drops_conflicting_calls():
    calls, conflicts = pv.parse_ast("a=R,b=S,a=S,c=I")
    assert calls == {"b": "S", "c": "I"} and conflicts == ["a"]


def test_metrics_from_counts():
    m = pv.metrics([30, 10, 50, 10])  # tp fp tn fn
    assert m["sensitivity"] == pytest.approx(0.75)
    assert m["specificity"] == pytest.approx(50 / 60)
    assert m["ppv_ruled_out"] == pytest.approx(0.75)
    assert m["false_reassurance"] == pytest.approx(10 / 60)
    assert m["balanced_accuracy"] == pytest.approx((0.75 + 50 / 60) / 2)


def test_prediction_rules():
    p = pair("klebsiella", "c1", "MEROPENEM", "R", a="partly_affected")
    prior = {("klebsiella", "MEROPENEM"): "S"}
    assert pv.prediction(p, "A|class", prior) == "R"
    assert pv.prediction(p, "A|strict", prior) == "S"
    assert pv.prediction(p, "never_ruled_out", prior) == "S"
    assert pv.prediction(p, "drug_prior", prior) == "S"


def test_drug_prior_tie_predicts_susceptible():
    pairs = [pair("klebsiella", "c1", "X", "R"), pair("klebsiella", "c2", "X", "S")]
    assert pv.drug_prior(pairs)[("klebsiella", "X")] == "S"


def perfect_and_noisy():
    pairs = []
    for sp in pv.SPECIES:
        for k in range(12):
            res = k % 2 == 0
            pairs.append(pair(sp, f"{sp}{k}", "D", "R" if res else "S", a="defeated" if res else "unaffected"))
            pairs.append(pair(sp, f"{sp}{k}", "E", "R" if res else "S", a="defeated" if res else "unaffected"))
    return pairs


def test_perfect_rule_scores_perfectly_and_beats_the_never_baseline():
    out = pv.evaluate_scope(perfect_and_noisy(), "pool")
    a = out["strata"]["pooled"]["A|class"]
    assert a["balanced_accuracy"]["value"] == 1.0 and a["false_reassurance"]["value"] == 0.0
    assert out["strata"]["pooled"]["never_ruled_out"]["balanced_accuracy"]["value"] == 0.5
    assert out["differences"]["pooled"]["A-class minus drug_prior"]["value"] > 0


def test_bootstrap_is_reproducible_and_clustered():
    one, two = pv.evaluate_scope(perfect_and_noisy(), "pool"), pv.evaluate_scope(perfect_and_noisy(), "pool")
    assert one == two
    # three species with 12 clusters each: the pooled count reflects whole clusters only
    cells = pv.cluster_counts(perfect_and_noisy(), "pool")["klebsiella"]["A|class"]
    assert cells.shape == (12, 4) and cells.sum() == 24


def test_a_useless_rule_has_no_signal():
    rng = np.random.default_rng(1)
    pairs = [pair(sp, f"{sp}{k % 15}", f"D{k % 3}", "R" if rng.random() < .5 else "S",
                  a="defeated" if rng.random() < .5 else "unaffected")
             for sp in pv.SPECIES for k in range(300)]
    pooled = pv.evaluate_scope(pairs, "pool")["strata"]["pooled"]["A|class"]["balanced_accuracy"]
    assert pooled["ci95"][0] < 0.5 < pooled["ci95"][1]


def test_catalogue_scope_includes_drugs_outside_the_pool():
    pairs = [pair("klebsiella", "c1", "COLISTIN", "R", a="defeated")]
    pairs[0]["pool"] = False
    assert pv.evaluate_scope(pairs, "pool")["strata"]["klebsiella"]["A|class"]["n_pairs"] == 0
    assert pv.evaluate_scope(pairs, "catalogue")["strata"]["klebsiella"]["A|class"]["n_pairs"] == 1


def test_freeze_verify_amend(tmp_path, monkeypatch):
    for rel in pv.FROZEN_FILES.values():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    out = tmp_path / "pre.json"
    pv.freeze(tmp_path, out)
    assert pv.verify(tmp_path, out) == []
    (tmp_path / pv.FROZEN_FILES["protocol"]).write_text("changed")
    assert pv.verify(tmp_path, out) == ["protocol changed since the freeze"]
    with pytest.raises(SystemExit):
        pv.freeze(tmp_path, out)  # a freeze is not redone
    record = pv.amend("fix", tmp_path, out)
    assert record["amendments"][0]["changed"] == ["protocol"] and pv.verify(tmp_path, out) == []
    assert json.loads(out.read_text())["sha256"]["protocol"] != record["amendments"][0]["sha256"]["protocol"]
