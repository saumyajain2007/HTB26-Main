"""Offline checks for the selection-only runner and failure-aware scoring."""
from tests.conftest import FIXTURES
import json
from pathlib import Path

import pytest

from jury import pilot
from jury.client import ModelReply, mock_model
from test_pilot import _v2_fixture


@pytest.fixture
def bakeoff(tmp_path, monkeypatch):
    output, report = tmp_path / 'data', tmp_path / 'report'
    output.mkdir(); report.mkdir()
    _v2_fixture(output)
    for name in ['coverage.json', 'provenance.json']:
        pilot.write_json(output / name, [] if name == 'coverage.json' else {'inputs_sha256': {}})
    (report / 'protocol.md').write_text('Synthetic offline protocol, no scientific results.')
    monkeypatch.delenv('SNOWFLAKE_REASONING_EFFORT', raising=False)
    return output, report


def test_bakeoff_jobs_and_frozen_inputs(bakeoff):
    output, report = bakeoff
    jobs = pilot.bakeoff_jobs(output)
    assert len(jobs) == 30
    assert {j['model'] for j in jobs} == set(pilot.BAKEOFF_MODELS)
    assert all(j['condition'] == 'blind' and j['reasoning_effort'] == pilot.BAKEOFF_EFFORT for j in jobs)
    assert pilot.BAKEOFF_EFFORT['grok-4.7'] is None
    assert all(j['prompt'].endswith('}') for j in jobs)
    assert pilot.freeze_bakeoff(output, report) == pilot.freeze_bakeoff(output, report)
    (output / 'coverage.json').write_text('[{"changed": true}]')
    with pytest.raises(ValueError, match='changed'):
        pilot.freeze_bakeoff(output, report)


def test_bakeoff_shared_dispatch_caps_all_failures_and_resume(bakeoff, monkeypatch):
    output, report = bakeoff
    calls = []
    fail_adapter = pilot.b_live_attempt
    # Keep the production attempt adapter, substituting only the transport.
    def dispatch(job):
        run = json.loads(Path(job['path']).read_text())
        assert run['attempts'][-1]['status'] == 'reserved'
        calls.append(job['model'])
        return fail_adapter(job, lambda *a: (_ for _ in ()).throw(RuntimeError('secret must not be persisted')))
    monkeypatch.setattr(pilot, 'b_live_attempt', dispatch)
    pilot.run_b(output, report, bakeoff=True)
    pilot.run_b(output, report, bakeoff=True)
    assert len(calls) == 40
    assert sum(len(json.loads(p.read_text())['attempts']) for p in (output/'runs').glob('*.json')) == 40
    assert not (output / 'live.lock').exists()
    result = pilot.score_bakeoff(output, report)
    assert result['calls_used'] == 40
    assert all(m['valid_ballots'] == m['hits'] == m['mrr'] == 0 for m in result['models'].values())
    assert all(m['token_usage']['input_tokens']['total'] is None for m in result['models'].values())
    assert all(j['panels_with_consensus'] == 0 for j in result['juries'].values())
    assert 'secret must not be persisted' not in (report / 'results.json').read_text()


def test_bakeoff_revalidates_refusals_partial_juries_and_usage(bakeoff, monkeypatch):
    output, report = bakeoff
    adapter = pilot.b_live_attempt
    def dispatch(job):
        def reply(model, prompt):
            if model == 'openai-gpt-5.4':
                return ModelReply(mock_model(model, prompt, 0), 10, 20, stop_reason='refusal')
            if model == 'grok-4.7':
                raise TimeoutError('secret')
            return ModelReply(mock_model(model, prompt, 0), 10, 20)
        return adapter(job, reply)
    monkeypatch.setattr(pilot, 'b_live_attempt', dispatch)
    pilot.run_b(output, report, bakeoff=True)
    result = pilot.score_bakeoff(output, report)
    assert result['calls_used'] == 40
    assert result['models']['openai-gpt-5.5']['valid_ballots'] == 6
    assert result['models']['openai-gpt-5.5']['token_usage']['input_tokens']['total'] == 60
    assert result['models']['openai-gpt-5.4']['refusals'] >= 6
    two = result['juries']['openai-gpt-5.4+glm-5.3+kimi-k3']
    assert two['panels_with_consensus'] == 6 and two['three_valid_panels'] == 0
    assert all(r['consensus_status']['jurors_counted'] == 2 for r in two['per_panel'])
    one = result['juries']['openai-gpt-5.4+kimi-k3+grok-4.7']
    assert one['panels_with_consensus'] == one['hits'] == one['mrr'] == 0
    assert result['recommended_jury'] == 'openai-gpt-5.5+glm-5.3+kimi-k3'
    run_path = next((output / 'runs').glob('*openai-gpt-5.5*.json'))
    run = json.loads(run_path.read_text())
    run['attempts'][0]['reviews'][0]['rank'] = 999
    pilot.write_json(run_path, run)
    with pytest.raises(ValueError, match='revalidation'):
        pilot.score_bakeoff(output, report)


def test_bakeoff_passes_effort_to_current_adapter(tmp_path, monkeypatch):
    packet = json.loads((FIXTURES / 'evidence_packet.json').read_text())
    job = {'path': str(tmp_path / 'run.json'), 'model': 'grok-4.7', 'condition': 'blind',
           'disease_id': packet['disease']['id'], 'packet': packet, 'name_aliases': [],
           'prompt': pilot.build_prompt(packet, [c['label'] for c in packet['candidates']]),
           'reasoning_effort': pilot.BAKEOFF_EFFORT}
    monkeypatch.delenv('SNOWFLAKE_REASONING_EFFORT', raising=False)
    class Adapter:
        def __init__(self, *, reasoning_effort):
            self.reasoning_effort = reasoning_effort
            assert reasoning_effort['grok-4.7'] is None
        def __call__(self, model, prompt, temperature):
            assert temperature == 0
            return ModelReply(mock_model(model, prompt, temperature), 10, 20)
        def close(self):
            pass
    monkeypatch.setattr(pilot, 'CortexModel', Adapter)
    pilot.write_json(Path(job['path']), {'attempts': [{'attempt': 1, 'status': 'reserved'}]})
    assert pilot.b_live_attempt(job)['status'] == 'valid'


def test_prepare_reblinds_new_pathway_aliases_without_changing_panels(tmp_path):
    from hashlib import sha256
    data = tmp_path / 'data'
    source, paths, reactome = data / 'pilot/v2', data / 'pilot/v2_paths', data / 'reactome/97'
    for root in [source, paths, reactome, data / 'a6_paths']:
        root.mkdir(parents=True)
    _v2_fixture(source)
    for name in ['panels.json', 'identities.json']:
        (paths / name).write_bytes((source / name).read_bytes())
    (paths / 'reconstruct.py').write_text('# synthetic recorded export')
    panels = json.loads((source / 'panels.json').read_text())['panels']
    coverage = {}
    for panel in panels:
        did = panel['disease']['id']
        packet = json.loads((source / f'blind-{did}.json').read_text())
        assert any(e['kind'] == 'network_path' for e in packet['evidence'])
        removed = {e['id'] for e in packet['evidence'] if e['kind'] == 'pathway'}
        packet['evidence'] = [e for e in packet['evidence'] if e['id'] not in removed]
        for candidate in packet['candidates']:
            candidate['evidence_ids'] = [e for e in candidate['evidence_ids'] if e not in removed]
        pilot.write_json(paths / f'blind-{did}.json', packet)
        pilot.write_json(paths / f'paths-{did}.json', {'graph': {'artifact_files': {}}})
        pilot.write_json(source / f'targets-{did}.json', {'disease_id': did,
            'release': 'opentargets-26.09', 'targets': [{'target_id': 'ENSG00000162434'}]})
        coverage[f'pilot/{did}'] = {'unmapped_items': 0, 'unmapped': []}
    pilot.write_json(data / 'a6_paths/coverage.json', coverage)
    mapping = reactome / 'Ensembl2Reactome.human.tsv'
    mapping.write_text('ENSG00000162434\tR-HSA-123\thttps://reactome.org/content/detail/R-HSA-123\tMockDrug1 signaling\tTAS\tHomo sapiens\n')
    pilot.write_json(reactome / 'manifest.json', {'release': 'reactome-97', 'sha256': sha256(mapping.read_bytes()).hexdigest()})
    output = data / 'bakeoff'
    pilot.prepare_bakeoff(output, data)
    jobs = pilot.bakeoff_jobs(output)  # Known-alias scan must pass after enrichment.
    assert len(jobs) == 30
    assert (output / 'panels.json').read_bytes() == (source / 'panels.json').read_bytes()
    packet = jobs[0]['packet']
    pathways = [e for e in packet['evidence'] if e['kind'] == 'pathway']
    assert pathways and all('MockDrug1' not in e['statement'] for e in pathways)
    assert pathways[0]['source_id'] == 'R-HSA-123'
    assert pathways[0]['values'] == {'pathway_gene_count': 1}
