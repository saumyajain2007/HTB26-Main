"""Run a prepared manifest in parallel on one GPU; never contains cloud credentials."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = Path(sys.argv[1]).resolve()
workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
manifest = json.loads((root / "manifest.json").read_text())
digest = hashlib.sha256((root / "manifest.json").read_bytes())
for source in sorted((root / "inputs").iterdir()):
    if source.is_file():
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
stamp = root / "input_digest.txt"
if stamp.exists() and stamp.read_text() != digest.hexdigest():
    raise ValueError(
        "Inputs changed: use a fresh work directory to avoid cached predictions"
    )
stamp.write_text(digest.hexdigest())
cache = root / "cache"
cache.mkdir(exist_ok=True)
# One downloader prevents concurrent writers corrupting shared model assets.
from boltz.main import download_boltz2

download_boltz2(cache)
(root / "assets-ready").touch()
jobs = manifest["jobs"]
chunks = [jobs[i::workers] for i in range(workers)]


def run_chunk(item):
    index, chunk = item
    inputs = root / f"chunk_{index}"
    inputs.mkdir(exist_ok=True)
    for job in chunk:
        source = root / "inputs" / f"{job['job_id']}.yaml"
        (inputs / source.name).write_bytes(source.read_bytes())
    command = [
        "boltz",
        "predict",
        str(inputs),
        "--out_dir",
        str(root / "outputs"),
        "--cache",
        str(cache),
        "--model",
        "boltz2",
        "--output_format",
        "pdb",
        "--diffusion_samples",
        "1",
        "--seed",
        "42",
        "--use_msa_server",
        "--num_workers",
        "0",
        "--preprocessing-threads",
        "1",
        "--max_msa_seqs",
        "512",
        "--no_kernels",
    ]
    with (root / f"worker_{index}.log").open("w") as output:
        result = subprocess.run(
            command,
            check=False,
            stdout=output,
            stderr=subprocess.STDOUT,
            env={**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"},
        )
    return {"worker": index, "exit_code": result.returncode}


started = time.time()
with ThreadPoolExecutor(max_workers=workers) as pool:
    statuses = list(pool.map(run_chunk, enumerate(chunks)))
models = list((root / "outputs").rglob("*_model_0.pdb"))
(root / "done.json").write_text(
    json.dumps(
        {
            "elapsed_seconds": time.time() - started,
            "workers": statuses,
            "models": len(models),
        },
        indent=2,
    )
)
print("Completed", len(models), "of", len(jobs), "predictions", flush=True)

# Boltz can return success after skipping malformed inputs; fail an incomplete batch.
raise SystemExit(0 if len(models) == len(jobs) else 1)
