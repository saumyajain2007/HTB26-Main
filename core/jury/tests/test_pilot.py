from tests.conftest import FIXTURES
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from jury.client import ModelReply, mock_model, validate_reply
from jury.pilot import (MAX_CALLS, MODELS, freeze, leakage_matches, recovery,
                        run_pilot, score)

PACKET = json.loads((FIXTURES / "evidence_packet.json").read_text())


def prepare(tmp_path):
    panels = []
    for i, disease_id in enumerate(("MONDO_0008383", "MONDO_0005148", "MONDO_0005180")):
        packet = deepcopy(PACKET)
        packet["disease"] = {"id": disease_id, "name": f"Disease {i}"}
        (tmp_path / f"packet-{disease_id}.json").write_text(json.dumps(packet))
        panels.append({"disease": {**packet["disease"], "area": "area"},
                       "true_drug": {"drug_id": packet["candidates"][0]["candidate_id"], "name": "Drug", "target_count": 1}})
    (tmp_path / "panels.json").write_text(json.dumps({"panels": panels}))
    return freeze(tmp_path)


def model_reply(model, prompt):
    return ModelReply(mock_model(model, prompt.rsplit("\n", 1)[0], 0), 20, 30)


def test_runner_scoring_audit_and_environment(tmp_path, monkeypatch):
    declaration = prepare(tmp_path)
    monkeypatch.setenv("SNOWFLAKE_MODELS", "original")
    calls = []
    def call(model, prompt):
        assert json.loads(os.environ["SNOWFLAKE_MODELS"]) == [model]
        calls.append(model)
        return model_reply(model, prompt)
    run_pilot(tmp_path, call, declaration)
    assert len(calls) == 15
    assert os.environ["SNOWFLAKE_MODELS"] == "original"
    run_pilot(tmp_path, call, declaration)
    assert len(calls) == 15
    result = score(tmp_path)
    assert result["total_attempts"] == 15
    assert result["jury"]["complete_panels"] == 3
    assert all(s["valid_reply_rate"] == 1 and s["input_tokens"] == 60 for s in result["models"].values())
    import csv
    rows = list(csv.DictReader((tmp_path / "audit_sample.csv").open()))
    assert len(rows) == 30 and Counter(r["model"] for r in rows) == {m: 6 for m in MODELS}
    assert all(r["supported_by_citation (yes/no)"] == "" and r["note"] == "" for r in rows)
    assert all(r["cited E IDs"] and r["the cited statements"] for r in rows)
    assert any("warning" in r["the cited statements"].lower() for r in rows)
    first = (tmp_path / "audit_sample.csv").read_bytes()
    score(tmp_path)
    assert (tmp_path / "audit_sample.csv").read_bytes() == first
    assert result["chance"]["mrr"] == pytest.approx(.2212152662)


def test_retry_budget_durable_resume_and_secret_safe_errors(tmp_path):
    declaration = prepare(tmp_path)
    calls = []
    def fail(model, prompt):
        calls.append(model)
        raise RuntimeError("secret MUST NOT BE SAVED")
    run_pilot(tmp_path, fail, declaration)
    assert len(calls) == MAX_CALLS
    run_pilot(tmp_path, fail, declaration)
    assert len(calls) == MAX_CALLS
    records = [json.loads(p.read_text()) for p in (tmp_path / "runs").glob("*.json")]
    assert sum(len(r["attempts"]) for r in records) == 25
    assert all(len(r["attempts"]) <= 2 for r in records)
    assert all("MUST NOT BE SAVED" not in p.read_text() for p in (tmp_path / "runs").glob("*.json"))
    result = score(tmp_path)
    assert result["total_attempts"] == 25
    assert result["jury"]["mrr"] == 0
    assert result["audit_rows"] == 0
    assert all(n == 6 for n in result["audit_shortfalls"].values())
    assert all(s["missing_usage_attempts"] == s["attempts"] for s in result["models"].values())


def test_frozen_inputs_cannot_change(tmp_path):
    declaration = prepare(tmp_path)
    assert freeze(tmp_path) == declaration
    path = tmp_path / "packet-MONDO_0008383.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="Frozen"):
        freeze(tmp_path)


def test_recovery_failure_denominator_and_leakage():
    assert recovery(None, "CHEMBL1") == {"rank": None, "hits_at_5": 0, "reciprocal_rank": 0}
    assert recovery([{"candidate_id": "CHEMBL1", "rank": 5}], "CHEMBL1")["hits_at_5"] == 1
    assert recovery([{"candidate_id": "CHEMBL1", "rank": 6}], "CHEMBL1")["reciprocal_rank"] == 1/6
    assert leakage_matches("Approved for rheumatoid arthritis.", ["rheumatoid arthritis"])
    assert not leakage_matches("Target is associated with rheumatoid arthritis.", ["rheumatoid arthritis"])
    assert leakage_matches("Already used to treat RA.", ["RA"])


@pytest.mark.parametrize("decisions,valid", [
    (["investigate", "watch", "watch", "deprioritise"], True),
    (["watch", "watch", "watch", "watch"], True),
    (["watch", "investigate", "watch", "deprioritise"], False),
    (["investigate", "deprioritise", "watch", "deprioritise"], False),
    (["deprioritise", "watch", "watch", "investigate"], False),
])
def test_decision_rank_order_is_by_rank_not_array_order(decisions, valid):
    value = json.loads(mock_model("mock", "Evidence packet:\n" + json.dumps({
        "disease": PACKET["disease"], "candidates": PACKET["candidates"], "evidence": PACKET["evidence"]}), 0))
    for review, decision in zip(value["reviews"], decisions):
        review["decision"] = decision
    value["reviews"].reverse()
    reviews, validation = validate_reply(json.dumps(value), PACKET)
    assert (reviews is not None) is valid
    assert ("Decisions must not improve as rank gets worse" in validation["errors"]) is not valid


def test_pilot_adapter_keeps_reasoning_client_and_expands_anthropic_cap():
    from jury.pilot import call_model
    class Client:
        def __init__(self):
            self.client = self
            self.body = None
        def post(self, path, *, cast_to, body, options):
            assert path == "/messages"
            self.body = body
            return {"content": [{"type": "text", "text": "reply"}],
                    "usage": {"input_tokens": 11, "output_tokens": 12}}
        def __call__(self, model, prompt, temperature):
            # GLM/Kimi go through CortexModel, which reads reasoning effort from env.
            return ModelReply(model, 13, 14)
    client = Client()
    assert call_model(client, MODELS[0], "prompt") == ModelReply("reply", 11, 12)
    assert client.body["max_tokens"] == 12000 and "temperature" not in client.body
    for model in MODELS[-2:]:
        assert call_model(client, model, "prompt").text == model


def test_partial_jury_has_no_full_jury_score_or_agreement(tmp_path):
    declaration = prepare(tmp_path)
    def call(model, prompt):
        if model == "openai-gpt-5.4" and '"Disease 0"' in prompt:
            raise RuntimeError("unavailable")
        return model_reply(model, prompt)
    run_pilot(tmp_path, call, declaration)
    result = score(tmp_path)
    assert result["jury"]["complete_panels"] == 2
    partial = result["jury"]["per_disease"][0]
    assert partial["consensus"]["jurors_counted"] == 2
    assert partial["consensus"]["kendalls_w"] is None
    assert partial["rank"] is None and partial["reciprocal_rank"] == 0


def test_interruption_is_journalled_as_consumed_failure(tmp_path):
    declaration = prepare(tmp_path)
    def interrupt(model, prompt):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run_pilot(tmp_path, interrupt, declaration)
    record = json.loads(next((tmp_path / "runs").glob("*.json")).read_text())
    assert len(record["attempts"]) == 1
    attempt = record["attempts"][0]
    assert attempt["status"] == "failed" and attempt["error"]["type"] == "InterruptedRequest"
    assert attempt["latency_ms"] is not None


def test_uniform_revalidation_preserves_receipt_verdict(tmp_path):
    from jury.pilot import revalidate_runs, rejection_counts
    case = json.loads((Path(__file__).parent / 'data/pilot_numeric/opus_new_family.json').read_text())
    disease = case['packet']['disease']['id']
    (tmp_path / f'packet-{disease}.json').write_text(json.dumps(case['packet']))
    (tmp_path / 'runs').mkdir()
    path = tmp_path / 'runs/record.json'
    receipt = {'errors': ['C3: unsupported or unparseable number in rationale']}
    path.write_text(json.dumps({'disease_id': disease, 'model': MODELS[0], 'attempts': [{
        'raw_output': case['attempts'][0]['raw_output'], 'reviews': None,
        'validation': receipt, 'status': 'invalid'}]}))
    revalidate_runs(tmp_path)
    attempt = json.loads(path.read_text())['attempts'][0]
    assert attempt['status'] == 'valid' and attempt['validation']['errors'] == []
    assert attempt['status_at_receipt'] == 'invalid' and attempt['validation_at_receipt'] == receipt
    assert rejection_counts([attempt]) == {}
    first = path.read_bytes()
    revalidate_runs(tmp_path)
    assert path.read_bytes() == first


def _v2_fixture(tmp_path):
    from pipeline.panels import blind_packet
    packet = deepcopy(PACKET)
    packet['candidates'] = []
    aliases = {}
    for i in range(15):
        c = deepcopy(PACKET['candidates'][i % 4])
        old_name = c['name']
        c.update(candidate_id=f'CHEMBL{7000000+i}', label=f'C{i+1}', name=f'MockDrug{i+1}')
        packet['candidates'].append(c)
        aliases[c['candidate_id']] = [c['name'], f'MockTrade{i+1}', c['candidate_id'], old_name]
    panels = []
    for i in range(6):
        did = f'MONDO_{9000000+i}'
        named = deepcopy(packet)
        named['disease'] = {'id': did, 'name': f'Synthetic Disease {i}'}
        (tmp_path / f'packet-{did}.json').write_text(json.dumps(named))
        (tmp_path / f'blind-{did}.json').write_text(json.dumps(blind_packet(named, aliases)))
        rows = [{'drug_id': c['candidate_id'], 'name': c['name'], 'plausible': True} for c in named['candidates']]
        rows[0]['first_approval'] = {'date': '2024-01-01'}
        panels.append({'disease': {**named['disease'], 'area': f'mock{i}'}, 'true_drug': rows[0], 'decoys': rows[1:]})
    (tmp_path / 'panels.json').write_text(json.dumps({'version': 2, 'panels': panels}))
    (tmp_path / 'identities.json').write_text(json.dumps({'drug_aliases': aliases, 'target_name_aliases': {}}))


def _v2_mock_valid(job):
    from jury.pilot import write_json
    path = Path(job['path'])
    run = json.loads(path.read_text())
    raw = mock_model(job['model'], job['prompt'].rsplit('\n', 1)[0], 0)
    reviews, flags = validate_reply(raw, job['packet'], name_aliases=job['name_aliases'])
    assert reviews is not None, flags
    run['attempts'][-1].update(status='valid', reviews=reviews, validation=flags,
        raw_output=raw, input_tokens=10, output_tokens=20, latency_ms=1)
    write_json(path, run)
    return {'model': job['model'], 'condition': job['condition'], 'status': 'valid'}


def _v2_mock_fail(job):
    from jury.pilot import write_json
    path = Path(job['path']);run = json.loads(path.read_text())
    run['attempts'][-1].update(status='failed', error={'type': 'SyntheticFailure', 'http_status': None}, latency_ms=1)
    write_json(path, run)
    return {'model': job['model'], 'condition': job['condition'], 'status': 'failed'}


def test_v2_blind_identity_scan_keeps_biology_values_and_synonyms(tmp_path):
    from pipeline.panels import blind_packet, blind_prompt_leaks
    from jury.client import build_prompt
    packet = deepcopy(PACKET)
    aliases = {c['candidate_id']: [c['name'], c['candidate_id'], f'Trade {c["label"]}'] for c in packet['candidates']}
    c = packet['candidates'][0]
    packet['evidence'][0]['statement'] += f" {c['name']}'s Trade {c['label']} identity is {c['candidate_id']}."
    blind = blind_packet(packet, aliases)
    prompt = build_prompt(blind, [c['label'] for c in blind['candidates']])
    assert blind_prompt_leaks(prompt, [a for v in aliases.values() for a in v]) == []
    assert [c['targets'] for c in blind['candidates']] == [c['targets'] for c in packet['candidates']]
    assert [e['values'] for e in blind['evidence']] == [e['values'] for e in packet['evidence']]
    assert blind_prompt_leaks(prompt + ' CHEMBL1234567', []) == ['CHEMBL1234567']


def test_v2_paired_orders_score_both_juries_and_gap_offline(tmp_path):
    from jury.pilot import freeze_v2, v2_jobs, run_v2, score_v2
    _v2_fixture(tmp_path)
    freeze_v2(tmp_path)
    jobs = v2_jobs(tmp_path)
    assert len(jobs) == 48
    orders = {}
    for j in jobs:
        key = (j['disease_id'], j['model'])
        if key in orders: assert orders[key] == j['presented_order']
        orders[key] = j['presented_order']
    run_v2(tmp_path, _v2_mock_valid)
    s = score_v2(tmp_path)
    assert s['total_attempts'] == 48
    assert all(v['valid_runs'] == 6 for c in s['models'].values() for v in c.values())
    assert all(j['complete_panels'] == 6 for c in s['juries'].values() for j in c.values())
    assert all(v['mrr_named_minus_blind'] == 0 for v in s['named_minus_blind'].values())
    run_v2(tmp_path, _v2_mock_valid)
    assert score_v2(tmp_path)['total_attempts'] == 48


def test_v2_sixty_call_budget_survives_resume(tmp_path):
    from jury.pilot import run_v2, score_v2
    _v2_fixture(tmp_path)
    run_v2(tmp_path, _v2_mock_fail)
    result = score_v2(tmp_path)
    assert result['total_attempts'] == 60
    assert all(v['mrr'] == 0 for c in result['models'].values() for v in c.values())
    run_v2(tmp_path, _v2_mock_fail)
    assert score_v2(tmp_path)['total_attempts'] == 60


def test_v2_superseded_calls_are_charged_to_the_same_budget(tmp_path):
    from jury.pilot import run_v2, score_v2
    _v2_fixture(tmp_path)
    (tmp_path / 'protocol_amendment.json').write_text(json.dumps({'prior_calls_not_in_active_runs': 10}))
    run_v2(tmp_path, _v2_mock_fail)
    result = score_v2(tmp_path)
    assert result['active_attempts'] == 50 and result['total_attempts'] == 60
    run_v2(tmp_path, _v2_mock_fail)
    assert score_v2(tmp_path)['total_attempts'] == 60


def test_numeric_family_cannot_exempt_a_bare_measurement():
    from jury.client import _name_identifiers, _numbers
    packet = deepcopy(PACKET)
    packet['evidence'][0]['statement'] += ' Serotonin 1a receptor is a source name.'
    assert '1' not in _name_identifiers(packet)
    assert _numbers('Uncited measurement 1', _name_identifiers(packet))


@pytest.mark.parametrize('case_name', ['v2_map2k', 'v2_fgfr_range', 'v2_expanded_family'])
def test_recorded_v2_source_families_are_not_measurements(case_name):
    from jury.client import validate_reply
    case = json.loads((Path(__file__).parent / f'data/pilot_v2/{case_name}.json').read_text())
    assert validate_reply(case['raw_output'], case['packet'], name_aliases=case['name_aliases'])[0] is not None
    raw = json.loads(case['raw_output'])
    raw['reviews'][0]['rationale'] += ' Uncited measurement 99.123456789.'
    reviews, flags = validate_reply(json.dumps(raw), case['packet'], name_aliases=case['name_aliases'])
    assert reviews is None and not flags['numbers_match']
    if case_name == 'v2_expanded_family':
        changed = case['raw_output'].replace('phosphodiesterase 3 and 4', 'phosphodiesterase 3 and 99')
        assert changed != case['raw_output']
        reviews, flags = validate_reply(changed, case['packet'], name_aliases=case['name_aliases'])
        assert reviews is None and not flags['numbers_match']


def test_blinding_preserves_receptor_biology_when_a_synonym_overlaps():
    from pipeline.panels import blind_packet, blind_prompt_leaks
    packet = deepcopy(PACKET)
    candidate = packet['candidates'][0]
    aliases = {c['candidate_id']: [c['name'], c['candidate_id']] for c in packet['candidates']}
    aliases[candidate['candidate_id']].append('insulin')
    item = packet['evidence'][0]
    item.update(kind='mechanism', statement=f"ChEMBL records {candidate['name']}'s mechanism as Insulin receptor agonist.")
    blind = blind_packet(packet, aliases, {item['id']: 'INSR agonist'})
    assert blind['evidence'][0]['statement'].endswith('mechanism as INSR agonist.')
    assert blind_prompt_leaks(blind['evidence'][0]['statement'], ['insulin',candidate['name']]) == []
    assert [c['targets'] for c in blind['candidates']] == [c['targets'] for c in packet['candidates']]
    assert [e['values'] for e in blind['evidence']] == [e['values'] for e in packet['evidence']]


def test_v2_blind_only_jobs_preserve_frozen_presented_order(tmp_path):
    from jury.pilot import v2_jobs
    _v2_fixture(tmp_path)
    all_jobs = v2_jobs(tmp_path)
    expected = {(j['disease_id'],j['model']): j for j in all_jobs if j['condition']=='blind'}
    for path in tmp_path.glob('packet-*.json'):
        path.unlink()
    blind = v2_jobs(tmp_path, conditions=('blind',))
    assert len(blind) == 24
    for job in blind:
        prior = expected[job['disease_id'],job['model']]
        assert job['prompt'] == prior['prompt']
        assert job['presented_order'] == prior['presented_order']
