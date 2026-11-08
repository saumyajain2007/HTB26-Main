"""Tests for the oracle interface and the cost ledger (#88). Docking is faked; nothing is run."""

import json
import threading

import pytest

from htb_wholecell.oracles import (CostedOracle, DockingOracle, FilterOracle, Ledger, OracleError,
                                   OracleResult, identity)

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"


class Counting:
    name, fidelity, version = "counting", 3, "v1"

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def score(self, smiles):
        self.calls += 1
        if self.fail:
            raise ValueError("boom")
        return OracleResult(0.5, 0.1, {"k": 1})


def test_every_call_is_ledgered_with_measured_cost_and_provenance(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    oracle = CostedOracle(Counting(), ledger)
    oracle.call("c1", "CCO")
    (row,) = ledger.rows()
    assert (row["candidate_id"], row["oracle"], row["fidelity"], row["oracle_version"]) == ("c1", "counting", 3, "v1")
    assert row["seconds"] >= 0 and row["cache_hit"] is False and row["ok"] is True and row["score"] == 0.5
    assert row["hardware"] and row["inchikey"] == identity("CCO")


def test_cache_hit_is_free_logged_separately_and_survives_a_new_process(tmp_path):
    path, inner = tmp_path / "l.jsonl", Counting()
    CostedOracle(inner, Ledger(path)).call("a", "CCO")
    again = CostedOracle(inner, Ledger(path))            # a fresh wrapper rebuilds its cache from the ledger
    got = again.call("b", "OCC")                          # same molecule, written differently
    assert inner.calls == 1 and got.score == 0.5 and got.detail == {"k": 1}
    rows = Ledger(path).rows()
    assert [r["cache_hit"] for r in rows] == [False, True]
    s = Ledger(path).summary()["counting"]
    assert (s["calls"], s["cache_hits"]) == (2, 1)


def test_cache_can_be_switched_off_and_is_keyed_by_oracle_version(tmp_path):
    inner = Counting()
    wrapped = CostedOracle(inner, Ledger(tmp_path / "l.jsonl"), use_cache=False)
    wrapped.call("a", "CCO"); wrapped.call("a", "CCO")
    assert inner.calls == 2
    other = Counting(); other.version = "v2"
    CostedOracle(other, Ledger(tmp_path / "l.jsonl")).call("a", "CCO")
    assert other.calls == 1                                # a different version never reuses v1's answer


def test_a_failed_call_is_ledgered_with_its_cost_and_raises(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(OracleError, match="boom"):
        CostedOracle(Counting(fail=True), ledger).call("a", "CCO")
    (row,) = ledger.rows()
    assert row["ok"] is False and "ValueError" in row["error"] and row["seconds"] >= 0
    CostedOracle(Counting(), ledger).call("a", "CCO")      # and a failure is never served from the cache
    assert ledger.summary()["counting"]["failures"] == 1


def test_ledger_is_append_only_and_detects_edits_removals_and_reordering(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    oracle = CostedOracle(Counting(), ledger, use_cache=False)
    for i in range(4):
        oracle.call(f"c{i}", "CCO")
    assert ledger.verify() == []
    before = ledger.path.read_bytes()
    oracle.call("c4", "CCO")
    assert ledger.path.read_bytes().startswith(before)     # appending never rewrites earlier bytes

    lines = ledger.path.read_text().splitlines()
    edited = [json.loads(l) for l in lines]; edited[1]["seconds"] = 0.0
    ledger.path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in edited) + "\n")
    assert any("edited" in p for p in ledger.verify())

    ledger.path.write_text("\n".join(lines[:1] + lines[2:]) + "\n")
    assert any("removed or reordered" in p for p in ledger.verify())
    ledger.path.write_text("\n".join([lines[0], lines[2], lines[1]] + lines[3:]) + "\n")
    assert ledger.verify() != []


def test_concurrent_appends_keep_the_chain_intact(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    def work(n):
        for i in range(15):
            ledger.append(candidate_id=f"{n}-{i}", oracle="x", fidelity=0, seconds=0.0, cache_hit=False, ok=True)
    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(ledger.rows()) == 60 and ledger.verify() == []


def test_total_seconds_excludes_cache_hits_unless_asked(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(candidate_id="a", oracle="o", fidelity=0, seconds=2.0, cache_hit=False, ok=True)
    ledger.append(candidate_id="a", oracle="o", fidelity=0, seconds=0.5, cache_hit=True, ok=True)
    assert ledger.total_seconds("o") == 2.0 and ledger.total_seconds("o", include_cache_hits=True) == 2.5


def test_filter_oracle_gates_and_names_the_reason(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    oracle = CostedOracle(FilterOracle(), ledger)
    assert oracle.call("a", ABAUCIN).score == 1.0
    bad = oracle.call("b", "not a molecule")
    assert bad.score == 0.0 and bad.detail["stage"] == "validity"
    assert [r["fidelity"] for r in ledger.rows()] == [0, 0]


def _fake_runner(vina="1.2.7", best=(-7.2, -6.8), code=0):
    calls = []

    def run(cmd, env, timeout):
        calls.append(cmd)
        if cmd[-1] == "--toolchain":
            return 0, json.dumps({"vina": vina}), ""
        if code:
            return code, "", "Traceback ... something failed"
        out = cmd[cmd.index("--out") + 1]
        import pathlib
        pathlib.Path(out).mkdir(parents=True)
        pathlib.Path(out, "scores.json").write_text(json.dumps({
            "scores": [{"pose": i + 1, "score": s} for i, s in enumerate(best)],
            "toolchain": {"vina": vina}, "timing": {"total_s": 3.5}}))
        return 0, "", ""
    run.calls = calls
    return run


def _docking(tmp_path, runner):
    sd = tmp_path / "structures"; (sd / "3U2K").mkdir(parents=True)
    (sd / "settings.json").write_text(json.dumps({"exhaustiveness": 8, "seed": 42, "n_poses": 9}))
    return DockingOracle("3U2K", python="/dock/bin/python", worker_dir=tmp_path / "w", structures_dir=sd, runner=runner)


def test_docking_oracle_returns_negated_best_score_and_records_the_engine(tmp_path):
    runner = _fake_runner()
    ledger = Ledger(tmp_path / "l.jsonl")
    res = CostedOracle(_docking(tmp_path, runner), ledger).call("a", ABAUCIN)
    assert res.score == 7.2 and res.detail["best_vina_score"] == -7.2 and res.detail["engine_version"] == "1.2.7"
    (row,) = ledger.rows()
    assert row["oracle_version"] == "vina-1.2.7-ex8-seed42-3U2K" and row["fidelity"] == 1
    dock_cmd = [c for c in runner.calls if "--smiles" in c][0]
    assert dock_cmd[dock_cmd.index("--seed") + 1] == "42" and "--control" not in dock_cmd


def test_docking_failure_is_ledgered_and_raised(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(OracleError, match="exited 1"):
        CostedOracle(_docking(tmp_path, _fake_runner(code=1)), ledger).call("a", ABAUCIN)
    assert ledger.rows()[0]["ok"] is False
