from tests.conftest import FIXTURES
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import threading

import httpx
import openai
import pytest

from jury.client import (
    CortexModel, ModelReply, PROMPT_VERSION, RESPONSE_FORMAT, build_prompt, consensus, mock_model, run_jury,
    validate_config, validate_packet, validate_reply, visible_packet,
)


ROOT = Path(__file__).resolve().parents[3]
PACKET = json.loads((FIXTURES / "evidence_packet.json").read_text())
FIXTURE = json.loads((FIXTURES / "jury_result.json").read_text())
CONFIG = json.loads((ROOT / "core/jury/config.json").read_text())
RECORDED = json.loads((Path(__file__).parent / "data/live_recording.json").read_text())


def reply():
    return {"reviews": [{k: deepcopy(v) for k, v in r.items() if k != "candidate_id"}
                        for r in FIXTURE["jurors"][0]["reviews"]]}


def test_prompt_allowlist_and_no_input_ranking():
    packet = deepcopy(PACKET)
    for c in packet["candidates"]:
        c.update(network={"rank": 123}, rank=123, direct_evidence_rank=123,
                 selected_by=["network"], secret="forbidden")
    order = ["C4", "C2", "C1", "C3"]
    prompt = build_prompt(packet, order)
    visible = json.loads(prompt.split("Evidence packet:\n")[1])
    assert visible == visible_packet(packet, order)
    assert set(visible) == {"disease", "candidates", "evidence"}
    assert visible["disease"] == {"name": PACKET["disease"]["name"]}
    for c in visible["candidates"]:
        assert set(c) == {"label", "name", "targets", "evidence_ids", "safety_status"}
        assert all(set(t) == {"name", "mechanism"} for t in c["targets"])
    assert all(set(e) == {"id", "kind", "statement", "values"} for e in visible["evidence"])
    for forbidden in ("CHEMBL", "ENSG", "http", "source_id", "candidate_id", '"network":', "mean_distance", "degree_matched_z", "123", "secret"):
        assert forbidden not in prompt
    assert "rank" not in json.dumps(visible)
    assert "being investigated" in prompt and "do not endorse" in prompt
    for field in reply()["reviews"][0]:
        assert field in prompt


def test_seeded_orders_and_output_shape():
    result = run_jury(PACKET, CONFIG, mock_model)
    assert set(result) == set(FIXTURE)
    assert result["jury"] == {**CONFIG, 'prompt_version': PROMPT_VERSION,
                              'reasoning_effort': {model: None for model in CONFIG['models']}}
    assert PROMPT_VERSION == 'jury-v7'
    assert len(result["jurors"]) == 3
    for i, j in enumerate(result["jurors"]):
        order = [c["label"] for c in PACKET["candidates"]]
        random.Random(CONFIG["shuffle_seed"] + i).shuffle(order)
        assert j["presented_order"] == order
        assert j["status"] == "valid" and j["attempts"] == 1
        assert set(j) == set(FIXTURE["jurors"][0])
        assert j["token_usage"] == [{"attempt": 1, "input_tokens": None, "output_tokens": None}]
        assert set(j["reviews"][0]) == set(FIXTURE["jurors"][0]["reviews"][0])
        assert j["validation"]["errors"] == []
    again = run_jury(PACKET, CONFIG, mock_model)
    assert [j["presented_order"] for j in again["jurors"]] == [j["presented_order"] for j in result["jurors"]]
    assert len({tuple(j["presented_order"]) for j in result["jurors"]}) == 3



def test_on_juror_reports_each_juror_as_it_finishes():
    events = []

    def call(model, prompt, temperature):
        events.append(("asked", model))
        return mock_model(model, prompt, temperature)

    result = run_jury(PACKET, CONFIG, call, on_juror=lambda juror: events.append(("finished", juror)))
    expected = []
    for juror in result["jurors"]:
        expected += [("asked", juror["model"]), ("finished", juror)]
    assert events == expected

def test_concurrent_jurors_are_asked_at_the_same_time():
    """Each call waits until all three jurors have been asked: a juror-by-juror run
    would never get past the first call."""
    everyone_asked = threading.Barrier(len(CONFIG["models"]), timeout=5)
    finished = []

    def call(model, prompt, temperature):
        everyone_asked.wait()
        return mock_model(model, prompt, temperature)

    result = run_jury(PACKET, CONFIG, call, on_juror=finished.append, concurrent=True)
    assert [j["status"] for j in result["jurors"]] == ["valid"] * 3
    # Reported as each finished; returned in the configured order.
    assert sorted(j["model"] for j in finished) == sorted(CONFIG["models"])
    assert [j["model"] for j in result["jurors"]] == CONFIG["models"]
    sequential = run_jury(PACKET, CONFIG, mock_model)
    assert ([j["presented_order"] for j in result["jurors"]]
            == [j["presented_order"] for j in sequential["jurors"]])


def test_concurrent_jurors_share_the_call_budget_before_any_call():
    calls = []
    lock = threading.Lock()

    def invalid(model, prompt, temperature):
        with lock:
            calls.append(model)
        return 'incomplete JSON'

    result = run_jury(PACKET, CONFIG, invalid, max_calls=4, concurrent=True)
    assert Counter(calls) == Counter([CONFIG['models'][0], *CONFIG['models']])
    assert [j['attempts'] for j in result['jurors']] == [2, 1, 1]


def test_fixture_consensus_exactly():
    assert consensus(PACKET, FIXTURE["jurors"]) == FIXTURE["consensus"]
    for juror in FIXTURE["jurors"][:2]:
        value = {"reviews": [{k: v for k, v in r.items() if k != "candidate_id"}
                             for r in juror["reviews"]]}
        reviews, flags = validate_reply(json.dumps(value), PACKET)
        assert reviews == juror["reviews"] and not flags["errors"]


@pytest.mark.parametrize("change", [
    lambda v: v.update(extra=True),
    lambda v: v["reviews"][0].update(decision="safe"),
    lambda v: v["reviews"][0].update(direction="positive"),
    lambda v: v["reviews"][0].update(rank=True),
    lambda v: v["reviews"][0].update(rank=1.0),
    lambda v: v["reviews"][0].update(safety={"status": [], "evidence_ids": []}),
    lambda v: v["reviews"][0].update(missing_evidence="none"),
    lambda v: v["reviews"][0].update(candidate_id="CHEMBL2105759"),
    lambda v: v["reviews"][0].update(rank=2),
    lambda v: v["reviews"][0].update(rank=0),
    lambda v: v["reviews"][0].update(rank=5),
    lambda v: v["reviews"].pop(),
    lambda v: v["reviews"].append(deepcopy(v["reviews"][0])),
    lambda v: v["reviews"][0].update(label="C99"),
    lambda v: v["reviews"][0].update(supporting_evidence_ids=["E999"]),
    lambda v: v["reviews"][0].update(supporting_evidence_ids=["E1"]),
    lambda v: v["reviews"][0].update(supporting_evidence_ids=["E11"]),
    lambda v: v["reviews"][0]["safety"].update(status="unknown"),
    lambda v: v["reviews"][0]["safety"].update(evidence_ids=["E11"]),
    lambda v: v["reviews"][1]["safety"].update(evidence_ids=["E19"]),
    lambda v: v["reviews"][0].update(missing_evidence=["See E999."]),
    lambda v: v["reviews"][0].update(rationale="See E8."),
])
def test_invalid_replies_never_supply_reviews(change):
    value = reply()
    change(value)
    reviews, flags = validate_reply(json.dumps(value), PACKET)
    assert reviews is None and flags["errors"]


@pytest.mark.parametrize("raw", ["plain text", "[]", "null", "{}", '{"reviews":NaN}',
                                      '{"reviews":[],"reviews":[]}', None])
def test_bad_json(raw):
    reviews, flags = validate_reply(raw, PACKET)
    assert reviews is None and flags["schema"] is False


def test_recorded_claude_fence_and_identifiers():
    recorded = RECORDED["claude-sonnet-5"]
    assert recorded["validation"]["errors"] == [
        "Attempt 1: JSON decoding failed", "Attempt 2: JSON decoding failed"]
    reviews, flags = validate_reply(recorded["raw_output"], PACKET)
    assert reviews is not None and flags["errors"] == []
    assert "BCL2" in reviews[-1]["rationale"]
    assert "E19" in reviews[-1]["rationale"]


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "Here is my vote:\n{}\nEnd."])
def test_single_object_wrappers_preserve_validation(wrapper):
    raw = RECORDED["claude-sonnet-5"]["raw_output"][8:-4]
    assert validate_reply(wrapper.format(raw), PACKET)[0] is not None
    value = json.loads(raw)
    value["reviews"][0]["rank"] = 2  # Duplicate rank still rejects the entire ballot.
    assert validate_reply(wrapper.format(json.dumps(value)), PACKET)[0] is None


@pytest.mark.parametrize("wrapper", [
    "{}\n{}", "[{}]", '{{"broken": {}, "reviews": []',
    '{}\n{{"broken":', '{{"reviews":[],"reviews":[]}}\n{}',
])
def test_never_salvage_ambiguous_or_malformed_objects(wrapper):
    raw = RECORDED["claude-sonnet-5"]["raw_output"][8:-4]
    reviews, flags = validate_reply(wrapper.format(raw, raw), PACKET)
    assert reviews is None and flags["schema"] is False


@pytest.mark.parametrize("hyphen", ["-", "\u2010", "\u2011"])
@pytest.mark.parametrize("field", ["rationale", "objection"])
def test_recorded_gpt_numeric_text_with_typographic_identifier(hyphen, field):
    # The failed first GPT reply was not retained. Replay its retained second
    # ballot, varying only the typography of the packet's Bcl-2 identifier.
    value = {"reviews": [{k: v for k, v in r.items() if k != "candidate_id"}
                         for r in RECORDED["openai-gpt-5.4"]["reviews"]]}
    review = next(r for r in value["reviews"] if r["label"] == "C2")
    review[field] = review[field].replace("BCL2", "BCL" + hyphen + "2").replace("Bcl-2", "Bcl" + hyphen + "2")
    assert validate_reply(json.dumps(value), PACKET)[0] is not None
    review[field] += " Unsupported measurement 0.60000000000000001."
    reviews, flags = validate_reply(json.dumps(value), PACKET)
    assert reviews is None and flags["numbers_match"] is False


@pytest.mark.parametrize("text,accepted", [
    ("JAK1 and Bcl-2 are identifiers; association 0.80.", True),
    ("Association .8 or 8e-1.", True),
    ("Association 0.80000000000000001.", False),
    ("Association 0.9.", False),  # exists elsewhere in the packet, not in cited items
    ("Median 7.5 across 10 activities.", False),  # exists for Candidate, not cited
    ("Association −0.8.", False),
    ("Association 80%.", False),
    ("ChEMBL 37 records it.", False),  # release is not an evidence value
    ("Association 0.8 and 999.", False),
    ("An invented identifier dose-99.", False),
    ("An invented identifier JAK99.", False),
    ("JAK-1 is a hyphenated identifier; association 0.80.", True),
    ("An invented identifier JAK-99.", False),
])
@pytest.mark.parametrize("field", ["rationale", "objection"])
def test_exact_numbers_in_each_text_field(text, accepted, field):
    value = reply()
    value["reviews"][0][field] = text
    reviews, flags = validate_reply(json.dumps(value), PACKET)
    assert (reviews is not None) is accepted
    assert flags["numbers_match"] is accepted



@pytest.mark.parametrize("text,accepted", [
    # Kimi K3's live myeloma reply (25 Oct) for mirdametinib, a MAP2K1 and MAP2K2 inhibitor.
    ("A MAP2K1/2 inhibitor; association 0.80.", True),
    ("A MAP2K1/9 inhibitor; association 0.80.", False),  # MAP2K9 is not one of its Targets
    ("A MAP2K1/2/3 inhibitor; association 0.80.", False),
])
def test_slashed_family_names_whose_prefix_ends_in_digits_and_letters(text, accepted):
    packet = deepcopy(PACKET)
    targets = packet["candidates"][0]["targets"]
    targets[0]["name"], targets[1]["name"] = "MAP2K1", "MAP2K2"
    value = reply()
    value["reviews"][0]["rationale"] = text
    reviews, flags = validate_reply(json.dumps(value), packet)
    assert (reviews is not None) is accepted
    assert flags["numbers_match"] is accepted

def test_bioactivity_numbers():
    value = reply()
    value["reviews"][0].update(supporting_evidence_ids=["E8"],
                               rationale="Median 7.50 across 1e1 JAK1 activities.")
    assert validate_reply(json.dumps(value), PACKET)[0] is not None


@pytest.mark.parametrize("field", ["rationale", "objection"])
@pytest.mark.parametrize("text,flag", [
    ("Association 0.8e9999999999999999999.", "numbers_match"),
    ("", "schema"),
    (" \t\n ", "schema"),
], ids=["huge-exponent", "empty", "whitespace"])
def test_invalid_review_text_is_rejected_and_retried(field, text, flag):
    value = reply()
    value["reviews"][0][field] = text
    raw = json.dumps(value)
    reviews, validation = validate_reply(raw, PACKET)
    assert reviews is None and validation[flag] is False and validation["errors"]

    exhausted = run_jury(PACKET, CONFIG, lambda *args: raw)
    assert exhausted["consensus_status"]["jurors_counted"] == 0
    for juror in exhausted["jurors"]:
        assert juror["status"] == "invalid" and juror["reviews"] is None
        assert juror["attempts"] == CONFIG["max_attempts"]
        assert juror["raw_output"] == raw
        assert len(juror["validation"]["errors"]) == CONFIG["max_attempts"]

    calls = {}
    def recover(model, *args):
        calls[model] = calls.get(model, 0) + 1
        return raw if calls[model] == 1 else json.dumps(reply())
    recovered = run_jury(PACKET, CONFIG, recover)
    assert recovered["consensus"]["jurors_counted"] == len(CONFIG["models"])
    assert all(j["status"] == "valid" and j["attempts"] == 2 for j in recovered["jurors"])


def test_retry_recovery_and_exhaustion():
    calls = CounterCalls()
    result = run_jury(PACKET, CONFIG, calls)
    assert all(j["status"] == "valid" and j["attempts"] == 2 for j in result["jurors"])
    assert all(j["validation"]["errors"] == ["Attempt 1: JSON decoding failed"] for j in result["jurors"])
    invalid = run_jury(PACKET, CONFIG, lambda *args: "last raw reply")
    assert invalid["consensus"] is None
    assert invalid["consensus_status"] == {"jurors_counted": 0,
                                           "failed_jurors": CONFIG["models"],
                                           "reason": "fewer_than_two_valid_jurors"}
    for j in invalid["jurors"]:
        assert j["status"] == "invalid" and j["reviews"] is None
        assert j["raw_output"] == "last raw reply" and j["attempts"] == 2
        assert len(j["validation"]["errors"]) == 2


class CounterCalls:
    def __init__(self):
        self.calls = {}

    def __call__(self, model, prompt, temperature):
        self.calls[model] = self.calls.get(model, 0) + 1
        return "invalid" if self.calls[model] == 1 else json.dumps(reply())


def test_failures_do_not_leak_secrets_or_fabricate_votes():
    def fail(*args):
        raise RuntimeError("secret PAT should never be recorded")
    result = run_jury(PACKET, CONFIG, fail)
    assert "secret PAT" not in json.dumps(result)
    assert result["consensus_status"]["jurors_counted"] == 0
    for j in result["jurors"]:
        assert j["status"] == "failed" and j["attempts"] == 2
        assert j["reviews"] is None and j["raw_output"] is None


def test_insufficient_jurors_and_single_candidate():
    assert consensus(PACKET, FIXTURE["jurors"][:1])["kendalls_w"] is None
    packet = deepcopy(PACKET)
    packet["candidates"] = packet["candidates"][:1]
    result = run_jury(packet, CONFIG, mock_model)
    assert result["consensus"]["kendalls_w"] is None
    assert result["consensus"]["ranking"][0]["borda_points"] == 0


def test_unanimous_and_opposite_rankings():
    juror = deepcopy(FIXTURE["jurors"][0])
    assert consensus(PACKET, [juror, juror])["kendalls_w"] == 1.0
    opposite = deepcopy(juror)
    for review in opposite["reviews"]:
        review["rank"] = len(PACKET["candidates"]) + 1 - review["rank"]
    result = consensus(PACKET, [juror, opposite])
    assert result["kendalls_w"] == 0.0
    assert [r["rank"] for r in result["ranking"]] == [1, 1, 1, 1]
    assert {r["borda_points"] for r in result["ranking"]} == {3}


def test_mixed_failures_retain_last_reply():
    calls = {}
    def model_call(model, *args):
        calls[model] = calls.get(model, 0) + 1
        if calls[model] == 1:
            return "last raw reply"
        raise TimeoutError("private request details")
    result = run_jury(PACKET, CONFIG, model_call)
    for juror in result["jurors"]:
        assert juror["status"] == "invalid"
        assert juror["raw_output"] == "last raw reply"
        assert juror["reviews"] is None
        assert juror["validation"]["errors"] == [
            "Attempt 1: JSON decoding failed", "Attempt 2: call failed (TimeoutError)"]


def test_bad_packet_and_config_fail_before_calls():
    packet = deepcopy(PACKET)
    packet["candidates"][1]["label"] = "C1"
    with pytest.raises(ValueError, match="duplicate"):
        validate_packet(packet)
    packet = deepcopy(PACKET)
    packet["candidates"][0]["safety_status"] = "unknown"
    with pytest.raises(ValueError, match="safety"):
        validate_packet(packet)
    for key, bad in (("models", ["a"]), ("models", ["a", "a", "b"]),
                     ("max_attempts", 0), ("shuffle_seed", True)):
        with pytest.raises(ValueError):
            validate_config({**CONFIG, key: bad})


def test_sdk_endpoint_auth_config_model_and_no_hidden_retries(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_PAT", "fake-test-token")
    real_openai = openai.OpenAI
    calls = []
    def handle(request):
        calls.append(request)
        assert str(request.url) == "https://test-account.snowflakecomputing.com/api/v2/cortex/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fake-test-token"
        body = json.loads(request.content)
        assert body["model"] == "configured-model" and body["temperature"] == 0
        assert body["response_format"] == RESPONSE_FORMAT
        schema = body["response_format"]["json_schema"]["schema"]
        assert schema["required"] == ["reviews"] and schema["additionalProperties"] is False
        review_schema = schema["properties"]["reviews"]["items"]
        assert set(review_schema["required"]) == set(reply()["reviews"][0])
        assert set(review_schema["properties"]) == set(reply()["reviews"][0])
        return httpx.Response(200, json={"id": "test", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]})
    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        return real_openai(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(openai, "OpenAI", factory)
    client = CortexModel()
    try:
        assert client("configured-model", "test prompt", 0) == ModelReply("OK")
    finally:
        client.close()
    assert len(calls) == 1


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5", "openai-gpt-5.4", "glm-5.3"])
@pytest.mark.parametrize("candidate_count", [0, 15, 100])
def test_endpoint_routing_structured_output_and_usage(monkeypatch, model, candidate_count):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_PAT", "fake-test-token")
    monkeypatch.setenv("SNOWFLAKE_REASONING_EFFORT", json.dumps({model: "low"}))
    real_openai = openai.OpenAI
    calls = []
    raw = json.dumps(reply())
    prompt = "test prompt"
    if candidate_count:
        prompt += "\nEvidence packet:\n" + json.dumps({"candidates": [{}] * candidate_count})
    def handle(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer fake-test-token"
        assert request.extensions["timeout"]["read"] == 300
        body = json.loads(request.content)
        if model.startswith('claude-'):
            assert body['output_config']['effort'] == 'low'
        else:
            assert body['reasoning_effort'] == 'low'
        assert body["model"] == model
        assert body["messages"] == [{"role": "user", "content": prompt}]
        if model.startswith("claude-"):
            assert str(request.url) == "https://test-account.snowflakecomputing.com/api/v2/cortex/v1/messages"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert body["max_tokens"] == min(32768, max(4096, 1024 * candidate_count))
            assert "temperature" not in body  # Opus 5.5 rejects sampling parameters.
            assert "response_format" not in body
            assert body["output_config"] == {"effort": "low", "format": {
                "type": "json_schema", "schema": RESPONSE_FORMAT["json_schema"]["schema"]}}
            return httpx.Response(200, json={"content": [
                {"type": "thinking", "thinking": "This is not part of the vote."},
                {"type": "text", "text": raw[:20]}, {"type": "text", "text": raw[20:]}],
                "usage": {"input_tokens": 123, "output_tokens": 456}, "stop_reason": "end_turn"})
        assert str(request.url) == "https://test-account.snowflakecomputing.com/api/v2/cortex/v1/chat/completions"
        if model.startswith('openai-gpt-5'):
            assert 'temperature' not in body
        else:
            assert body["temperature"] == 0
        assert body["max_completion_tokens"] == 32768
        assert "anthropic-version" not in request.headers
        assert body["response_format"] == RESPONSE_FORMAT
        assert "output_config" not in body
        return httpx.Response(200, json={"id": "test", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": raw}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 456, "total_tokens": 579}})
    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        return real_openai(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(openai, "OpenAI", factory)
    client = CortexModel()
    try:
        result = client(model, prompt, 0)
    finally:
        client.close()
    assert result == ModelReply(raw, input_tokens=123, output_tokens=456,
        max_output_tokens=min(32768, max(4096, 1024 * candidate_count)) if model.startswith("claude-") else None,
        stop_reason="end_turn" if model.startswith("claude-") else None)
    assert validate_reply(result.text, PACKET)[0] is not None
    assert len(calls) == 1


def test_recorded_cross_candidate_numbers_still_reject():
    raw = (Path(__file__).parent / "data/gpt_cross_candidate_vote.json").read_text()
    reviews, flags = validate_reply(raw, PACKET)
    assert reviews is None and flags["numbers_match"] is False
    assert flags["errors"] == ["C2: unsupported or unparseable number in rationale"]
    value = json.loads(raw)
    c2 = next(r for r in value["reviews"] if r["label"] == "C2")
    c2["rationale"] = c2["rationale"].replace("scores of 0.8 or 0.9", "stronger association evidence")
    assert validate_reply(json.dumps(value), PACKET)[0] is not None
    assert "Compare Candidates qualitatively" in build_prompt(PACKET, ["C1", "C2", "C3", "C4"])


@pytest.mark.parametrize("outcomes,expected_status,expected_usage", [
    ([ModelReply("invalid", 10, 2), ModelReply(json.dumps(reply()), 20, 30)], "valid", [(10, 2), (20, 30)]),
    ([TimeoutError("private"), ModelReply(json.dumps(reply()), 20, 30)], "valid", [(None, None), (20, 30)]),
    ([ModelReply("invalid", 10, 2), TimeoutError("private")], "invalid", [(10, 2), (None, None)]),
])
def test_usage_retained_for_every_attempt(outcomes, expected_status, expected_usage):
    calls = {}
    def model_call(model, *args):
        index = calls.get(model, 0)
        calls[model] = index + 1
        outcome = outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    result = run_jury(PACKET, CONFIG, model_call)
    for juror in result["jurors"]:
        assert juror["status"] == expected_status and juror["attempts"] == 2
        assert juror["token_usage"] == [
            {"attempt": i, "input_tokens": counts[0], "output_tokens": counts[1]}
            for i, counts in enumerate(expected_usage, 1)]
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("configured,explicit,expected", [(None, None, 300), ("420", None, 420), ("420", 180, 180)])
def test_recorded_glm_timeout_budget(monkeypatch, configured, explicit, expected):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_PAT", "fake-test-token")
    if configured is None:
        monkeypatch.delenv("SNOWFLAKE_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("SNOWFLAKE_TIMEOUT_SECONDS", configured)
    glm = RECORDED["glm-5.3"]
    assert glm["validation"]["errors"] == [
        "Attempt 1: call failed (APITimeoutError)", "Attempt 2: call failed (APITimeoutError)"]
    assert glm["raw_output"] is None
    observed_timeout = glm["latency_ms"] / glm["attempts"] / 1000
    recovered = glm["recovered_vote"]
    completion_seconds = recovered["latency_ms"] / 1000
    assert completion_seconds > observed_timeout > 60
    real_openai = openai.OpenAI
    calls = []
    def handle(request):
        calls.append(request)
        # Simulate a slow completion without sleeping or spending live credit.
        budget = request.extensions["timeout"]["read"]
        if budget <= completion_seconds:
            raise httpx.ReadTimeout("simulated slow-model timeout", request=request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": recovered["reply"]}]})
        return httpx.Response(200, json={"id": "recorded", "choices": [
            {"index": 0, "message": {"role": "assistant", "content":
             recovered["reply"]}, "finish_reason": "stop"}]})
    def factory(**kwargs):
        assert kwargs["timeout"] == expected and kwargs["max_retries"] == 0
        return real_openai(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(openai, "OpenAI", factory)
    client = CortexModel(timeout=explicit)
    try:
        result = run_jury(PACKET, {**CONFIG, "models": list(RECORDED)}, client)
    finally:
        client.close()
    assert len(calls) == 3
    assert all(j["status"] == "valid" and j["attempts"] == 1 for j in result["jurors"])


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "bad"])
def test_invalid_timeout(monkeypatch, timeout):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_PAT", "fake-test-token")
    monkeypatch.setenv("SNOWFLAKE_TIMEOUT_SECONDS", timeout)
    with pytest.raises(ValueError):
        CortexModel()


def test_cli_mock(tmp_path):
    out = tmp_path / "new-directory" / "result.json"
    process = subprocess.run([sys.executable, "-m", "jury",
                              str(FIXTURES / "evidence_packet.json"), "--out", str(out), "--mock"],
                             cwd=ROOT, capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    result = json.loads(out.read_text())
    assert result["consensus"]["jurors_counted"] == 3
    assert all("Mock review" in j["reviews"][0]["rationale"] for j in result["jurors"])


@pytest.mark.network
def test_one_real_cortex_call():
    if not all(os.environ.get(k) for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_PAT", "SNOWFLAKE_MODELS")):
        pytest.skip("Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_PAT and SNOWFLAKE_MODELS")
    config = {**CONFIG, "models": json.loads(os.environ["SNOWFLAKE_MODELS"])}
    validate_config(config)
    client = CortexModel()
    try:
        text = client(config["models"][0], "Reply with the single word OK", config["temperature"]).text
        assert isinstance(text, str) and text.strip()
    finally:
        client.close()


def test_recorded_covid_objection_requires_its_measurement_citations():
    case = json.loads((Path(__file__).parent / 'data/covid_gpt_citations.json').read_text())
    packet, value = case['packet'], case['reply']
    reviews, flags = validate_reply(json.dumps(value), packet)
    assert reviews is None
    assert flags['errors'] == ['C9: unsupported or unparseable number in objection']
    # Both numbers were supplied, but E68 (STAT3) and E70 (BMP2K) were omitted.
    value['reviews'][0]['contradicting_evidence_ids'] = ['E68', 'E70']
    assert validate_reply(json.dumps(value), packet)[0] is not None
    value['reviews'][0]['objection'] += ' The dose is 99 mg.'
    assert validate_reply(json.dumps(value), packet)[0] is None


def test_retry_explains_validation_failure_without_changing_packet():
    seen = {}
    def model_call(model, prompt, temperature):
        prompts = seen.setdefault(model, [])
        prompts.append(prompt)
        if len(prompts) == 1:
            return 'incomplete JSON'
        assert prompt.startswith('Your previous reply failed validation: JSON decoding failed')
        assert json.loads(prompt.split('Evidence packet:\n', 1)[1]) == json.loads(
            prompts[0].split('Evidence packet:\n', 1)[1])
        return mock_model(model, prompt, temperature)
    result = run_jury(PACKET, CONFIG, model_call)
    assert all(j['status'] == 'valid' and j['attempts'] == 2 for j in result['jurors'])


def test_total_call_budget_reserves_one_attempt_per_juror():
    calls = []
    def invalid(model, prompt, temperature):
        calls.append(model)
        return 'incomplete JSON'
    result = run_jury(PACKET, CONFIG, invalid, max_calls=4)
    assert calls == [CONFIG['models'][0], CONFIG['models'][0], *CONFIG['models'][1:]]
    assert [j['attempts'] for j in result['jurors']] == [2, 1, 1]
    assert all(j['status'] == 'invalid' for j in result['jurors'])
    assert all('Total jury call budget exhausted; no further retry' in j['validation']['errors']
               for j in result['jurors'][1:])
    with pytest.raises(ValueError, match='at least one attempt'):
        run_jury(PACKET, CONFIG, invalid, max_calls=2)


def test_v4_research_scope_and_explicit_citation_fields():
    prompt = build_prompt(PACKET, [c['label'] for c in PACKET['candidates']])
    assert 'retrospective evidence-review exercise using supplied public data' in prompt
    assert 'no advice for any patient' in prompt
    assert 'approvals may concern other Diseases' in prompt
    assert 'Inline citations do not populate these arrays' in prompt
    assert 'All fields are required' in prompt
    assert 'including non-numeric claims' in prompt


def test_recorded_opus_refusal_is_invalid_and_not_a_token_limit():
    case = json.loads((Path(__file__).parent / 'data/covid_jury_failures.json').read_text())
    usage = case['opus_usage'][1]
    assert usage['stop_reason'] == 'refusal'
    assert usage['output_tokens'] == 690 < usage['max_output_tokens'] == 15360
    reviews, flags = validate_reply(case['opus_refusal']['raw_output'], case['packet'])
    assert reviews is None and flags['errors'] == ['JSON decoding failed']


def test_recorded_kimi_citations_remain_required_in_v4():
    import re

    case = json.loads((Path(__file__).parent / 'data/covid_jury_failures.json').read_text())
    value = json.loads(case['kimi']['raw_output'])
    missing = {}
    for review in value['reviews']:
        cited = set(review['supporting_evidence_ids'] + review['contradicting_evidence_ids']
                    + review['safety']['evidence_ids'])
        for field in ('rationale', 'objection', 'missing_evidence'):
            ids = set(re.findall(r'\bE[0-9]+\b', json.dumps(review[field]))) - cited
            if ids:
                missing[(review['label'], field)] = ids
    assert missing == {
        ('C2', 'rationale'): {'E104'}, ('C4', 'rationale'): {'E44', 'E46'},
        ('C4', 'objection'): {'E55'}, ('C12', 'objection'): {'E87', 'E88'},
        ('C7', 'objection'): {'E114'}, ('C5', 'rationale'): {'E93', 'E95'},
        ('C3', 'objection'): {'E121'},
    }
    reviews, flags = validate_reply(json.dumps(value), case['packet'])
    assert reviews is None and not flags['numbers_match']
    for review in value['reviews']:
        for field, array in (('rationale', 'supporting_evidence_ids'),
                             ('objection', 'contradicting_evidence_ids')):
            review[array].extend(sorted(missing.get((review['label'], field), set())))
    assert validate_reply(json.dumps(value), case['packet'])[0] is not None
    value['reviews'][0]['objection'] += ' An invented dose of 99 mg.'
    assert validate_reply(json.dumps(value), case['packet'])[0] is None


@pytest.mark.parametrize('override', [False, True])
def test_saved_effort_matches_effective_provider_settings(monkeypatch, override):
    monkeypatch.setenv('SNOWFLAKE_ACCOUNT', 'test-account')
    monkeypatch.setenv('SNOWFLAKE_PAT', 'fake-test-token')
    models = ['claude-opus-5-5', 'openai-gpt-5.4', 'kimi-k3']
    configured = {models[0]: None, models[1]: 'low', models[2]: 'low'}
    expected = {models[0]: 'low', models[1]: None, models[2]: 'low'} if override else configured
    if override:
        monkeypatch.setenv('SNOWFLAKE_REASONING_EFFORT', json.dumps(expected))
    else:
        monkeypatch.delenv('SNOWFLAKE_REASONING_EFFORT', raising=False)
    real_openai = openai.OpenAI
    observed = {}

    def handle(request):
        body = json.loads(request.content)
        model = body['model']
        effort = body.get('output_config', {}).get('effort') if model.startswith('claude-') else body.get('reasoning_effort')
        observed[model] = effort
        if model.startswith('claude-'):
            return httpx.Response(200, json={'content': [{'type': 'text', 'text': json.dumps(reply())}]})
        return httpx.Response(200, json={'id': 'test', 'choices': [
            {'index': 0, 'message': {'role': 'assistant', 'content': json.dumps(reply())}, 'finish_reason': 'stop'}]})

    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: real_openai(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))))
    config = {**CONFIG, 'models': models, 'reasoning_effort': configured}
    before = deepcopy(config)
    client = CortexModel(reasoning_effort=configured)
    try:
        result = run_jury(PACKET, config, client)
    finally:
        client.close()
    assert config == before
    assert observed == result['jury']['reasoning_effort'] == expected
    assert {k: v for k, v in result['jury'].items() if k not in {'reasoning_effort', 'prompt_version'}} == {
        k: v for k, v in config.items() if k not in {'reasoning_effort', 'prompt_version'}}
    assert all(j['status'] == 'valid' for j in result['jurors'])


@pytest.mark.parametrize('effort', [None, [], {'unknown-model': 'low'}, {'mock-family-a': ''},
                                   {'mock-family-a': 1}])
def test_invalid_effort_configuration(effort):
    with pytest.raises(ValueError, match='reasoning_effort'):
        validate_config({**CONFIG, 'reasoning_effort': effort})


def test_legacy_config_saves_provider_defaults():
    config = {k: v for k, v in CONFIG.items() if k != 'reasoning_effort'}
    result = run_jury(PACKET, config, mock_model)
    assert result['jury']['reasoning_effort'] == {model: None for model in config['models']}
    assert 'reasoning_effort' not in config


@pytest.mark.parametrize('raw', ['', '{"reviews":[', json.dumps(reply())])
def test_provider_refusal_is_never_a_json_error_or_a_vote(raw):
    result = run_jury(PACKET, CONFIG, lambda *args: ModelReply(
        raw, input_tokens=10, output_tokens=2, stop_reason='refusal'))
    for juror in result['jurors']:
        assert juror['status'] == 'invalid' and juror['reviews'] is None
        assert juror['raw_output'] == raw
        assert juror['validation'] == {
            'schema': None, 'unique_ranks': None, 'evidence_ids_exist': None,
            'numbers_match': None,
            'errors': [f'Attempt {i}: refused (provider stop_reason=refusal)'
                       for i in range(1, CONFIG['max_attempts'] + 1)],
        }
        assert all(u['stop_reason'] == 'refusal' and u['input_tokens'] == 10
                   for u in juror['token_usage'])


def test_refusal_retry_preserves_order_and_runs_all_validation():
    prompts = {}
    def call(model, prompt, temperature):
        prompts.setdefault(model, []).append(prompt)
        if len(prompts[model]) == 1:
            return ModelReply('{"reviews":[', stop_reason='refusal')
        value = reply()
        value['reviews'][0]['rationale'] = 'Invented measurement 999999.'
        return ModelReply(json.dumps(value), stop_reason='end_turn')
    result = run_jury(PACKET, CONFIG, call)
    for juror in result['jurors']:
        assert prompts[juror['model']][0] == prompts[juror['model']][1]
        assert juror['status'] == 'invalid' and juror['reviews'] is None
        assert juror['validation']['numbers_match'] is False
        assert juror['validation']['errors'][0].endswith('stop_reason=refusal)')
        assert 'unsupported or unparseable number' in juror['validation']['errors'][1]


def test_refusal_can_recover_with_a_complete_validated_reply():
    calls = {}
    def call(model, prompt, temperature):
        calls[model] = calls.get(model, 0) + 1
        return (ModelReply('', stop_reason='refusal') if calls[model] == 1
                else ModelReply(json.dumps(reply()), stop_reason='end_turn'))
    result = run_jury(PACKET, CONFIG, call)
    assert all(j['status'] == 'valid' and j['attempts'] == 2 for j in result['jurors'])
    assert all(j['validation']['errors'] == [
        'Attempt 1: refused (provider stop_reason=refusal)'] for j in result['jurors'])


def test_v7_changes_only_the_research_framing():
    prompt = build_prompt(PACKET, ['C1', 'C2', 'C3', 'C4'])
    assert 'retrospective evidence-review exercise' in prompt
    assert 'no advice for any patient' in prompt
    assert 'priorities for further investigation' in prompt
    assert 'not as\nrecommendations' in prompt
    assert 'Missing warnings\nmean unknown, never safe' in prompt


@pytest.mark.parametrize('valid_count', [0, 1, 2, 3])
def test_consensus_requires_two_and_counts_every_valid_juror(valid_count):
    jurors = []
    for index in range(3):
        juror = deepcopy(FIXTURE['jurors'][index % 2])
        juror['model'] = f'juror-{index}'
        if index >= valid_count:
            juror.update(status='failed' if index % 2 else 'invalid', reviews=None)
        jurors.append(juror)
    result = consensus(PACKET, jurors)
    assert result['jurors_counted'] == valid_count
    assert result['failed_jurors'] == [j['model'] for j in jurors[valid_count:]]
    if valid_count < 2:
        assert result['ranking'] == [] and result['kendalls_w'] is None
        assert result['reason'] == 'fewer_than_two_valid_jurors'
    else:
        assert result['reason'] is None
        ranks = {c['label']: [] for c in PACKET['candidates']}
        for juror in jurors[:valid_count]:
            for review in juror['reviews']:
                ranks[review['label']].append(review['rank'])
        points = {label: sum(4 - rank for rank in values) for label, values in ranks.items()}
        assert {r['label']: r['borda_points'] for r in result['ranking']} == points
        s = sum((sum(values) - valid_count * 2.5) ** 2 for values in ranks.values())
        assert result['kendalls_w'] == round(12 * s / (valid_count ** 2 * (4 ** 3 - 4)), 4)


@pytest.mark.parametrize('valid_count', [0, 1, 2, 3])
def test_jury_serializes_null_consensus_and_preserves_failure_metadata(valid_count):
    config = {**CONFIG, 'max_attempts': 1}
    def call(model, prompt, temperature):
        if config['models'].index(model) >= valid_count:
            return ModelReply('', stop_reason='refusal')
        return mock_model(model, prompt, temperature)
    result = run_jury(PACKET, config, call)
    assert result['consensus_status'] == {
        'jurors_counted': valid_count,
        'failed_jurors': config['models'][valid_count:],
        'reason': 'fewer_than_two_valid_jurors' if valid_count < 2 else None,
    }
    if valid_count < 2:
        assert result['consensus'] is None
        assert json.loads(json.dumps(result))['consensus'] is None
    else:
        assert result['consensus'] == consensus(PACKET, result['jurors'])


@pytest.mark.parametrize('valid_count', [0, 1])
def test_a6_receipts_and_comparison_handle_refusal_and_null_consensus(tmp_path, monkeypatch, valid_count):
    from pipeline import a6

    monkeypatch.setenv('SNOWFLAKE_MODELS', json.dumps(CONFIG['models']))
    monkeypatch.delenv('SNOWFLAKE_REASONING_EFFORT', raising=False)
    calls = []
    class RefusingClient:
        reasoning_effort = {}
        def __call__(self, model, prompt, temperature):
            calls.append(model)
            if CONFIG['models'].index(model) < valid_count:
                return mock_model(model, prompt, temperature)
            return ModelReply('{"reviews":[', stop_reason='refusal')
        def close(self):
            pass
    monkeypatch.setattr(a6, 'CortexModel', RefusingClient)
    manifest = {'diseases': {}}
    for disease_id in a6.DISEASES:
        folder = tmp_path / disease_id
        folder.mkdir()
        a6.write(folder / 'evidence_packet.json', PACKET)
        manifest['diseases'][disease_id] = {
            'packet_sha256': a6.digest(folder / 'evidence_packet.json')}
    a6.write(tmp_path / 'manifest.json', manifest)
    a6.live(tmp_path)
    assert len(calls) == a6.CALL_BUDGET
    for receipt in a6.read(tmp_path / 'live_calls.json'):
        if CONFIG['models'].index(receipt['model']) < valid_count:
            assert receipt['status'] == 'valid'
            continue
        assert receipt['status'] == 'invalid'
        assert receipt['validation']['schema'] is None
        assert receipt['validation']['errors'] == ['refused (provider stop_reason=refusal)']
    result = a6.read(tmp_path / a6.DISEASES[0] / 'jury_result.json')
    assert result['consensus'] is None
    candidates = a6.read(FIXTURES / 'candidates.json')['candidates']
    network = {'disease': PACKET['disease'], 'candidates': candidates,
               'shortlist': [c['candidate_id'] for c in candidates]}
    before = deepcopy(result)
    comparison = a6.compare(network, PACKET, result,
                            a6.read(FIXTURES / 'drug_targets.json'))
    assert result == before
    assert comparison['jurors_counted'] == valid_count
    assert comparison['failed_jurors'] == CONFIG['models'][valid_count:]
    assert comparison['consensus_reason'] == 'fewer_than_two_valid_jurors'
    assert comparison['kendalls_w'] is None
    assert all(r['borda_rank'] is None and r['borda_points'] is None
               for r in comparison['rows'])
    result['consensus_status']['jurors_counted'] = 2
    with pytest.raises(ValueError, match='metadata'):
        a6.compare(network, PACKET, result, a6.read(FIXTURES / 'drug_targets.json'))
