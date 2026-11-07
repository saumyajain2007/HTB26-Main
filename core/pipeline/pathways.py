"""Lowest-level Reactome memberships, joined only through Ensembl gene IDs."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

import httpx

VERSION_URL = 'https://reactome.org/ContentService/data/database/version'
MAX_GENES = 300
MAX_PATHWAYS = 3
LICENCE = {
    'name': 'CC0-1.0', 'url': 'https://reactome.org/license',
    'terms_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'redistribution': 'Reactome database and derived data are CC0; attribution encouraged.',
}


def download(data_dir='data', *, client=None):
    """Pin a numbered release; retain human rows and hash the original download."""
    owned = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        response = client.get(VERSION_URL)
        response.raise_for_status()
        version = response.text.strip()
        if not re.fullmatch(r'[0-9]+', version):
            raise ValueError('Invalid Reactome version')
        root = Path(data_dir) / 'reactome' / version
        path, manifest = root / 'Ensembl2Reactome.human.tsv', root / 'manifest.json'
        if path.exists() and manifest.exists():
            saved = json.loads(manifest.read_text())
            if sha256(path.read_bytes()).hexdigest() != saved['sha256']:
                raise ValueError('Reactome cache checksum mismatch')
            return path, saved
        root.mkdir(parents=True, exist_ok=True)
        url = f'https://reactome.org/download/{version}/Ensembl2Reactome.txt'
        digest, size, counts = sha256(), 0, Counter()
        temporary = path.with_suffix('.tmp')
        # Stream bytes for an exact source hash; the raw multi-species file is not retained.
        with client.stream('GET', url) as response, temporary.open('wb') as output:
            response.raise_for_status()
            pending = b''
            for chunk in response.iter_bytes():
                digest.update(chunk)
                size += len(chunk)
                pending += chunk
                lines = pending.split(b'\n')
                pending = lines.pop()
                for line in lines:
                    counts['source_rows'] += 1
                    fields = line.rstrip(b'\r').split(b'\t')
                    if len(fields) != 6:
                        raise ValueError('Expected six Reactome mapping columns')
                    if fields[1].startswith(b'R-HSA-'):
                        if fields[5] != b'Homo sapiens':
                            raise ValueError('Human pathway/species mismatch')
                        output.write(line.rstrip(b'\r') + b'\n')
                        counts['human_rows'] += 1
            if pending:
                raise ValueError('Unterminated Reactome download')
        if not counts['human_rows']:
            raise ValueError('No human Reactome rows')
        temporary.replace(path)
        saved = {
            'source': 'reactome', 'release': f'reactome-{version}', 'version': version,
            'url': url, 'version_url': VERSION_URL,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'retrieved_at_estimated': False,
            'licence': {**LICENCE, 'checked_at': datetime.now(timezone.utc).date().isoformat()},
            'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest(),
            'size_bytes': path.stat().st_size,
            'download_sha256': digest.hexdigest(), 'download_size_bytes': size,
            'filter': 'R-HSA- pathway ID and Homo sapiens; no names used for mapping',
            'mapping': 'lowest-level Ensembl2Reactome.txt, not All_Levels',
            'counts': dict(counts), 'used_by': ['pipeline.pathways', 'experiment_b'],
        }
        manifest.write_text(json.dumps(saved, indent=2) + '\n')
        return path, saved
    finally:
        if owned:
            client.close()


def load_pathways(path):
    """Count distinct ENSG members across the complete human mapping, not panel genes."""
    pathways, rejected = {}, Counter()
    with Path(path).open() as stream:
        for line in stream:
            fields = line.rstrip('\r\n').split('\t')
            if len(fields) != 6:
                raise ValueError('Expected six Reactome mapping columns')
            gene, pid, url, name, evidence_code, species = fields
            if not pid.startswith('R-HSA-'):
                rejected['non_human_pathway'] += 1
                continue
            if not re.fullmatch(r'R-HSA-[0-9]+', pid) or species != 'Homo sapiens':
                raise ValueError('Invalid human Reactome pathway')
            if not re.fullmatch(r'ENSG[0-9]{11}', gene):
                rejected['not_Ensembl_gene_ID'] += 1
                continue
            if not name or not url.startswith('https://reactome.org/'):
                raise ValueError('Missing Reactome pathway metadata')
            row = pathways.setdefault(pid, {'name': name, 'genes': set()})
            if row['name'] != name:
                raise ValueError('Ambiguous Reactome pathway name for ID')
            row['genes'].add(gene)
    return pathways, dict(rejected)


def memberships(pathways, drug_ids, disease_ids):
    """Fixed size cap and ordering, before selecting any display names."""
    if any(not re.fullmatch(r'ENSG[0-9]{11}', i) for i in set(drug_ids) | set(disease_ids)):
        raise ValueError('Pathway joins require Ensembl gene IDs')
    shared = [(pid, row) for pid, row in pathways.items()
              if len(row['genes']) <= MAX_GENES and row['genes'].intersection(drug_ids)
              and row['genes'].intersection(disease_ids)]
    return sorted(shared, key=lambda pair: (len(pair[1]['genes']), pair[0]))[:MAX_PATHWAYS]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    path, manifest = download(args.data_dir)
    pathways, rejected = load_pathways(path)
    print(json.dumps({'release': manifest['release'], 'pathways': len(pathways), 'unmapped_by_reason': rejected}))
