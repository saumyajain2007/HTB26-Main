"""Offline source-mapping, fixed selection and packet-contract regressions."""
from tests.conftest import FIXTURES
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from jury.client import build_prompt, validate_packet, validate_reply, mock_model
from pipeline.pathways import download, load_pathways, memberships
from pipeline.packets import add_pathways

SAMPLE = Path(__file__).parent / 'data/pathways/Ensembl2Reactome.tsv'
G = 'ENSG00000096968'


def test_recorded_real_membership_and_blind_projection():
    ps, rejected = load_pathways(SAMPLE)
    assert len(ps['R-HSA-9006335']['genes']) == 5 and G in ps['R-HSA-9006335']['genes']
    assert rejected == {}
    packet = json.loads((FIXTURES / 'evidence_packet.json').read_text())
    ids = {e['id'] for e in packet['evidence'] if e['kind']=='pathway'}
    packet['evidence'] = [e for e in packet['evidence'] if e['id'] not in ids]
    packet['releases'].remove('reactome-97')
    for c in packet['candidates']:
        c['evidence_ids'] = [e for e in c['evidence_ids'] if e not in ids]
    original = deepcopy(packet)
    coverage = {}
    result = add_pathways(packet, json.loads((FIXTURES / 'disease_targets.json').read_text()), ps,
                          release='reactome-97', coverage=coverage)
    assert packet == original
    assert result == json.loads((FIXTURES / 'evidence_packet.json').read_text())
    validate_packet(result)
    prompt = build_prompt(result, [c['label'] for c in result['candidates']])
    assert 'shared membership does not establish effect' in prompt
    assert 'degree_matched_z' not in prompt and 'source_id' not in prompt
    assert validate_reply(mock_model('offline', prompt, 0), result)[0] is not None
    assert coverage['pathway_items'] == 1
    assert coverage['unmapped_items'] > 0


def test_fixed_cap_order_unique_gene_counts_and_no_symbol_joins(tmp_path):
    sample = SAMPLE.read_text()
    path = tmp_path / 'sample.tsv'
    path.write_text(sample + sample + sample.replace(G, 'JAK2') +
                    'ENSG00000096968\tR-MMU-1\thttps://reactome.org/content/detail/R-MMU-1\tMouse\tIEA\tMus musculus\n')
    ps, rejected = load_pathways(path)
    assert len(ps['R-HSA-9006335']['genes']) == 5
    assert rejected == {'not_Ensembl_gene_ID': 2, 'non_human_pathway': 1}
    genes = {f'ENSG{i:011d}' for i in range(301)}
    ps = {f'R-HSA-{i}': {'name': str(i), 'genes': set(sorted(genes)[:n])}
          for i,n in [(9,301),(8,300),(6,3),(5,2),(4,2),(3,2)]}
    assert [pid for pid,_ in memberships(ps, {'ENSG00000000000'}, {'ENSG00000000001'})] == ['R-HSA-3','R-HSA-4','R-HSA-5']
    assert memberships(ps, {'ENSG00000000000'}, {'ENSG00000000302'}) == []
    with pytest.raises(ValueError, match='Ensembl'):
        memberships(ps, {'JAK2'}, {G})
    assert [pid for pid,_ in memberships({'R-HSA-8':ps['R-HSA-8'], 'R-HSA-9':ps['R-HSA-9']}, {'ENSG00000000000'}, {'ENSG00000000001'})] == ['R-HSA-8']


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'], ids=['lf', 'crlf'])
def test_download_manifest_is_numbered_human_and_hashed(tmp_path, newline):
    rows = SAMPLE.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', newline)
    other = b'ENSMUSG00000000001\tR-MMU-1\thttps://reactome.org/content/detail/R-MMU-1\tMouse\tIEA\tMus musculus\n'
    def handle(request):
        return httpx.Response(200, text='97') if str(request.url).endswith('/version') else httpx.Response(200, content=rows+other)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        path, manifest = download(tmp_path, client=client)
        # The downloader canonicalizes retained rows to LF; source hashes cover original bytes.
        assert path.read_bytes() == rows.replace(b'\r\n', b'\n')
        from hashlib import sha256
        assert manifest['sha256'] == sha256(path.read_bytes()).hexdigest()
        assert manifest['download_sha256'] == sha256(rows + other).hexdigest()
        assert manifest['release'] == 'reactome-97'
        assert manifest['url'].endswith('/97/Ensembl2Reactome.txt')
        assert manifest['licence']['name'] == 'CC0-1.0'
        assert manifest['download_size_bytes'] > manifest['size_bytes']
        assert manifest['retrieved_at'] and len(manifest['download_sha256']) == 64
        assert download(tmp_path, client=client) == (path, manifest)
        path.write_text('corrupted')
        with pytest.raises(ValueError, match='checksum'):
            download(tmp_path, client=client)
