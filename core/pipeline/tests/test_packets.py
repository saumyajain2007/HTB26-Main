"""Offline A4 checks against small recorded primary-source responses."""
from tests.conftest import FIXTURES
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import random
import re
import shutil
import sys
from tempfile import TemporaryDirectory

import duckdb
import httpx
import pytest

from pipeline.packets import (
    ASSOC_QUERY, CHEMBL_RELEASE, CHEMBL_URL, EvidenceSources,
    OT_RELEASE, OT_URL, build_evidence_packet,
)
from pipeline.drugs import build_universe

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = Path(__file__).parent / 'data/packets'


def read(path):
    return json.loads(path.read_text())


@pytest.fixture
def inputs():
    disease_targets = read(FIXTURES / 'disease_targets.json')
    drug_targets = read(FIXTURES / 'drug_targets.json')
    recorded = read(Path(__file__).parent / 'data/drugs/recorded.json')
    recorded.pop('provenance')
    for name in ('clinical_indication', 'clinical_report'):
        recorded['tables'][name] = read(Path(__file__).parent / f'data/drugs/{name}.json')['rows']
    real_drugs = {d['drug_id']: d for d in build_universe(**recorded)['drugs']}
    for drug in drug_targets['drugs']:
        real_targets = {t['target_id']: t for t in real_drugs.get(drug['drug_id'], {}).get('targets', [])}
        for target in drug['targets']:
            if 'bioactivity' in target['support']:
                for key in ('median_pchembl', 'n_activities'):
                    target[key] = real_targets[target['target_id']][key]
    candidates = read(FIXTURES / 'candidates.json')
    return disease_targets, drug_targets, candidates


@pytest.fixture
def sources(tmp_path):
    for saved in read(SAMPLES / 'http.json') + read(SAMPLES / 'qa-http.json'):
        signature = json.dumps(saved['request'], sort_keys=True)
        path = tmp_path / 'packets/http' / saved['release'] / (sha256(signature.encode()).hexdigest() + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved))
    for sample in SAMPLES.glob('ot-*.json'):
        dataset = sample.stem.removeprefix('ot-')
        records = tmp_path / (dataset + '.json')
        records.write_text(json.dumps(read(sample)['records']))
        target = tmp_path / 'ot' / dataset / 'sample.parquet'
        target.parent.mkdir(parents=True)
        duckdb.read_json(str(records)).write_parquet(str(target))
    return EvidenceSources(tmp_path, offline=True)


def build(inputs, sources, ids=None, **kwargs):
    disease, drugs, candidates = inputs
    return build_evidence_packet(
        {'id': disease['disease_id'], 'name': disease['disease_name']},
        ids if ids is not None else [c['candidate_id'] for c in candidates['candidates']],
        disease, drugs, experiment_id=candidates['experiment_id'],
        releases=candidates['releases'], sources=sources, **kwargs,
    )


def test_fixture_shapes_and_real_measurements(inputs, sources):
    before = deepcopy(inputs)
    updates, packet = build(inputs, sources)
    fixture_packet = read(FIXTURES / 'evidence_packet.json')
    assert inputs == before
    assert packet.keys() == fixture_packet.keys()
    assert len(packet['candidates']) == 4
    assert len(packet['evidence']) == 21
    assert packet['releases'] == fixture_packet['releases']
    by_id = {c['candidate_id']: c for c in updates}
    for sample in inputs[2]['candidates']:
        update = by_id[sample['candidate_id']]
        assert {**sample, **update}.keys() == sample.keys()
        assert update['targets'] == sample['targets']
        assert update['pubchem_cid'] == sample['pubchem_cid']
        assert update['safety_status'] == sample['safety_status']
        for warning in update['warnings']:
            assert warning.keys() == sample['warnings'][0].keys()
    for candidate in packet['candidates']:
        assert candidate.keys() == fixture_packet['candidates'][0].keys()
    for item in packet['evidence']:
        assert item.keys() == fixture_packet['evidence'][0].keys()
        assert all(item[k] for k in ('source', 'source_id', 'url', 'release'))
        assert all(type(v) in (float, int) for v in item['values'].values())
        assert all(str(v) in item['statement'] for v in item['values'].values())
    pairs = {e['source_id']: e['values'] for e in packet['evidence'] if e['kind'] == 'bioactivity'}
    assert pairs == {
        'CHEMBL2105759/CHEMBL2835': {'median_pchembl': 8.23, 'n_activities': 26},
        'CHEMBL2105759/CHEMBL3553': {'median_pchembl': 7.28, 'n_activities': 13},
    }
    scores = {e['source_id'].split('/')[0]: e['values']['evidence_only_score']
              for e in packet['evidence'] if e['kind'] == 'target_association'}
    assert scores == {'ENSG00000068078': .62956398, 'ENSG00000162434': .29073451,
                      'ENSG00000096968': .29462655, 'ENSG00000171791': .34861204}
    # Every non-approval source record and text matches the fixture, after replacing
    # only the fictional measurements. Approval can select another real regulator.
    actual = {(e['kind'], e['source_id']): e for e in packet['evidence']}
    for sample in fixture_packet['evidence']:
        if sample['kind'] in {'approval', 'network_path', 'pathway'}:
            continue
        item = actual[sample['kind'], sample['source_id']]
        assert item['values'].keys() == sample['values'].keys()
        if sample['kind'] != 'bioactivity':
            assert item['url'] == sample['url']
        if sample['kind'] in {'mechanism', 'warning'}:
            assert item['statement'] == sample['statement']
    # Shared association records have one E ID, reused by both JAK inhibitors.
    rux = {e['id'] for e in by_id['CHEMBL1789941']['evidence'] if e['kind'] == 'target_association'}
    bari = {e['id'] for e in by_id['CHEMBL2105759']['evidence'] if e['kind'] == 'target_association'}
    assert len(rux) == 2 and rux == bari
    assert len({e['id'] for e in packet['evidence']}) == len(packet['evidence'])


def test_seeded_labels_ignore_upstream_order_and_packet_has_no_ranks(inputs, sources):
    ids = [c['candidate_id'] for c in inputs[2]['candidates']]
    _, packet = build(inputs, sources, ids)
    _, reversed_packet = build(inputs, sources, list(reversed(ids)))
    assert packet == reversed_packet
    expected = sorted(ids)
    random.Random(7).shuffle(expected)
    assert [c['candidate_id'] for c in packet['candidates']] == expected
    assert [c['label'] for c in packet['candidates']] == ['C1', 'C2', 'C3', 'C4']
    _, changed_seed = build(inputs, sources, ids, shuffle_seed=9)
    assert packet['candidates'] != changed_seed['candidates']
    forbidden = {'network', 'direct_evidence_rank', 'selected_by', 'rank'}

    def check(value):
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(packet)
    # Packet copies cannot mutate the UI evidence or target rows.
    updates, packet = build(inputs, sources)
    packet['candidates'][0]['targets'][0]['name'] = 'changed'
    assert all(t['name'] != 'changed' for c in updates for t in c['targets'])


def test_melphalan_does_not_leak_myeloma(inputs, sources):
    updates, packet = build(inputs, sources, ['CHEMBL852'])
    assert updates[0]['targets'] == []
    assert packet['evidence']
    for item in packet['evidence']:
        assert item['kind'] in {'approval', 'warning'}
        assert not re.search(r'myeloma|MONDO_0009693|EFO_0001378', json.dumps(item), re.I)
        assert 'clinical' not in item['statement'].lower()
    assert sources.coverage['unmapped_by_reason']['non_protein_target'] == 1


def test_missing_warnings_are_unknown_and_warning_text_is_preserved(inputs, sources):
    updates, packet = build(inputs, sources)
    for candidate in updates:
        if candidate['candidate_id'] in {'CHEMBL3545376', 'CHEMBL3137309'}:
            assert candidate['warnings'] == []
            assert candidate['safety_status'] == 'unknown'
        else:
            assert candidate['warnings']
            assert candidate['safety_status'] == 'warnings_recorded'
            assert all(w['description'] is None for w in candidate['warnings'])
    rux = next(c for c in updates if c['candidate_id'] == 'CHEMBL1789941')
    assert {e['source_id'] for e in rux['evidence'] if e['kind'] == 'mechanism'} == {'934', '936'}
    assert {e['source_id'] for e in rux['evidence'] if e['kind'] == 'warning'} == {'3762'}
    assert not any(e['source_id'] in {'9864', '9908', '9931', '9953', '5'} for e in packet['evidence'])


def test_only_regulator_reports_count(sources):
    relation = sources.table('clinical_report')
    # In source data ATC and TTD say APPROVAL too; neither verifies approval.
    sources.table = lambda name: (relation.filter(duckdb.ColumnExpression('source').isin('ATC', 'TTD'))
                                  if name == 'clinical_report' else EvidenceSources.table(sources, name))
    assert sources.approval(['CHEMBL3545376']) is None


def test_pubchem_uses_inchikey_and_none_never_name(tmp_path):
    seen = []
    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(404, json={'Fault': {'Code': 'PUGREST.NotFound'}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        sources = EvidenceSources(tmp_path, client=client)
        molecule = {'pref_name': 'NEVER USE THIS', 'molecule_structures': {
            'standard_inchi_key': 'XUZMWHLSFXCVMG-UHFFFAOYSA-N'}}
        assert sources.pubchem_cid(molecule) is None
        assert '/inchikey/XUZMWHLSFXCVMG-UHFFFAOYSA-N/cids/JSON' in seen[0]
        assert len(seen) == 1
        assert sources.pubchem_cid({'pref_name': 'BARICITINIB', 'molecule_structures': None}) is None
        assert len(seen) == 1
        sources.offline = True
        assert sources.pubchem_cid(molecule) is None
    assert 'NEVER' not in ''.join(seen)


def test_ambiguous_mappings_are_counted_without_symbol_fallback(sources):
    sources._protein_map = {'P23458': {'ENSG00000162434', 'ENSG00000096968'}}
    assert sources.map_target('CHEMBL2835') == set()
    assert sources.coverage['unmapped_items'] == 1
    assert sources.coverage['unmapped'][0]['status'] == 'unmapped'
    assert sources.coverage['unmapped_by_reason'] == {'ambiguous_uniprot_mapping': 1}
    sources._protein_map = {}
    assert sources.map_target('CHEMBL2835') == set()
    assert sources.coverage['unmapped_by_reason']['missing_uniprot_mapping'] == 1


def test_empty_set_and_validation(inputs, sources):
    updates, packet = build(inputs, sources, [])
    assert updates == packet['candidates'] == packet['evidence'] == []
    for ids in [['BARICITINIB'], ['CHEMBL999999999'], ['CHEMBL852', 'CHEMBL852']]:
        with pytest.raises(ValueError):
            build(inputs, sources, ids)
    with pytest.raises(ValueError):
        build_evidence_packet({'id': 'MONDO_0100096', 'name': 'COVID-19'}, [],
                              inputs[0], inputs[1], experiment_id=inputs[2]['experiment_id'], sources=sources)


def test_missing_warning_cache_fails_instead_of_claiming_no_warnings(inputs, sources):
    for path in (sources.data_dir / 'ot/drug_warning').glob('*.parquet'):
        path.unlink()
    with pytest.raises(FileNotFoundError, match='drug_warning'):
        build(inputs, sources)


def test_coverage_returned_outside_packet_contract(inputs, sources):
    coverage = {}
    _, packet = build(inputs, sources, coverage=coverage)
    assert coverage['unmapped_items'] == 5
    assert coverage['unmapped_items'] == sum(coverage['unmapped_by_reason'].values())
    assert all(r['status'] == 'unmapped' and r['reason'] for r in coverage['unmapped'])
    assert 'coverage' not in packet


def test_one_shared_warning_record_gets_one_e_id(inputs, sources):
    warning = deepcopy(next(r for r in sources.warnings(['CHEMBL2105759']) if r['id'] == 172))
    # Synthetic shared-record edge case using a recorded warning's fields.
    warning['chemblIds'] = ['CHEMBL1789941', 'CHEMBL2105759']
    warning['references'] = []
    sources.warnings = lambda _: [warning]
    updates, packet = build(inputs, sources, warning['chemblIds'])
    warnings = [e for e in packet['evidence'] if e['kind'] == 'warning']
    assert len(warnings) == 1
    assert all(c['warnings'][0]['evidence_id'] == warnings[0]['id'] for c in updates)
    assert 'BARICITINIB' in warnings[0]['statement'] and 'RUXOLITINIB' in warnings[0]['statement']


def test_ivacaftor_and_tezacaftor_share_one_candidate_neutral_approval(inputs, sources):
    disease, _, candidates = inputs
    drugs = read(SAMPLES / 'qa-drug-targets.json')
    ids = ['CHEMBL2010601', 'CHEMBL3544914']
    updates, packet = build((disease, drugs, candidates), sources, ids)
    approvals = [e for e in packet['evidence'] if e['kind'] == 'approval']
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval['source_id'] == 'label/2018/210491lbl.pdf'
    assert approval['statement'] == 'Open Targets 26.09 records a regulator-backed approval from FDA.'
    assert all([e for e in c['evidence'] if e['kind'] == 'approval'] == [approval] for c in updates)
    assert all(approval['id'] in c['evidence_ids'] for c in packet['candidates'])
    assert not re.search(r'ivacaftor|tezacaftor|CHEMBL2010601|CHEMBL3544914', approval['statement'], re.I)


@pytest.mark.parametrize('disease_mention', [None, 'name', 'id', 'source_id', 'numbers'])
def test_gemtuzumab_warning_description_and_disease_leakage(inputs, sources, disease_mention):
    disease, _, candidates = inputs
    drugs = read(SAMPLES / 'qa-drug-targets.json')
    original = sources.warnings
    description = 'greater number of deaths'
    if disease_mention:
        records = deepcopy(original(['CHEMBL1201506']))
        warning = next(r for r in records if r['id'] == 4457)
        if disease_mention == 'numbers':
            description = warning['description'] = 'greater number of deaths in 2 studies'
        elif disease_mention == 'source_id':
            # The mapped ID also catches a source's alternative Disease name.
            warning['efoId'] = disease['disease_id'].replace('_', ':')
            warning['description'] = 'greater number of deaths in multiple myeloma'
        else:
            term = disease['disease_name'].upper() if disease_mention == 'name' else disease['disease_id']
            warning['description'] = f'greater number of deaths in {term}'
        sources.warnings = lambda _: records
    updates, packet = build((disease, drugs, candidates), sources, ['CHEMBL1201506'])
    item = next(e for e in packet['evidence'] if e['source_id'] == '4457')
    assert updates[0]['safety_status'] == 'warnings_recorded'
    if disease_mention and disease_mention != 'numbers':
        assert 'Description:' not in item['statement']
        assert not re.search(r'myeloma|MONDO_0009693|MONDO:0009693', item['statement'], re.I)
    else:
        assert item['statement'].endswith('Description: ' + description)
        assert next(w for w in updates[0]['warnings'] if w['evidence_id'] == item['id'])['description'] == description
        if disease_mention == 'numbers':
            assert item['values'] == {'description_number_1': 2}


def test_live_check_fails_without_network_even_with_warm_cache(inputs, sources, tmp_path, monkeypatch):
    fake_root = tmp_path / 'repo'
    for directory in ('packets', 'ot'):
        shutil.copytree(sources.data_dir / directory, fake_root / 'data' / directory)
    monkeypatch.setattr(sys.modules[__name__], 'ROOT', fake_root)
    monkeypatch.setattr('pipeline.packets.time.sleep', lambda _: None)
    attempts = []
    def unavailable(request):
        attempts.append(request)
        raise httpx.ConnectError('network disabled', request=request)
    client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda *args, **kwargs: client(
        *args, **kwargs, transport=httpx.MockTransport(unavailable)))
    with pytest.raises(httpx.ConnectError, match='network disabled'):
        test_live_fixture_candidates(inputs)
    assert attempts


def test_mixed_release_is_rejected(inputs, sources):
    chembl = sources.chembl
    sources.chembl = lambda endpoint: ({'chembl_db_version': 'ChEMBL_38'}
                                       if endpoint == 'status.json' else chembl(endpoint))
    with pytest.raises(ValueError, match='release differs'):
        build(inputs, sources)


def test_retries_cache_and_upstream_failure(tmp_path, monkeypatch):
    monkeypatch.setattr('pipeline.packets.time.sleep', lambda _: None)
    attempts = []
    def respond(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ReadError('connection reset')
        return httpx.Response(503 if len(attempts) == 2 else 200, json={'value': 4})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        sources = EvidenceSources(tmp_path, client=client)
        assert sources.request(CHEMBL_URL + 'status.json', CHEMBL_RELEASE) == {'value': 4}
        assert len(attempts) == 3
        sources.offline = True
        assert sources.request(CHEMBL_URL + 'status.json', CHEMBL_RELEASE) == {'value': 4}
        saved = read(next(tmp_path.glob('packets/http/*/*.json')))
        assert saved['release'] == CHEMBL_RELEASE and saved['retrieved_at']
        with pytest.raises(FileNotFoundError):
            sources.chembl('missing.json')
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        sources = EvidenceSources(tmp_path / 'failed', client=client)
        with pytest.raises(httpx.HTTPStatusError):
            sources.request(OT_URL, OT_RELEASE)
        assert not list((tmp_path / 'failed').rglob('*.json'))


def test_graphql_errors_never_become_missing_evidence(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'errors': [{'message': 'failed'}]}))) as client:
        sources = EvidenceSources(tmp_path, client=client)
        with pytest.raises(ValueError, match='query failed'):
            sources.associations('MONDO_0009693')
        assert not list(tmp_path.rglob('*.json'))


def test_association_and_chembl_pagination(tmp_path):
    calls = []
    def respond(request):
        calls.append(request)
        if request.method == 'POST':
            body = json.loads(request.content)
            assert body['query'] == ASSOC_QUERY
            index = body['variables']['i']
            score = .6 / (3.141592653589793**2 / 6)
            row = {'target': {'id': f'ENSG{index:011d}', 'approvedSymbol': 'display'},
                   'score': score, 'datasourceScores': [{'id': 'eva', 'score': .6}]}
            return httpx.Response(200, json={'data': {'disease': {'associatedTargets': {'count': 2, 'rows': [row]}}}})
        if 'offset=1' in str(request.url):
            return httpx.Response(200, json={'activities': [2], 'page_meta': {'next': None}})
        return httpx.Response(200, json={'activities': [1], 'page_meta': {'next': '/chembl/api/data/activity.json?offset=1'}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        sources = EvidenceSources(tmp_path, client=client)
        assert len(sources.associations('MONDO_0009693')) == 2
        assert list(sources.pages('activity.json', 'activities')) == [1, 2]
    assert len(calls) == 4


def test_samples_are_small_and_releases_recorded():
    for path in SAMPLES.glob('*.json'):
        assert path.stat().st_size < 200_000
    for envelope in read(SAMPLES / 'http.json'):
        assert envelope['release'] and envelope['retrieved_at']


@pytest.mark.network
def test_live_fixture_candidates(inputs):
    # Reuse only the pinned Parquet datasets; HTTP responses must be fetched.
    successful_requests = []
    def received(response):
        if response.is_success:
            successful_requests.append(str(response.request.url))
    data_dir = ROOT / 'data'
    with TemporaryDirectory(prefix='packets-network-', dir=data_dir) as temporary:
        cache = Path(temporary)
        (cache / 'ot').symlink_to(data_dir / 'ot', target_is_directory=True)
        assert not list(cache.glob('packets/http/*/*.json'))
        with httpx.Client(timeout=15, follow_redirects=True, event_hooks={'response': [received]}) as client:
            updates, packet = build(inputs, EvidenceSources(cache, client=client))
        assert len(updates) == 4 and len(packet['evidence']) == 21
        assert all(c['pubchem_cid'] for c in updates)
        assert OT_URL in successful_requests
        assert any(url.startswith(CHEMBL_URL) for url in successful_requests)
        assert any(url.startswith('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/')
                   for url in successful_requests)


def test_reuses_a2_values_with_salt_only_source_ids(inputs, sources):
    drug = next(d for d in inputs[1]['drugs'] if d['drug_id'] == 'CHEMBL2105759')
    drug['source_chembl_ids'].append('CHEMBL999999')
    chembl, pages = sources.chembl, sources.pages
    sources.chembl = lambda endpoint: ({'molecule_hierarchy': {'parent_chembl_id': drug['drug_id']}}
        if endpoint == 'molecule/CHEMBL999999.json' else chembl(endpoint))
    # ID discovery needs no measurement values. Only the salt supplies the IDs.
    sources.pages = lambda endpoint, key: (
        [{'target_chembl_id': 'CHEMBL2835'}, {'target_chembl_id': 'CHEMBL3553'}]
        if 'molecule_chembl_id=CHEMBL999999&' in endpoint else []
        if endpoint.startswith('activity.json?') else pages(endpoint, key))
    _, packet = build(inputs, sources, [drug['drug_id']])
    actual = [e for e in packet['evidence'] if e['kind'] == 'bioactivity']
    assert len(actual) == 2
    assert {tuple(e['values'].items()) for e in actual} == {
        (('median_pchembl', t['median_pchembl']), ('n_activities', t['n_activities']))
        for t in drug['targets'] if 'bioactivity' in t['support']}
    assert all('CHEMBL999999' in e['url'] and 'pchembl_value__gte=5' in e['url'] for e in actual)


def test_obsolete_uniprot_ids_use_a2_index(sources):
    sources._protein_map = None
    relation = sources.table('target')
    sources.table = lambda _: relation.project(
        "id, list_transform(proteinIds, lambda p: {'id': p.id, 'source': 'uniprot_obsolete'}) as proteinIds")
    assert sources.map_target('CHEMBL2835', single=True) == {'ENSG00000162434'}


def test_optional_pathways_update_candidates_and_count_unmapped(inputs, sources):
    from pipeline.pathways import load_pathways
    pathways, _ = load_pathways(Path(__file__).parent/'data/pathways/Ensembl2Reactome.tsv')
    coverage = {}
    updates, packet = build(inputs, sources, pathways=pathways, pathway_release='reactome-97', coverage=coverage)
    items = {e['id']:e for e in packet['evidence']}
    assert sum(e['kind']=='pathway' for e in items.values()) == 1
    assert coverage['pathways']['unmapped_items'] > 0
    for update in updates:
        candidate = next(c for c in packet['candidates'] if c['candidate_id']==update['candidate_id'])
        assert update['evidence']==[items[e] for e in candidate['evidence_ids']]


def test_packet_accepts_alphanumeric_disease_id(inputs, sources, monkeypatch):
    disease, drugs, candidates = deepcopy(inputs)
    disease['disease_id'] = 'NCIT_C74532'
    monkeypatch.setattr(sources, 'associations', lambda _: {})
    _, packet = build((disease, drugs, candidates), sources)
    assert packet['disease']['id'] == 'NCIT_C74532'
