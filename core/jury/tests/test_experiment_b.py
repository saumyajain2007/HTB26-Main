"""Offline budget and strict-validation checks; no provider calls."""
from tests.conftest import FIXTURES
from copy import deepcopy
import json
from pathlib import Path

import pytest

from jury import pilot
from jury.client import ModelReply, mock_model



@pytest.fixture
def scorer_checkout(tmp_path, monkeypatch):
    root = tmp_path / 'scorer-checkout'
    ranking = root / 'ranking'
    ranking.mkdir(parents=True)
    for name in ['scoring.py', 'network.py', 'proximity.py', 'data.py', 'artifacts.py']:
        (ranking / name).write_text('# synthetic source for offline freeze tests\n')
    monkeypatch.setenv('RANKING_ROOT', str(root))
    return root


def test_b_budget_reserves_before_dispatch_and_caps_retries(tmp_path, monkeypatch):
    output, report = tmp_path/'data', tmp_path/'report'
    output.mkdir(); report.mkdir()
    (report/'protocol.md').write_text('Frozen test protocol')
    jobs = [{'disease_id': f'MONDO_{i}', 'model': 'test', 'condition': 'pathways',
             'presented_order': [], 'prompt': 'Frozen prompt', 'path':str(output/'runs'/f'{i}.json')}
            for i in range(42)]
    monkeypatch.setattr(pilot, 'freeze_b', lambda *a: None)
    monkeypatch.setattr(pilot, 'b_jobs', lambda *a: deepcopy(jobs))
    monkeypatch.delenv('SNOWFLAKE_REASONING_EFFORT', raising=False)
    calls=[]
    def fail(job):
        p=Path(job['path']);run=json.loads(p.read_text());a=run['attempts'][-1]
        assert a['status']=='reserved' and a['protocol_sha256']
        calls.append((job['disease_id'],a['attempt']))
        a.update(status='failed',error={'type':'OfflineFailure'})
        pilot.write_json(p,run)
        return {'status':'failed'}
    monkeypatch.setattr(pilot,'b_live_attempt',fail)
    pilot.run_b(output,report)
    assert len(calls)==45
    assert sum(len(json.loads(p.read_text())['attempts']) for p in (output/'runs').glob('*.json'))==45
    assert set(i for i,a in calls if a==2)=={'MONDO_0','MONDO_1','MONDO_2'}
    pilot.run_b(output,report)
    assert len(calls)==45
    assert not (output/'live.lock').exists()


def test_b_attempt_retains_strict_numeric_and_citation_checks(tmp_path):
    packet=json.loads((FIXTURES / 'evidence_packet.json').read_text())
    order=[c['label'] for c in packet['candidates']]
    from jury.client import build_prompt
    prompt=build_prompt(packet,order)
    job={'path':str(tmp_path/'run.json'),'packet':packet,'prompt':prompt,
         'name_aliases':[],'model':'offline','condition':'pathways','disease_id':packet['disease']['id']}
    def reserve():
        pilot.write_json(Path(job['path']),{'attempts':[{'status':'reserved','attempt':1}]})
    reserve()
    assert pilot.b_live_attempt(job,lambda m,p: ModelReply(mock_model(m,p,0)))['status']=='valid'
    bad=json.loads(mock_model('offline',prompt,0));bad['reviews'][0]['rationale']='A measured effect of 987654321.'
    reserve()
    assert pilot.b_live_attempt(job,lambda m,p: ModelReply(json.dumps(bad)))['status']=='invalid'
    saved=json.loads(Path(job['path']).read_text())['attempts'][0]
    assert saved['raw_output'] and saved['validation']['errors']
    assert saved['dispatched_at']


def test_b_borda_breaks_points_ties_for_fifteen_rank_null():
    packet={'candidates':[{'label':'C1','candidate_id':'CHEMBL2'}, {'label':'C2','candidate_id':'CHEMBL1'}]}
    reviews=[{'label':'C1','rank':1,'decision':'watch'}, {'label':'C2','rank':2,'decision':'watch'}]
    reverse=[{**r,'rank':3-r['rank']} for r in reviews]
    ranked,w=pilot.b_borda(packet,[{'reviews':reviews},{'reviews':reverse}])
    assert [r['candidate_id'] for r in ranked]==['CHEMBL1','CHEMBL2']
    assert [r['rank'] for r in ranked]==[1,2]
    assert pilot.b_borda(packet,[None])==(None,None)


def test_b_refuses_incomplete_cohort_before_loading_prompts(tmp_path):
    import pytest
    (tmp_path/'panels.json').write_text(json.dumps({'panels':[{}]*10}))
    with pytest.raises(ValueError,match='eleven'):
        pilot.b_jobs(tmp_path)


def test_b_freezes_protocol_before_dispatch_and_detects_changes(tmp_path, monkeypatch, scorer_checkout):
    import pytest
    output,report=tmp_path/'data',tmp_path/'report'
    output.mkdir();report.mkdir()
    protocol=report/'protocol.md';protocol.write_text('Frozen protocol; no calls yet.')
    jobs=[{'disease_id':f'MONDO_{i}','model':'offline','condition':'pathways',
           'presented_order':['C1'],'prompt':f'Frozen prompt {i}',
           'path':str(output/'runs'/f'{i}.json')} for i in range(42)]
    monkeypatch.setattr(pilot,'b_jobs',lambda *a:deepcopy(jobs))
    monkeypatch.chdir(tmp_path)
    first=pilot.freeze_b(output,report)
    assert pilot.freeze_b(output,report)==first
    scorer_hashes = {name: digest for name, digest in first['source_sha256'].items()
                     if Path(name).parent == scorer_checkout / 'ranking'}
    assert len(scorer_hashes) == 5
    from hashlib import sha256
    assert scorer_hashes == {str(p): sha256(p.read_bytes()).hexdigest()
                             for p in (scorer_checkout / 'ranking').glob('*.py')}
    assert first['protocol_sha256'] in (report/'results.md').read_text()
    assert not (output/'runs').exists()
    scorer = scorer_checkout / 'ranking/scoring.py'
    original = scorer.read_bytes()
    scorer.write_text('# changed scorer')
    with pytest.raises(ValueError, match='changed'):
        pilot.freeze_b(output, report)
    scorer.write_bytes(original)
    protocol.write_text('Changed after sealing')
    with pytest.raises(ValueError,match='changed'):
        pilot.freeze_b(output,report)


def test_amended_experiment_scores_all_methods_and_paired_panels_offline(tmp_path, monkeypatch, scorer_checkout):
    # Synthetic contract records exercise the whole runner/report path; no scientific claims.
    from pipeline.panels import B_DISEASES
    from jury.client import ModelReply
    output, report = tmp_path/'data', tmp_path/'report'
    output.mkdir();report.mkdir();(report/'protocol.md').write_text('Frozen synthetic protocol')
    panels=[]
    for did,name,area in B_DISEASES:
        rows=[{'drug_id':f'CHEMBL{i}','name':f'Drug {i}'} for i in range(1,16)]
        panels.append({'disease':{'id':did,'name':name},'true_drug':rows[0], 'decoys':rows[1:],
                       'matching':{'plausible_decoy_count':1,'eligible_plausible':1},'blind_exclusions':[]})
        packet={'experiment_id':'e965c62a-545d-4dbd-a7b8-bb775c4f9ef1',
                'disease':{'id':did,'name':name},'releases':['opentargets-26.09'],
                'candidates':[{'candidate_id':r['drug_id'],'label':f'C{i}','name':f'Agent C{i}',
                    'targets':[{'id':'ENSG00000000001','name':'GENE','mechanism':'unknown'}],
                    'evidence_ids':['E1'],'safety_status':'unknown'} for i,r in enumerate(rows,1)],
                'evidence':[{'id':'E1','kind':'target_association','source':'open_targets',
                    'source_id':'synthetic','url':'https://example.org','release':'opentargets-26.09',
                    'statement':'Synthetic Target association.', 'values':{'evidence_only_score':.5}}]}
        pilot.write_json(output/f'blind-{did}.json',packet)
        pilot.write_json(output/f'network-{did}.json',{'candidates':[
            {'candidate_id':r['drug_id'],'network':{'rank':i}} for i,r in enumerate(rows,1)]})
    pilot.write_json(output/'panels.json',{'panels':panels})
    pilot.write_json(output/'identities.json',{'drug_aliases':{f'CHEMBL{i}':[f'CHEMBL{i}'] for i in range(1,16)},
                                              'target_name_aliases':{}})
    attempt=pilot.b_live_attempt
    monkeypatch.setenv('SNOWFLAKE_REASONING_EFFORT',json.dumps(pilot.B_EFFORT))
    monkeypatch.setattr(pilot,'b_live_attempt',lambda job: attempt(job,lambda m,p:ModelReply(mock_model(m,p,0),10,20)))
    pilot.run_b(output,report)
    result=pilot.score_b(output,report)
    assert result['live_calls_including_retries']==42
    assert result['methods']['direct_evidence']['hits']==11
    assert result['methods']['direct_evidence']['mrr']==1
    assert result['methods']['network_z']['mrr']==1
    assert result['pathway_ablation']['n']==3
    assert result['pathway_ablation']['mrr_delta']==0
    assert len(json.loads((report/'audit_sample.json').read_text()))==18
    assert len(result['panels'])==11
    assert result['protocol_sha256'] in (report/'results.md').read_text()
    assert 'Plausible decoys' in (report/'results.md').read_text()
    assert all(result['validity'][model]['pathways']==11 for model in pilot.B_MODELS)


def test_b_provider_refusal_never_parses_a_complete_ballot(tmp_path, monkeypatch):
    from jury.client import build_prompt
    packet = json.loads((FIXTURES / 'evidence_packet.json').read_text())
    prompt = build_prompt(packet, [c['label'] for c in packet['candidates']])
    raw = mock_model('offline', prompt, 0)
    path = tmp_path / 'run.json'
    pilot.write_json(path, {'attempts': [{'status': 'reserved', 'attempt': 1}]})
    job = {'path': str(path), 'packet': packet, 'prompt': prompt, 'name_aliases': [],
           'model': 'offline', 'condition': 'pathways', 'disease_id': packet['disease']['id']}
    def must_not_parse(*args, **kwargs):
        pytest.fail('Provider refusals must be rejected before ballot parsing')
    monkeypatch.setattr('jury.client.json.JSONDecoder', must_not_parse)
    result = pilot.b_live_attempt(job, lambda m, p: ModelReply(raw, 10, 20, stop_reason='refusal'))
    saved = json.loads(path.read_text())['attempts'][0]
    assert result['status'] == saved['status'] == 'invalid'
    assert saved['reviews'] is None
    assert saved['stop_reason'] == 'refusal' and saved['raw_output'] == raw
    assert saved['input_tokens'] == 10 and saved['output_tokens'] == 20
    assert 'refus' in ' '.join(saved['validation']['errors']).lower()
    assert pilot.final_attempt({'attempts': [saved]}) is None


@pytest.mark.parametrize('missing', ['all', 'scoring.py', 'network.py', 'proximity.py', 'data.py', 'artifacts.py'])
def test_b_freeze_requires_scorer_sources_before_sealing(tmp_path, monkeypatch, missing):
    output, report, ranking = tmp_path / 'data', tmp_path / 'report', tmp_path / 'external' / 'ranking'
    output.mkdir(); report.mkdir(); ranking.mkdir(parents=True)
    (report / 'protocol.md').write_text('Offline protocol')
    for name in ['scoring.py', 'network.py', 'proximity.py', 'data.py', 'artifacts.py']:
        if missing not in ('all', name):
            (ranking / name).write_text('# offline scorer source')
    monkeypatch.setenv('RANKING_ROOT', str(ranking.parent))
    monkeypatch.setattr(pilot, 'b_jobs', lambda *a, **kw: [
        {'disease_id': f'MONDO_{i}', 'model': 'offline', 'condition': 'pathways',
         'presented_order': [], 'prompt': 'Frozen', 'path': str(output / 'runs' / f'{i}.json')}
        for i in range(42)])
    with pytest.raises(FileNotFoundError, match='ranking'):
        pilot.freeze_b(output, report)
    assert not (output / 'preregistered.json').exists()
    assert not (report / 'preregistered.json').exists()
    assert not (output / 'prompts').exists()
