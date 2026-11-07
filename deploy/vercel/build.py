# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Assemble the folder Vercel deploys: the web app, the API function and its data.

    uv run deploy/vercel/build.py --data data --sha "$(git rev-parse HEAD)" --out .vercel-deploy
    cd .vercel-deploy && vercel pull --yes --environment=production \\
      && vercel build --prod && vercel deploy --prebuilt --prod

Vercel's Python builder installs only a uv workspace's root project, so instead of
pointing it at this repository the folder is explicit:

- requirements.txt: the API's locked third-party packages (`uv export`).
- index.py (deploy/vercel/index.py) and the code it imports, at the paths they have
  here (app/api, app/worker, core), so every repository-relative path still works.
- data/: the prepared data (`python -m oxhack_api.prepare`) minus run-time output.
  It is about 0.5 GB, so the project uses Vercel's large functions
  (VERCEL_SUPPORT_LARGE_FUNCTIONS=1). Files over Vercel's 100 MB upload limit (the
  network's 158 MB distance matrix) ship gzipped and are restored on start-up.
- public/: the built web app, served by Vercel's CDN, with release.json naming
  the commit.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODE = {
    "app/api/oxhack_api": "app/api/oxhack_api",
    "app/worker/oxhack_worker": "app/worker/oxhack_worker",
    "app/worker/structures": "app/worker/structures",
    "core/pipeline": "core/pipeline",
    "core/jury": "core/jury",
    "core/ranking": "core/ranking",
    "deploy/db/migrate.py": "deploy/db/migrate.py",
    "deploy/db/migrations": "deploy/db/migrations",
}
UPLOAD_LIMIT = 95 * 2**20
"""Vercel refuses deployment files over 100 MB: larger ones ship gzipped, with
PACKED_SUFFIX, and index.py restores them on start-up."""
PACKED_SUFFIX = ".vercel.gz"
FOLDER_LIMIT = 100
"""Vercel's Hobby plan accepts 5,000 uploaded files a day: a data folder holding more
files than this (the ChEMBL and HTTP caches) ships as one archive, FOLDER_SUFFIX,
which index.py unpacks on start-up."""
FOLDER_SUFFIX = ".vercel.tgz"
DATA_LEFT_OUT = {"experiments", "docking", "string"}
"""Run-time output (audits, docking results) and STRING's raw download, which only
`prepare` reads."""
VERCEL_CONFIG = {
    "$schema": "https://openapi.vercel.sh/vercel.json",
    "framework": "fastapi",
    "git": {"deploymentEnabled": False},
    # Web app routes are the single page app's; files in public/ are served first.
    "rewrites": [{"source": "/((?!api/).*)", "destination": "/index.html"}],
    # CI checks the deployed commit here right after each deploy.
    "headers": [
        {
            "source": "/release.json",
            "headers": [{"key": "Cache-Control", "value": "no-store"}],
        }
    ],
}


def code_ignore(folder: str, names: list[str]) -> set[str]:
    return {
        n
        for n in names
        if n in {"__pycache__", "tests", ".pytest_cache"} or n.endswith(".pyc")
    }


def data_ignore(root: Path):
    def ignore(folder: str, names: list[str]) -> set[str]:
        top = Path(folder) == root
        # macOS tar and Finder metadata (._name, .DS_Store) would pass for data:
        # DuckDB's *.parquet glob reads ._part.parquet and fails.
        return {
            n
            for n in names
            if (top and n in DATA_LEFT_OUT)
            or n.endswith(".tmp")
            or n.startswith("._")
            or n == ".DS_Store"
        }

    return ignore


def copy_data(source: str, target: str) -> None:
    """copytree's copy function: files over the upload limit are gzipped."""
    if Path(source).stat().st_size <= UPLOAD_LIMIT:
        shutil.copy2(source, target)
        return
    with (
        open(source, "rb") as raw,
        gzip.open(target + PACKED_SUFFIX, "wb", compresslevel=6) as packed,
    ):
        shutil.copyfileobj(raw, packed, 1 << 20)


def pack_folders(data: Path) -> None:
    """Replace each folder under `data` holding more than FOLDER_LIMIT files with
    one archive of it, keeping the folder's name inside."""
    for folder in sorted(p for p in data.rglob("*") if p.is_dir()):
        if not folder.exists():  # inside a folder packed already
            continue
        if sum(1 for p in folder.rglob("*") if p.is_file()) <= FOLDER_LIMIT:
            continue
        with tarfile.open(
            folder.with_name(folder.name + FOLDER_SUFFIX), "w:gz"
        ) as archive:
            archive.add(folder, arcname=folder.name)
        shutil.rmtree(folder)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--data", type=Path, required=True, help="the prepared data folder"
    )
    parser.add_argument("--sha", required=True, help="the commit being deployed")
    parser.add_argument("--out", type=Path, default=REPO / ".vercel-deploy")
    args = parser.parse_args()
    data = args.data.resolve()
    if not (data / "drug_targets.json").is_file():
        raise SystemExit(f"{data} is not a prepared data folder (no drug_targets.json)")
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for source, target in CODE.items():
        if (REPO / source).is_dir():
            shutil.copytree(REPO / source, out / target, ignore=code_ignore)
        else:
            (out / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / source, out / target)
    shutil.copy2(REPO / "deploy/vercel/index.py", out / "index.py")
    shutil.copy2(REPO / "deploy/vercel/mirror.py", out / "mirror.py")
    shutil.copytree(
        data, out / "data", ignore=data_ignore(data), copy_function=copy_data
    )
    pack_folders(out / "data")
    subprocess.run(
        [
            "uv", "export", "--frozen", "--no-dev", "--package", "oxhack-api",
            "--no-emit-workspace", "--no-hashes", "--no-header", "--quiet",
            "--output-file", str(out / "requirements.txt"),
        ],
        cwd=REPO,
        check=True,
    )  # fmt: skip
    (out / ".python-version").write_text("3.12\n")
    (out / "vercel.json").write_text(json.dumps(VERCEL_CONFIG, indent=2) + "\n")

    web = REPO / "app/web"
    subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=web, check=True)
    subprocess.run(["npm", "run", "build"], cwd=web, check=True)
    shutil.copytree(web / "dist", out / "public")
    (out / "public/release.json").write_text(json.dumps({"sha": args.sha}) + "\n")
    print(f"Deploy folder ready: {out}")


if __name__ == "__main__":
    main()
