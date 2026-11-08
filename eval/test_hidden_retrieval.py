import json
import pytest
from eval.hidden_retrieval import assert_purged, percentile, freeze, run


def test_leak_crashes():
    sources = {k: [] for k in ('training', 'calibration', 'generator_seeds', 'baseline_reference')}
    sources['training'] = [{'id': 'same', 'smiles': 'CCO'}]
    with pytest.raises(ValueError, match='LEAK'):
        assert_purged({'id': 'hidden', 'smiles': 'CCO'}, sources)


def test_missing_source_crashes():
    with pytest.raises(ValueError, match='Exactly'):
        assert_purged({'id': 'h', 'smiles': 'CCO'}, {})


def test_percentiles():
    assert percentile(['a', 'b', 'c'], 'a') == 100
    assert percentile(['a', 'b', 'c'], 'c') == 0


def test_no_fabricated_freeze(tmp_path):
    p = tmp_path / 'empty.json'
    p.write_text(json.dumps({'cases': [], 'seeds': [1]}))
    with pytest.raises(ValueError, match='3–5'):
        freeze(p, tmp_path / 'freeze.json')


def test_run_requires_real_freeze(tmp_path):
    with pytest.raises(FileNotFoundError):
        run(tmp_path / 'missing.json', tmp_path / 'missing_freeze.json', tmp_path / 'out.json')
