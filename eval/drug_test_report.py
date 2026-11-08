"""WS5 report generator for REAL frozen retrieval runs; refuses incomplete evidence."""
import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path

METHODS = ('pipeline', 'random', 'molecular_weight', 'docking_only', 'nearest_active')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bootstrap_ci(values, seed=2026, replicates=2000):
    if not values or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError('Nonempty finite seed values required')
    if len(values) == 1:
        return None  # No seed variability can be estimated.
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(replicates))
    return [means[int(.025 * (replicates - 1))], means[int(.975 * (replicates - 1))]]


def build_report(results_path, manifest_path, freeze_path, ledger_path):
    results = json.loads(Path(results_path).read_text(encoding='utf8'))
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf8'))
    frozen = json.loads(Path(freeze_path).read_text(encoding='utf8'))
    ledger = json.loads(Path(ledger_path).read_text(encoding='utf8'))
    if frozen.get('manifest_sha256') != sha256(manifest_path):
        raise ValueError('Manifest differs from frozen protocol')
    if results.get('protocol_sha256') != sha256(freeze_path):
        raise ValueError('Results differ from frozen protocol')
    cases = manifest.get('cases', [])
    if len(cases) not in (3, 4, 5) or len(results.get('results', [])) != len(cases):
        raise ValueError('Every one of 3–5 preregistered attempts must be reported')
    ids = [c['hidden']['id'] for c in cases]
    by_id = {r['hidden_id']: r for r in results['results']}
    if len(by_id) != len(ids) or set(by_id) != set(ids):
        raise ValueError('Results missing, duplicated or unexpected compounds')
    if ledger.get('protocol_sha256') != sha256(freeze_path):
        raise ValueError('Ledger not bound to frozen protocol')
    ledger_cases = ledger.get('cases', {})
    if set(ledger_cases) != set(ids):
        raise ValueError('Ledger missing or extra cases')
    rows = []
    for case in cases:
        cid = case['hidden']['id']
        r = by_id[cid]
        attempts = r.get('seed_percentiles', [])
        if len(attempts) != len(manifest['seeds']) or not attempts:
            raise ValueError(f'Seed count mismatch for {cid}')
        costs = ledger_cases[cid]
        if set(costs) != set(METHODS):
            raise ValueError(f'Missing baseline costs for {cid}')
        for method in METHODS:
            vals = [a[method] for a in attempts]
            if not all(0 <= v <= 100 for v in vals):
                raise ValueError('Percentiles must be in [0,100]')
            cost = costs[method]
            if not isinstance(cost, dict) or not isinstance(cost.get('amount'), (int, float)) or not math.isfinite(cost['amount']) or cost['amount'] < 0 or not cost.get('unit') or not cost.get('source_ref'):
                raise ValueError(f'Unverified cost for {cid}/{method}')
            ci = bootstrap_ci(vals)
            rows.append({'hidden_id': cid, 'method': method, 'n_seeds': len(vals),
                         'mean_percentile': round(sum(vals)/len(vals), 4),
                         'ci95_low': '' if ci is None else round(ci[0], 4),
                         'ci95_high': '' if ci is None else round(ci[1], 4),
                         'compute_amount': cost['amount'], 'compute_unit': cost['unit'],
                         'compute_source_ref': cost['source_ref'],
                         'selection_reason': case['selection_reason'],
                         'failure_analysis': r.get('failure_analysis', '')})
        if not r.get('failure_analysis'):
            raise ValueError(f'Failure/limitation analysis required for every case: {cid}')
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', required=True)
    p.add_argument('--manifest', required=True)
    p.add_argument('--freeze', required=True)
    p.add_argument('--ledger', required=True)
    p.add_argument('--out', required=True)
    args = p.parse_args()
    rows = build_report(args.results, args.manifest, args.freeze, args.ledger)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f'Wrote {len(rows)} real result rows to {out}')

if __name__ == '__main__':
    main()
