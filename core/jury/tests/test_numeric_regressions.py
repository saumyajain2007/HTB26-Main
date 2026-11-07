"""Replay actual pilot ballots; measurements must still be citation-exact."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from jury.client import validate_reply

DATA = Path(__file__).parent / 'data/pilot_numeric'
CASES = [json.loads(p.read_text()) for p in sorted(DATA.glob('*.json'))]


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['source_run'])
def test_recorded_disease_names_family_names_and_digit_leading_aliases(case):
    for attempt in case['attempts']:
        reviews, flags = validate_reply(attempt['raw_output'], case['packet'])
        assert reviews is not None, flags['errors']
        assert flags['numbers_match']


@pytest.mark.parametrize('kind', ['drug', 'target', 'disease', 'ids'])
def test_recorded_reply_with_digits_in_named_entities(kind):
    case = CASES[0]
    packet = deepcopy(case['packet'])
    value = json.loads(case['attempts'][0]['raw_output'])
    review = value['reviews'][0]
    candidate = next(c for c in packet['candidates'] if c['label'] == review['label'])
    if kind == 'drug':
        candidate['name'] = 'Recorded drug 123 formulation'
        text = 'Recorded drug 123 formulation has mechanism evidence.'
    elif kind == 'target':
        candidate['targets'][0]['name'] = 'Recorded target 123 subunit'
        text = 'Recorded target 123 subunit has mechanism evidence.'
    elif kind == 'disease':
        text = packet['disease']['name'] + ' is the Disease under review.'
    else:
        ids = review['supporting_evidence_ids'] + review['safety']['evidence_ids']
        text = review['label'] + ' references ' + ' and '.join(ids) + '.'
    review['rationale'] = text
    assert validate_reply(json.dumps(value), packet)[0] is not None
    review['rationale'] += ' Unsupported measurement 0.123456789123456789.'
    reviews, flags = validate_reply(json.dumps(value), packet)
    assert reviews is None and flags['numbers_match'] is False


@pytest.mark.parametrize('measurement', ['50mg', '1e+1', '8e-1', 'dose-99', 'pChEMBL8'])
def test_source_text_never_exempts_an_uncited_measurement(measurement):
    from jury.client import _name_identifiers, _numbers
    packet = deepcopy(CASES[0]['packet'])
    packet['evidence'][0]['statement'] += ' Uncited measurement ' + measurement + '.'
    assert _numbers(measurement, _name_identifiers(packet))


@pytest.mark.parametrize('name', ['PDE3/4', '5-HT2a/2c'])
def test_recorded_reply_with_shared_prefix_family_names(name):
    case = CASES[0]
    value = json.loads(case['attempts'][0]['raw_output'])
    value['reviews'][0]['rationale'] = name + ' mechanisms are listed in the source packet.'
    assert validate_reply(json.dumps(value), case['packet'])[0] is not None
    value['reviews'][0]['rationale'] += ' An unsupported measurement 0.123456789123456789.'
    assert validate_reply(json.dumps(value), case['packet'])[0] is None


def test_unknown_family_member_is_not_silently_exempted():
    from jury.client import _numbers, _name_identifiers
    assert _numbers('PDE3/99', _name_identifiers(CASES[0]['packet']))
