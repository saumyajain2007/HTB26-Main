"""Replication freezes, budget and null tests, entirely offline."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from jury import pilot
from pipeline import panels


def test_replication_budget_is_sixty_and_restart_never_refunds(tmp_path, monkeypatch):
    output, report = tmp_path/'data', tmp_path/'report'
    output.mkdir(); report.mkdir()
    (report/'protocol.md').write_text('Frozen offline protocol')
    jobs=[{'disease_id':f'MONDO_{i//3}', 'model':pilot.B_MODELS[i%3],
           'condition':'pathways','presented_order':[], 'prompt':'frozen',
           'path':str(output/'runs'/f'{i}.json')} for i in range(42)]
    monkeypatch.setattr(pilot,'freeze_b',lambda *a,**kw:None)
    monkeypatch.setattr(pilot,'b_jobs',lambda *a,**kw:deepcopy(jobs))
    monkeypatch.delenv('SNOWFLAKE_REASONING_EFFORT',raising=False)
    calls=[]
    def fail(job):
        path=Path(job['path']);run=json.loads(path.read_text());attempt=run['attempts'][-1]
        assert attempt['status']=='reserved' and attempt['protocol_sha256']
        calls.append((job['disease_id'],job['model'],attempt['attempt']))
        attempt.update(status='failed')
        pilot.write_json(path,run)
        return {'status':'failed'}
    monkeypatch.setattr(pilot,'b_live_attempt',fail)
    pilot.run_b(output,report,replication=True)
    assert len(calls)==60
    assert {(d,m) for d,m,a in calls if a==2}=={(j['disease_id'],j['model']) for j in jobs[:18]}
    pilot.run_b(output,report,replication=True)
    assert len(calls)==60


def test_protocol_and_candidate_order_cannot_change(tmp_path):
    from hashlib import sha256
    (tmp_path/'protocol.md').write_text('scientific protocol')
    (tmp_path/'candidates.json').write_text('[]')
    seal={key:sha256((tmp_path/name).read_bytes()).hexdigest() for name,key in [
        ('protocol.md','protocol_sha256'),('candidates.json','candidates_sha256')]}
    pilot.write_json(tmp_path/'protocol_frozen.json',seal)
    assert panels.replication_protocol(tmp_path)==seal
    (tmp_path/'candidates.json').write_text('["replacement"]')
    with pytest.raises(ValueError,match='changed'):
        panels.replication_protocol(tmp_path)


def test_frozen_list_excludes_no_prior_case_by_name_guess():
    seal=panels.replication_protocol()
    assert len(seal['protocol_sha256'])==64
    candidates=json.loads(Path('results/experiment_b_replication/candidates.json').read_text())
    assert len(candidates)==48 and len({r['name'] for r in candidates})==48
    assert len({r['area'] for r in candidates})>=7


def test_same_chance_tests_reproduce_original_eleven_panel_analysis():
    old=json.loads(Path('results/experiment_b/results.json').read_text())
    methods=pilot.replication_statistics({m:v['per_panel'] for m,v in old['methods'].items()})
    for m,v in methods.items():
        for key in ['hits','hits_at_5','mrr','hits_p_one_sided','mrr_p_monte_carlo',
                    'hits_p_one_sided_holm','mrr_p_monte_carlo_holm']:
            expected = old['methods'][m][key]
            if isinstance(expected, float):
                # Allow only binary64 rounding differences across platform libm implementations.
                assert v[key] == pytest.approx(expected, rel=0, abs=1e-15)
            else:
                assert v[key] == expected


def test_fourteen_failed_panels_are_all_misses_with_joint_holm():
    rows=[{'disease_id':f'MONDO_{i}',**pilot.recovery(None,'CHEMBL1')} for i in range(14)]
    methods=pilot.replication_statistics({m:deepcopy(rows) for m in ['jury',*pilot.B_MODELS,'direct_evidence','network_z']})
    assert len(methods)==6
    for v in methods.values():
        assert (v['panels'],v['hits'],v['mrr'])==(14,0,0)
        assert v['mrr_p_monte_carlo']==v['mrr_p_monte_carlo_holm']==1
        assert v['hits_p_one_sided']==pytest.approx(1)


def test_replication_full_frozen_run_and_pooled_report_offline(tmp_path, monkeypatch):
    from jury.client import ModelReply, mock_model
    from hashlib import sha256
    output,report=tmp_path/'data',tmp_path/'report'
    output.mkdir();report.mkdir()
    for name in ['protocol.md','protocol_frozen.json','candidates.json']:
        (report/name).write_bytes((Path('results/experiment_b_replication')/name).read_bytes())
    specs=[]; selected=[]
    for i in range(14):
        did=f'MONDO_{900000+i}';name=f'Synthetic disease {i}'
        selected.append([did,name,f'area{i%7}'])
        rows=[{'drug_id':f'CHEMBL{j}','name':f'Drug {j}'} for j in range(1,16)]
        specs.append({'disease':{'id':did,'name':name,'area':f'area{i%7}'},
            'true_drug':rows[0],'decoys':rows[1:],
            'matching':{'plausible_decoy_count':1,'eligible_plausible':1},'blind_exclusions':[]})
        packet={'experiment_id':'e965c62a-545d-4dbd-a7b8-bb775c4f9ef1',
            'disease':{'id':did,'name':name},'releases':['opentargets-26.09'],
            'candidates':[{'candidate_id':r['drug_id'],'label':f'C{j}','name':f'Agent C{j}',
                'targets':[{'id':'ENSG00000000001','name':'GENE','mechanism':'unknown'}],
                'evidence_ids':['E1'],'safety_status':'unknown'} for j,r in enumerate(rows,1)],
            'evidence':[{'id':'E1','kind':'target_association','source':'open_targets',
                'source_id':'synthetic','url':'https://example.org','release':'opentargets-26.09',
                'statement':'Synthetic Target association.','values':{'evidence_only_score':.5}}]}
        pilot.write_json(output/f'blind-{did}.json',packet)
        pilot.write_json(output/f'network-{did}.json',{'candidates':[
            {'candidate_id':r['drug_id'],'network':{'rank':j}} for j,r in enumerate(rows,1)]})
    pilot.write_json(output/'selection.json',{'selected':selected})
    pilot.write_json(output/'panels.json',{'panels':specs})
    pilot.write_json(output/'identities.json',{'drug_aliases':{f'CHEMBL{j}':[f'CHEMBL{j}'] for j in range(1,16)},'target_name_aliases':{}})
    jobs=pilot.b_jobs(output,replication=True)
    assert len(jobs)==42 and {j['condition'] for j in jobs}=={'pathways'}
    assert [j['disease_id'] for j in jobs][::3]==[s[0] for s in selected]
    # Synthetic run hashes only its tiny input files and the tracked prior result;
    # no ignored production data, API, graph artifact or credentials are required.
    monkeypatch.setattr(pilot,'replication_input_paths',lambda o,r:[
        r/'candidates.json',r/'protocol_frozen.json',Path('results/experiment_b/results.json')])
    ranking = tmp_path / 'scorer-checkout/ranking'
    ranking.mkdir(parents=True)
    for name in ['scoring.py', 'network.py', 'proximity.py', 'data.py', 'artifacts.py']:
        (ranking / name).write_text('# synthetic source for offline freeze test\n')
    monkeypatch.setenv('RANKING_ROOT', str(ranking.parent))
    declaration=pilot.freeze_b(output,report,replication=True)
    assert declaration['max_live_calls']==60
    assert not (output/'runs').exists()
    assert pilot.freeze_b(output,report,replication=True)==declaration
    attempt=pilot.b_live_attempt
    monkeypatch.setenv('SNOWFLAKE_REASONING_EFFORT',json.dumps(pilot.B_EFFORT))
    monkeypatch.setattr(pilot,'b_live_attempt',lambda job:attempt(job,lambda m,p:ModelReply(mock_model(m,p,0),10,20)))
    pilot.run_b(output,report,replication=True)
    result=pilot.score_b(output,report,replication=True)
    assert result['live_calls_including_retries']==42
    assert result['primary']['methods']['jury']['panels']==14
    assert result['secondary']['methods']['jury']['panels']==25
    assert result['methods']['direct_evidence']['hits']==14
    assert result['secondary']['methods']['direct_evidence']['hits']>=14
    assert result['protocol_sha256'] in (report/'results.md').read_text()
    assert len(json.loads((report/'audit_sample.json').read_text()))==18
    assert result['first_live_call_at']>result['frozen_at']
    (output/'panels.json').write_text('{}')
    with pytest.raises(ValueError,match='bytes changed'):
        pilot.score_b(output,report,replication=True)



@pytest.mark.parametrize('study,group', [('experiment_b', None),
    ('experiment_b_replication', 'primary'), ('experiment_b_replication', 'secondary')])
def test_all_published_statistics_recompute(study, group):
    root = Path(__file__).resolve().parents[3]
    published = json.loads((root / 'results' / study / 'results.json').read_text())
    methods = (published[group] if group else published)['methods']
    actual = pilot.replication_statistics({m: v['per_panel'] for m, v in methods.items()})
    assert actual.keys() == methods.keys()
    for method, expected in methods.items():
        assert actual[method].keys() == expected.keys()
        for key, value in expected.items():
            if isinstance(value, float):
                # Published numbers stay fixed; tolerate only binary64 rounding (absolute 1e-15).
                assert actual[method][key] == pytest.approx(value, rel=0, abs=1e-15)
            else:
                assert actual[method][key] == value
