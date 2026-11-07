from tests.conftest import FIXTURES
from copy import deepcopy
import json
from pathlib import Path

import pytest

from pipeline.panels import build_panels, packet_leakage


def universe():
    return {"releases": ["opentargets-26.09", "chembl-37"], "coverage": {}, "drugs": [
        {"drug_id": f"CHEMBL{i}", "name": f"display {i}",
         "source_chembl_ids": [f"CHEMBL{i}"],
         "targets": [{"target_id": f"ENSG{j:011d}"} for j in range(1 if i < 18 else 3)],
         "approval": {"sources": ["FDA"], "disease_ids": ["MONDO_1"] if i == 1 else ["MONDO_2"]}}
        for i in range(1, 24)]}


def test_seeded_panel_eligibility_and_nearest_matching():
    source = universe()
    diseases = [{"id": "MONDO_1", "name": "Disease", "area": "area"}]
    result = build_panels(source, diseases, clinical_records={"MONDO_1": set()}, seed=42)
    assert result == build_panels(source, diseases, clinical_records={"MONDO_1": set()}, seed=42)
    source["drugs"].reverse()
    assert result == build_panels(source, diseases, clinical_records={"MONDO_1": set()}, seed=42)
    panel = result["panels"][0]
    assert panel["true_drug"]["drug_id"] == "CHEMBL1"
    assert len(panel["decoys"]) == len({d['drug_id'] for d in panel['decoys']}) == 14
    assert all(d["target_count_difference"] == 0 for d in panel["decoys"])
    assert all("MONDO_1" not in d["approval"]["disease_ids"] for d in panel["decoys"])


def test_excludes_unmapped_unapproved_and_worked_examples():
    source = universe()
    source["drugs"][0]["targets"] = []
    with pytest.raises(ValueError, match="No mapped"):
        build_panels(source, [{"id": "MONDO_1"}], clinical_records={"MONDO_1": set()})
    source = universe()
    source["drugs"][0]["approval"]["sources"] = ["ATC"]
    with pytest.raises(ValueError, match="No mapped"):
        build_panels(source, [{"id": "MONDO_1"}], clinical_records={"MONDO_1": set()})
    with pytest.raises(ValueError, match="Worked examples"):
        build_panels(universe(), [{"id": "MONDO_0009693"}], clinical_records={"MONDO_0009693": set()})
    with pytest.raises(ValueError, match="14 eligible"):
        short = universe()
        short["drugs"] = short["drugs"][:14]
        build_panels(short, [{"id": "MONDO_1"}], clinical_records={"MONDO_1": set()})


def test_packet_indication_screen():
    packet = json.loads((FIXTURES / "evidence_packet.json").read_text())
    assert packet_leakage(packet) == []
    leaked = deepcopy(packet)
    leaked["evidence"][0]["statement"] = "Approved for the panel's Disease in a clinical trial."
    assert packet_leakage(leaked)


def test_reuses_batch_target_cache_by_id_with_provenance(tmp_path):
    from pipeline.panels import PilotSources, seed_target_cache
    data, output = tmp_path / "data", tmp_path / "pilot"
    cache = data / "chembl-37"
    cache.mkdir(parents=True)
    target = {"target_chembl_id": "CHEMBL123", "organism": "Homo sapiens",
              "target_type": "SINGLE PROTEIN", "target_components": [{"accession": "P12345"}]}
    (cache / "batch.json").write_text(json.dumps({"release": "chembl-37", "retrieved_at": "2026-10-24",
        "request": {"url": "https://www.ebi.ac.uk/chembl/api/data/target.json", "params": {}},
        "response": {"targets": [target]}}))
    (cache / "status.json").write_text(json.dumps({"release": "chembl-37", "response": {"targets": 123}}))
    seed_target_cache(data, output)
    sources = PilotSources(data, output, offline=True)
    assert sources.chembl("target/CHEMBL123.json") == target
    saved_path = next((output / "packets/http/chembl-37").glob("*.json"))
    saved = json.loads(saved_path.read_text())
    assert saved["derived_from"]["path"] == str(cache / "batch.json")
    first = saved_path.read_bytes()
    seed_target_cache(data, output)
    assert saved_path.read_bytes() == first


def test_removes_only_affected_decoys_including_records_on_salts():
    source = universe()
    diseases = [{"id": "MONDO_1", "name": "Disease"}]
    old = build_panels(source, diseases, clinical_records={"MONDO_1": set()}, seed=42)['panels'][0]
    removed = old['decoys'][0]['drug_id']
    next(d for d in source['drugs'] if d['drug_id'] == removed)['source_chembl_ids'].append('CHEMBL9999')
    new = build_panels(source, diseases, clinical_records={"MONDO_1": {'CHEMBL9999'}}, seed=42)['panels'][0]
    assert new['true_drug'] == old['true_drug']
    old_ids = {d['drug_id'] for d in old['decoys']}
    new_ids = {d['drug_id'] for d in new['decoys']}
    assert old_ids - new_ids == {removed}
    assert len(new_ids - old_ids) == 1
    assert all(d['target_count_difference'] == 0 for d in new['decoys'])


def test_v2_requires_seven_true_top50_decoys_and_no_records():
    from pipeline.panels import build_v2_panel
    source = universe()
    # Synthetic mechanical test: source IDs and counts are not scientific results.
    for i, d in enumerate(source['drugs']):
        d['targets'] = [{'target_id': f'ENSG{(1 if i < 12 else 2):011d}'}]
    true = source['drugs'][0]
    disease = {'id': 'MONDO_1', 'name': 'Test disease'}
    top = {'targets': [{'target_id': 'ENSG00000000001'}]}
    p = build_v2_panel(source, disease, true, top, {'ENSG00000000001': .8}, blocked={'CHEMBL2'}, seed=42)
    assert len(p['decoys']) == 14 and sum(d['plausible'] for d in p['decoys']) >= 7
    assert all(d['target_count_difference'] == 0 and d['drug_id'] != 'CHEMBL2' for d in p['decoys'])
    assert p == build_v2_panel(source, disease, true, top, {'ENSG00000000001': .8}, blocked={'CHEMBL2'}, seed=42)
    with pytest.raises(ValueError, match='seven'):
        build_v2_panel(source, disease, true, {'targets': []}, {}, blocked=set(), seed=42)


def test_v2_missing_parent_hierarchy_requires_an_explicit_source_link(monkeypatch):
    from pipeline.panels import V2Sources, PilotSources
    recorded = {'molecule_chembl_id': 'CHEMBL3707224', 'molecule_hierarchy': None}
    monkeypatch.setattr(PilotSources, 'chembl', lambda self, endpoint: recorded)
    source = V2Sources(offline=True)
    assert source.chembl('molecule/CHEMBL3707224.json')['molecule_hierarchy'] is None
    # The recorded bromide row explicitly names CHEMBL3707224 as its parent.
    source.parent_links['CHEMBL3707224'] = ['CHEMBL3707223']
    assert source.chembl('molecule/CHEMBL3707224.json')['molecule_hierarchy'] == {'parent_chembl_id': 'CHEMBL3707224'}
    assert recorded['molecule_hierarchy'] is None


def test_experiment_b_true_selection_uses_ids_and_blocks_override_decoys():
    from pipeline.panels import build_b_panel
    source = universe()
    for i,d in enumerate(source['drugs']):
        d['targets'] = [{'target_id':'ENSG00000000001'}]
    source['drugs'][1]['approval']['overrides'] = [{'disease_id':'MONDO_1','url':'https://www.accessdata.fda.gov/example'}]
    panel = build_b_panel(source, {'id':'MONDO_1'}, {'targets':[{'target_id':'ENSG00000000001'}]},
                          {'ENSG00000000001':.5}, blocked=set(), index=0)
    assert panel['true_drug']['drug_id'] in {'CHEMBL1','CHEMBL2'}
    assert not {'CHEMBL1','CHEMBL2'}.intersection(d['drug_id'] for d in panel['decoys'])
    assert len(panel['decoys'])==14
    reversed_source = {**source,'drugs':list(reversed(source['drugs']))}
    assert panel == build_b_panel(reversed_source, {'id':'MONDO_1'}, {'targets':[{'target_id':'ENSG00000000001'}]},
                          {'ENSG00000000001':.5}, blocked=set(), index=0)


@pytest.mark.parametrize('plausible_count', [0, 1, 6, 7, 12])
def test_amendment_1_uses_available_plausible_then_fills_every_panel(plausible_count):
    from pipeline.panels import build_v2_panel
    source=universe()
    for i,drug in enumerate(source['drugs'][1:]):
        drug['targets']=[{'target_id':f'ENSG{(1 if i<plausible_count else 2):011d}'}]
    panel=build_v2_panel(source,{'id':'MONDO_1'},source['drugs'][0],
        {'targets':[{'target_id':'ENSG00000000001'}]}, {'ENSG00000000001':.5},
        blocked=set(),seed=42,allow_plausible_shortfall=True)
    assert len(panel['decoys'])==14
    assert panel['matching']['eligible_plausible']==plausible_count
    assert panel['matching']['plausible_priority_slots']==min(7,plausible_count)
    assert panel['matching']['plausible_decoy_count']==sum(d['plausible'] for d in panel['decoys'])
    if plausible_count<7:
        assert sum(d['plausible'] for d in panel['decoys'])==plausible_count


def test_amendment_1_exclusions_keep_seeded_priority_and_replace_true():
    from pipeline.panels import build_b_panel
    source=universe();source['drugs'][1]['approval']['disease_ids']=['MONDO_1']
    kwargs=dict(blocked=set(),index=0)
    args=(source,{'id':'MONDO_1'},{'targets':[{'target_id':'ENSG00000000000'}]}, {})
    original=build_b_panel(*args,**kwargs)
    excluded={original['true_drug']['drug_id']}
    replacement=build_b_panel(*args,excluded_ids=excluded,**kwargs)
    assert replacement['true_drug']['drug_id']==original['true_drug_priority'][1]
    assert replacement['true_drug_priority']==original['true_drug_priority']
    # Excluding a decoy advances within its matching order, leaving other priorities fixed.
    decoy=original['decoys'][2]['drug_id']
    refilled=build_b_panel(*args,excluded_ids={decoy},**kwargs)
    assert refilled['true_drug']==original['true_drug']
    assert [d['drug_id'] for d in refilled['decoys']][:13]==[d['drug_id'] for d in original['decoys'] if d['drug_id']!=decoy]


def test_amendment_1_collision_uses_exact_aliases_and_id_anchored_symbols():
    from pipeline.panels import unblindable_candidates
    packet={'candidates':[
        {'candidate_id':'CHEMBL1','name':'a drug','targets':[{'id':'ENSG00000000001','name':'display'}]},
        {'candidate_id':'CHEMBL2','name':'PDGFB','targets':[]}],
        'evidence':[{'kind':'network_path','source_id':'ENSG00000000002>ENSG00000000001@hash','statement':'JAK1 connects to PDGFB.'}]}
    symbols={'ENSG00000000001':'PDGFB','ENSG00000000002':'JAK1'}
    aliases={'CHEMBL1':[' Pdgfb ','PDGF'],'CHEMBL2':[]}
    excluded=unblindable_candidates(packet,aliases,symbols)
    assert [e['candidate_id'] for e in excluded]==['CHEMBL1','CHEMBL2']
    assert excluded[0]['matching_aliases']==[' Pdgfb ']
    assert excluded[0]['target_ids']==['ENSG00000000001']
    aliases['CHEMBL1']=['PDGF']
    assert len(unblindable_candidates(packet,aliases,symbols))==1


def test_amendment_1_local_ids_skip_aliases_without_changing_evidence():
    from pipeline.panels import avoid_identity_label_collisions
    packet={'candidates':[{'candidate_id':'CHEMBL1','label':'C1','name':'source name',
                           'evidence_ids':['E1','E2']}],
            'evidence':[{'id':'E1','statement':'First source statement','values':{'n':2}},
                        {'id':'E2','statement':'A protein and its biology','values':{}}]}
    original=deepcopy(packet)
    result,changes=avoid_identity_label_collisions(packet,{'CHEMBL1':['E2','C1']})
    assert packet==original
    assert [e['id'] for e in result['evidence']]==['E1','E3']
    assert result['candidates'][0]['label']=='C2'
    assert result['candidates'][0]['evidence_ids']==['E1','E3']
    assert changes=={'id':{'E2':'E3'},'label':{'C1':'C2'}}
    assert [{k:v for k,v in e.items() if k!='id'} for e in result['evidence']]==[
        {k:v for k,v in e.items() if k!='id'} for e in packet['evidence']]


def test_ranking_root_defaults_to_repo_and_accepts_env_and_argument(tmp_path, monkeypatch):
    from pipeline.panels import resolve_ranking_root
    monkeypatch.delenv('RANKING_ROOT', raising=False)
    monkeypatch.chdir(tmp_path)
    assert resolve_ranking_root() == Path(__file__).resolve().parents[3] / 'core'
    monkeypatch.setenv('RANKING_ROOT', str(tmp_path / 'configured'))
    assert resolve_ranking_root() == tmp_path / 'configured'
    assert resolve_ranking_root(tmp_path / 'explicit') == tmp_path / 'explicit'


@pytest.mark.parametrize('explicit', [False, True])
def test_replication_uses_configured_protocol_before_preparing_inputs(tmp_path, monkeypatch, explicit):
    from pipeline.panels import select_replication
    configured = tmp_path / 'configured'
    monkeypatch.setenv('RANKING_ROOT', str(tmp_path / 'wrong' if explicit else configured))
    kwargs = {'ranking_root': configured} if explicit else {}
    with pytest.raises(FileNotFoundError) as error:
        select_replication(output=tmp_path / 'output', offline=True, **kwargs)
    assert Path(error.value.filename) == configured / 'ranking/cohort_protocol.json'
    assert not (tmp_path / 'output').exists()
