"""Actual A6 replies must pass the same validator used by live calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from jury.client import validate_reply

DATA = Path(__file__).parent / 'data/a6'
CASES = json.loads((DATA / 'results.json').read_text())


def packet(disease_id):
    return json.loads((DATA / f'{disease_id}_packet.json').read_text())


def raw_reply(call):
    return json.loads((DATA / f'call_{call}_reply.json').read_text())['text']


def ballot(call):
    raw = raw_reply(call)
    return json.JSONDecoder().raw_decode(raw, raw.index('{'))[0]


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['disease_id'] + '/' + c['model'])
def test_recorded_a6_statuses_match_without_replay_or_alias_arguments(case):
    source = packet(case['disease_id'])
    for call in case['calls']:
        reviews, flags = validate_reply(raw_reply(call), source)
        assert reviews is not None, flags['errors']
        # Validation enriches IDs but must preserve every word and citation.
        assert [{k: v for k, v in r.items() if k != 'candidate_id'} for r in reviews] == ballot(call)['reviews']
    assert ('valid' if reviews is not None else 'invalid') == case['status']


@pytest.mark.parametrize('field', ['rationale', 'objection', 'missing_evidence'])
@pytest.mark.parametrize('mutation', ['measurement', 'inline_id', 'citation_id', 'standalone_e3'])
def test_recorded_ligase_reply_keeps_measurements_and_citations_strict(field, mutation):
    source = packet('MONDO_0100096')
    value = ballot(6)
    review = next(r for r in value['reviews'] if r['label'] == 'C14')
    if mutation == 'citation_id':
        review['supporting_evidence_ids'].append('E999999')
    else:
        extra = {'measurement': ' Measured efficacy is 99.123456789 percent.',
                 'inline_id': ' See E999999.', 'standalone_e3': ' See E3.'}[mutation]
        if field == 'missing_evidence':
            review[field].append(extra)
        else:
            review[field] += extra
    reviews, flags = validate_reply(json.dumps(value), source)
    assert reviews is None
    if mutation == 'measurement':
        assert flags['numbers_match'] is False
    elif mutation != 'standalone_e3':
        assert flags['evidence_ids_exist'] is False
    else:
        assert any('inline evidence' in e for e in flags['errors'])


def test_ligase_exemption_requires_an_assigned_mechanism():
    source = packet('MONDO_0100096')
    review = next(r for r in ballot(6)['reviews'] if r['label'] == 'C14')
    candidate = next(c for c in source['candidates'] if c['label'] == 'C14')
    before = deepcopy(source)
    for item in source['evidence']:
        if item['kind'] == 'mechanism' and item['id'] in candidate['evidence_ids']:
            item['statement'] = 'Mechanism description unavailable.'
    # An unrelated Candidate's mechanism is insufficient, even in the packet.
    unrelated = next(e for e in source['evidence'] if e['kind'] == 'mechanism'
                     and e['id'] not in candidate['evidence_ids'])
    unrelated['statement'] = 'E3 ubiquitin ligase inhibitor.'
    reviews, flags = validate_reply(raw_reply(6), source)
    assert reviews is None
    assert any('inline evidence' in e for e in flags['errors'])
    assert validate_reply(raw_reply(6), before)[0] is not None
    assert 'E3' in review['rationale']


def test_target_aliases_require_the_verified_target_id():
    source = packet('MONDO_0009693')
    assert validate_reply(raw_reply(5), source)[0] is not None
    for candidate in source['candidates']:
        for target in candidate['targets']:
            if target['id'] == 'ENSG00000128052':
                target['id'] = 'ENSG99999999999'
    reviews, flags = validate_reply(raw_reply(5), source)
    assert reviews is None and flags['numbers_match'] is False
