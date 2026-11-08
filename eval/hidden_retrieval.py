"""WS5 hidden-drug retrieval protocol. No data downloads or implicit defaults.

Inputs are JSON manifests with explicit SMILES, scores and provenance. The command
refuses to evaluate before all holdout datasets are audited and a freeze exists.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs, Descriptors

BASELINES = ('random', 'molecular_weight', 'docking_only', 'nearest_active')
DATASETS = ('training', 'calibration', 'generator_seeds', 'baseline_reference')
THRESHOLD = 0.5


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def molecule(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f'Invalid SMILES: {smiles!r}')
    return mol


def fingerprint(smiles):
    return AllChem.GetMorganGenerator(radius=2, fpSize=2048).GetFingerprint(molecule(smiles))


def similarity(a, b):
    return DataStructs.TanimotoSimilarity(fingerprint(a), fingerprint(b))


def assert_purged(hidden, sources):
    """Hard-fail if any holdout or analogue remains in any source."""
    if set(sources) != set(DATASETS):
        raise ValueError(f'Exactly these source sets required: {DATASETS}')
    hfp = fingerprint(hidden['smiles'])
    for source_name, records in sources.items():
        for item in records:
            sim = DataStructs.TanimotoSimilarity(hfp, fingerprint(item['smiles']))
            if sim > THRESHOLD:
                raise ValueError(f'LEAK: {hidden["id"]} in {source_name}: {item["id"]}, Tanimoto={sim:.4f}')
    return True


def validate_manifest(manifest):
    cases = manifest.get('cases', [])
    if not 3 <= len(cases) <= 5:
        raise ValueError('Must register 3–5 hidden-compound attempts before freezing')
    if len({c['hidden']['id'] for c in cases}) != len(cases):
        raise ValueError('Duplicate hidden compound')
    for case in cases:
        if not case.get('selection_reason') or not case.get('citation'):
            raise ValueError('Each case needs a selection reason and citation')
        hidden = case['hidden']
        molecule(hidden['smiles'])
        sources = case['purge_sources']
        assert_purged(hidden, sources)
        pool = case['pool']
        ids = [x['id'] for x in pool]
        if len(ids) != len(set(ids)) or hidden['id'] not in ids or len(ids) < 2:
            raise ValueError('Pool must have unique ids and include hidden compound and competitors')
        if not any(x.get('origin') == 'generated' for x in pool):
            raise ValueError('Pool must contain post-filter generated candidates')
        if not any(x.get('origin') == 'public_library' for x in pool):
            raise ValueError('Pool must contain public library entries')
        if not case.get('ledger_ref'):
            raise ValueError('Missing compute ledger reference')
        for entry in pool:
            molecule(entry['smiles'])
            if entry.get('docking_score') is None or entry.get('pipeline_score') is None:
                raise ValueError(f'Missing docking/pipeline score for {entry["id"]}')
        if not sources['baseline_reference']:
            raise ValueError('Nearest-active baseline requires a nonempty purged reference set')
    return True


def freeze(manifest_path, freeze_path):
    manifest = load(manifest_path)
    validate_manifest(manifest)
    if Path(freeze_path).exists():
        raise FileExistsError('Freeze already exists; use a new experiment version')
    record = {'protocol': 'ws5-hidden-retrieval-v1', 'manifest_sha256': digest(manifest_path),
              'tanimoto_cutoff': THRESHOLD, 'fingerprint': 'Morgan radius=2 2048 bits',
              'baselines': list(BASELINES), 'seed_list': manifest['seeds']}
    if not manifest['seeds'] or len(set(manifest['seeds'])) != len(manifest['seeds']):
        raise ValueError('Unique nonempty seeds required')
    Path(freeze_path).write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record


def percentile(order, target):
    """100 is best; 0 is worst, with zero-based rank normalization."""
    return 100 * (len(order) - 1 - order.index(target)) / (len(order) - 1)


def rank_case(case, seed):
    pool = case['pool']
    refs = [fingerprint(x['smiles']) for x in case['purge_sources']['baseline_reference']]
    rng = random.Random(seed)
    shuffled = sorted(pool, key=lambda x: x['id'])
    rng.shuffle(shuffled)
    def order(key, reverse=False):
        return [x['id'] for x in sorted(shuffled, key=key, reverse=reverse)]
    # Lower molecular weight is a predeclared naive preference, not an activity claim.
    # Docking convention: lower (more negative) is better.
    rankings = {
        'pipeline': order(lambda x: x['pipeline_score'], True),
        'random': [x['id'] for x in shuffled],
        'molecular_weight': order(lambda x: Descriptors.MolWt(molecule(x['smiles']))),
        'docking_only': order(lambda x: x['docking_score']),
        'nearest_active': order(lambda x: max(DataStructs.BulkTanimotoSimilarity(fingerprint(x['smiles']), refs)), True),
    }
    return {name: percentile(ids, case['hidden']['id']) for name, ids in rankings.items()}


def run(manifest_path, freeze_path, output_path):
    record = load(freeze_path)
    if record['manifest_sha256'] != digest(manifest_path) or record['protocol'] != 'ws5-hidden-retrieval-v1':
        raise ValueError('Frozen protocol mismatch; refusing to run')
    manifest = load(manifest_path)
    validate_manifest(manifest)
    if record['seed_list'] != manifest['seeds']:
        raise ValueError('Seed list changed after freeze')
    results = []
    for case in manifest['cases']:
        attempts = [rank_case(case, seed) for seed in manifest['seeds']]
        results.append({'hidden_id': case['hidden']['id'], 'selection_reason': case['selection_reason'],
                        'citation': case['citation'], 'ledger_ref': case['ledger_ref'],
                        'compute_spent': case.get('compute_spent'), 'seed_percentiles': attempts,
                        'mean_percentiles': {name: sum(x[name] for x in attempts)/len(attempts)
                                             for name in ('pipeline', *BASELINES)},
                        'note': 'Compute must be verified against ledger; this evaluator does not estimate cost.'})
    output = {'protocol_sha256': digest(freeze_path), 'status': 'evaluated', 'results': results}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['audit', 'freeze', 'run'])
    parser.add_argument('manifest')
    parser.add_argument('--freeze-file', required=False)
    parser.add_argument('--out')
    args = parser.parse_args()
    if args.command == 'audit':
        validate_manifest(load(args.manifest)); print('PASS: all holdouts purged and pools validated')
    elif args.command == 'freeze':
        if not args.freeze_file: parser.error('--freeze-file required')
        print(freeze(args.manifest, args.freeze_file))
    else:
        if not args.freeze_file or not args.out: parser.error('--freeze-file and --out required')
        print(run(args.manifest, args.freeze_file, args.out))

if __name__ == '__main__':
    main()
