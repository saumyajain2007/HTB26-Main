"""WS5 frozen protocol: it must be impossible to freeze after the fact, or to move an input
without the verify step noticing.

Everything runs against a throwaway tree, so the real results/ws5_retrospective is never
written to by the tests.
"""

import json

import pytest
from eval.protocol import (DECLARATION, INPUTS, PROTOCOL, ProtocolError, amend,
                           declaration_sha256, existing_results, freeze, load,
                           missing_inputs, require_frozen, verify)

DIR = "results/ws5_retrospective"


@pytest.fixture
def tree(tmp_path):
    """A tree with the protocol and every declared input present."""
    (tmp_path / DIR).mkdir(parents=True)
    (tmp_path / DIR / "protocol.md").write_text("# protocol\n\nNo result exists.\n",
                                                encoding="utf-8")
    for rel in INPUTS:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"stand_in_for": rel}) + "\n", encoding="utf-8")
    return tmp_path


# ---------- freezing ----------

def test_freeze_pins_the_protocol_and_every_input(tree):
    record = freeze(tree)
    assert set(record["inputs_sha256"]) == set(INPUTS)
    assert len(record["protocol_sha256"]) == 64
    assert record["declaration_sha256"] == declaration_sha256(DECLARATION)
    assert record["amendments"] == []
    assert (tree / DIR / "preregistered.json").exists()


def test_the_frozen_record_is_what_load_returns(tree):
    record = freeze(tree)
    assert load(tree) == record


def test_verify_is_clean_right_after_freezing(tree):
    freeze(tree)
    assert verify(tree) == []
    assert require_frozen(tree)["protocol_sha256"]


# ---------- the refusals that make it a pre-registration ----------

def test_freezing_after_a_result_exists_is_refused(tree):
    (tree / DIR / "results.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ProtocolError, match="would not be .*pre-registered"):
        freeze(tree)


@pytest.mark.parametrize("name", ["results.json", "results.md"])
def test_any_result_file_blocks_the_freeze(tree, name):
    (tree / DIR / name).write_text("x", encoding="utf-8")
    assert existing_results(tree) == [name]
    with pytest.raises(ProtocolError):
        freeze(tree)


def test_refreezing_is_refused(tree):
    freeze(tree)
    with pytest.raises(ProtocolError, match="already exists"):
        freeze(tree)


def test_freezing_without_a_protocol_is_refused(tree):
    (tree / DIR / "protocol.md").unlink()
    with pytest.raises(ProtocolError, match="write the protocol before freezing"):
        freeze(tree)


def test_freezing_with_a_missing_input_is_refused(tree):
    (tree / INPUTS[0]).unlink()
    assert missing_inputs(tree) == [INPUTS[0]]
    with pytest.raises(ProtocolError, match="inputs do not exist"):
        freeze(tree)


# ---------- detecting drift ----------

def test_a_changed_protocol_is_caught(tree):
    freeze(tree)
    (tree / DIR / "protocol.md").write_text("# protocol\n\nreworded after the fact\n",
                                            encoding="utf-8")
    assert any("protocol.md has changed" in p for p in verify(tree))


@pytest.mark.parametrize("index", range(len(INPUTS)))
def test_a_changed_input_is_caught(tree, index):
    freeze(tree)
    (tree / INPUTS[index]).write_text('{"tuned": true}\n', encoding="utf-8")
    assert any(INPUTS[index] in p and "changed" in p for p in verify(tree))


def test_a_missing_input_is_caught_after_the_freeze(tree):
    freeze(tree)
    (tree / INPUTS[1]).unlink()
    assert any("pinned input is missing" in p for p in verify(tree))


def test_editing_the_declaration_in_place_is_caught(tree):
    """Rewriting the recorded declaration without re-hashing it is the obvious cheat."""
    freeze(tree)
    path = tree / DIR / "preregistered.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["declaration"]["metrics"]["primary"] = "hit_at_3"
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    assert any("edited in place" in p for p in verify(tree))


def test_require_frozen_raises_rather_than_returning_a_number(tree):
    freeze(tree)
    (tree / INPUTS[0]).write_text('{"tuned": true}\n', encoding="utf-8")
    with pytest.raises(ProtocolError, match="not in the state it was frozen in"):
        require_frozen(tree)


def test_verify_without_a_freeze_says_so(tree):
    assert any("has not been frozen" in p for p in verify(tree))
    with pytest.raises(ProtocolError):
        require_frozen(tree)


def test_a_corrupt_record_is_an_error_not_a_crash(tree):
    freeze(tree)
    (tree / DIR / "preregistered.json").write_text("not json", encoding="utf-8")
    assert any("not valid JSON" in p for p in verify(tree))


# ---------- amendments ----------

def test_an_amendment_appends_and_leaves_the_declaration_intact(tree):
    original = freeze(tree)
    record = amend("a cited row was wrong", "exclude row x and report both ways", tree)
    assert len(record["amendments"]) == 1
    assert record["amendments"][0]["reason"]
    assert record["amendments"][0]["change"]
    assert record["declaration"] == original["declaration"]
    assert record["protocol_sha256"] == original["protocol_sha256"]


def test_an_amendment_records_whether_a_result_already_existed(tree):
    freeze(tree)
    (tree / DIR / "results.json").write_text("{}", encoding="utf-8")
    record = amend("found after running", "note the exclusion", tree)
    assert record["amendments"][0]["results_existed"] == ["results.json"]


def test_an_amendment_without_a_reason_is_refused(tree):
    freeze(tree)
    with pytest.raises(ProtocolError, match="needs both a reason"):
        amend("  ", "something", tree)
    with pytest.raises(ProtocolError, match="needs both a reason"):
        amend("something", "  ", tree)


def test_amending_before_freezing_is_refused(tree):
    with pytest.raises(ProtocolError, match="has not been frozen"):
        amend("why", "what", tree)


# ---------- the declaration itself ----------

def test_the_declaration_names_a_primary_metric_that_is_also_reported():
    assert DECLARATION["metrics"]["primary"] in DECLARATION["metrics"]["reported"]


def test_the_declaration_reports_the_inverted_rate():
    """The metric that distinguishes a wrong answer from a near miss."""
    assert "inverted_rate" in DECLARATION["metrics"]["reported"]
    assert DECLARATION["metrics"]["inverted_rate"]


def test_the_declaration_has_baselines_including_the_tie_break_floor():
    assert {"random", "alphabetical", "evasion_only"} <= set(DECLARATION["baselines"])


def test_the_declaration_fixes_the_uncertainty_method_up_front():
    u = DECLARATION["uncertainty"]
    assert u["resamples"] > 0 and 0 < u["interval"] < 1 and u["method"]


def test_the_declaration_commits_to_reporting_negative_results():
    joined = " ".join(DECLARATION["rules"]).lower()
    assert "negative result stands" in joined
    assert "every attempt is reported" in joined


def test_the_shipped_protocol_states_that_no_result_exists():
    """The claim that makes a pre-registration meaningful, in the committed file."""
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "No result has been produced" in text
    for rel in INPUTS:
        assert rel in text, rel
