import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('drug_test_report', Path(__file__).with_name('drug_test_report.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_bootstrap_is_deterministic():
    assert m.bootstrap_ci([20, 40, 60]) == m.bootstrap_ci([20, 40, 60])


def test_one_seed_has_no_interval():
    assert m.bootstrap_ci([50]) is None


def test_empty_rejected():
    with pytest.raises(ValueError):
        m.bootstrap_ci([])


def test_invalid_percentiles_rejected():
    with pytest.raises(ValueError):
        m.bootstrap_ci([float('nan')])


def test_missing_inputs_fail_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        m.build_report(tmp_path/'results.json', tmp_path/'manifest.json', tmp_path/'freeze.json', tmp_path/'ledger.json')
