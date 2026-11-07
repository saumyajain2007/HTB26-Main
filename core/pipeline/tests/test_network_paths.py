"""Offline packet projection checks; graph reconstruction belongs to ranking."""
from tests.conftest import FIXTURES
from copy import deepcopy
import json
from urllib.parse import parse_qs, urlparse

import pytest

from jury.client import PROMPT_VERSION, build_prompt, validate_packet
from pipeline.packets import add_network_paths

GENE = 'ENSG00000068078'


def base_packet():
    packet = json.loads((FIXTURES / 'evidence_packet.json').read_text())
    removed = {e['id'] for e in packet['evidence'] if e['kind']=='pathway'}
    packet['evidence'] = [e for e in packet['evidence'] if e['id'] not in removed]
    packet['releases'] = [r for r in packet['releases'] if not r.startswith('reactome-')]
    for c in packet['candidates']:
        c['evidence_ids'] = [e for e in c['evidence_ids'] if e not in removed]
    return packet


def inputs():
    packet = base_packet()
    item = packet['evidence'].pop()
    assert item['kind'] == 'network_path'
    for c in packet['candidates']:
        c['evidence_ids'] = [e for e in c['evidence_ids'] if e != item['id']]
    path = dict(drug_target_id=GENE, disease_target_id=GENE, target_ids=[GENE],
                hops=0, status='available', graph_version='string-12.5')
    candidates = [dict(candidate_id=c['candidate_id'], network={'mean_distance':987.65,
        'degree_matched_z':-765.43,'rank':999}, direct_evidence_rank=888,
        network_paths={'paths':[path] if c['candidate_id']=='CHEMBL3545376' else [],
            'complete_path_count':777, 'retained_drug_target_count':666}) for c in packet['candidates']]
    kwargs = dict(graph={'graph_version':'string-12.5','undirected':True,
        'filters':dict(combined_score_min=700,experiments_min=400,
                       direct_experiments_column='experiments',transferred_experiments_used_as_direct=False),
        'artifact_files':{'graph.npz':{'sha256':item['source_id'].split('@')[1]}}},
        target_names={GENE:'FGFR3'}, string_mappings=[dict(status='mapped',target_id=GENE,
            string_id='9606.ENSP00000339824')], disease_target_ids={GENE})
    return packet, candidates, kwargs


def test_paths_are_id_resolved_and_scores_never_enter_packet():
    packet, candidates, kwargs = inputs()
    before = deepcopy((packet,candidates,kwargs))
    enriched = add_network_paths(packet,candidates,**kwargs)
    assert (packet,candidates,kwargs) == before
    assert enriched == base_packet()
    validate_packet(enriched)
    item = enriched['evidence'][-1]
    assert item['values'] == {'hops':0}
    url = parse_qs(urlparse(item['url']).query)
    assert url['identifiers'] == ['9606.ENSP00000339824']
    text = json.dumps(enriched)
    for forbidden in ['mean_distance','degree_matched_z','rank','path_count','987.65','-765.43']:
        assert forbidden not in text
    prompt = build_prompt(enriched,[c['label'] for c in enriched['candidates']])
    assert PROMPT_VERSION == 'jury-v7'
    assert 'graph is undirected' in prompt and 'not a proven mechanism' in prompt


def test_missing_mapping_is_counted_without_name_fallback():
    packet,candidates,kwargs = inputs()
    kwargs['target_names'] = {'FGFR3': 'FGFR3'}
    coverage = {}
    result = add_network_paths(packet,candidates,coverage=coverage,**kwargs)
    assert not any(e['kind']=='network_path' for e in result['evidence'])
    assert coverage['unmapped_items'] == 1
    assert coverage['unmapped'][0]['status'] == 'unmapped'


@pytest.mark.parametrize('mutation', ['hops','endpoint','too_many','filter','ambiguous'])
def test_bad_paths_and_provenance_fail_closed(mutation):
    packet,candidates,kwargs = inputs()
    candidate = next(c for c in candidates if c['network_paths']['paths'])
    path = candidate['network_paths']['paths'][0]
    if mutation == 'hops': path['hops'] = 1
    if mutation == 'endpoint': kwargs['disease_target_ids'] = set()
    if mutation == 'too_many': candidate['network_paths']['paths'] *= 4
    if mutation == 'filter': kwargs['graph']['filters']['experiments_min'] = 0
    if mutation == 'ambiguous': kwargs['string_mappings'].append(dict(status='mapped',target_id='ENSG00000123456',string_id='9606.ENSP00000339824'))
    with pytest.raises(ValueError):
        add_network_paths(packet,candidates,**kwargs)


def test_multistep_template_and_identical_paths_share_one_record():
    packet,candidates,kwargs = inputs()
    # Synthetic two-hop route exercises projection only, not graph validation.
    middle,end = 'ENSG00000162434','ENSG00000105397'
    path = dict(drug_target_id=GENE,disease_target_id=end,target_ids=[GENE,middle,end],
                hops=2,status='available',graph_version='string-12.5')
    candidate=next(c for c in candidates if c['network_paths']['paths'])
    candidate['network_paths']['paths']=[path]
    kwargs['target_names'].update({middle:'JAK1',end:'TYK2'})
    kwargs['disease_target_ids']={end}
    kwargs['string_mappings'] += [dict(status='mapped',target_id=middle,string_id='9606.ENSP00000343204'),
                                dict(status='mapped',target_id=end,string_id='9606.ENSP00000264868')]
    result=add_network_paths(packet,candidates,**kwargs)
    item=result['evidence'][-1]
    assert item['values']=={'hops':2}
    assert 'in 2 steps: FGFR3 – JAK1 – TYK2.' in item['statement']
    assert item['source_id'].startswith('>'.join([GENE,middle,end])+'@')
    assert parse_qs(urlparse(item['url']).query)['identifiers']==[
        '9606.ENSP00000339824\r9606.ENSP00000343204\r9606.ENSP00000264868']
    # A single source path reused by two Candidates has one E ID.
    duplicate=deepcopy(packet['candidates'][2])
    duplicate.update(label='C5',candidate_id='CHEMBL9999999')
    packet['candidates'].append(duplicate)
    candidates.append(dict(candidate_id=duplicate['candidate_id'],network_paths={'paths':[path]}))
    result=add_network_paths(packet,candidates,**kwargs)
    assert sum(e['kind']=='network_path' for e in result['evidence'])==1
    linked=[c for c in result['candidates'] if result['evidence'][-1]['id'] in c['evidence_ids']]
    assert len(linked)==2
