"""Install the pinned Linux Lean release through GitHub's checksum-verified asset API."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HEADERS = {"User-Agent": "HTB26-CI", "X-GitHub-Api-Version": "2022-11-28"}


def download_verified(url: str, target: Path, digest: str) -> None:
    """Do not publish an archive until it matches GitHub's release-asset digest."""
    partial = target.with_suffix(target.suffix + ".partial")
    request = urllib.request.Request(
        url, headers={**HEADERS, "Accept": "application/octet-stream"}
    )
    for attempt in range(3):
        try:
            checksum = hashlib.sha256()
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                partial.open("wb") as out,
            ):
                while block := response.read(1024 * 1024):
                    checksum.update(block)
                    out.write(block)
            if checksum.hexdigest() != digest:
                raise ValueError("Lean release asset checksum mismatch")
            partial.replace(target)
            return
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
        finally:
            partial.unlink(missing_ok=True)


def install() -> Path:
    if shutil.which("zstd") is None:
        raise RuntimeError("Install zstd before extracting the pinned Lean release")
    toolchain = (REPO / "core/verify/lean/lean-toolchain").read_text().strip()
    match = re.fullmatch(
        r"leanprover/lean4:(v[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?)", toolchain
    )
    if match is None:
        raise ValueError(f"Unsupported pinned Lean toolchain: {toolchain}")
    version = match[1]
    name = f"lean-{version[1:]}-linux"
    pin = json.loads((REPO / "deploy/ci/lean-release.json").read_text())
    if pin["toolchain"] != toolchain:
        raise ValueError(
            "Update lean-release.json from the official release when changing Lean"
        )
    asset = pin["asset"]
    if asset["name"] != name + ".tar.zst":
        raise ValueError("Pinned Lean asset does not match the toolchain")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("The official Lean release has no SHA-256 asset digest")
    install_root = Path.home() / ".cache" / "htb-lean"
    install_root.mkdir(parents=True, exist_ok=True)
    destination = install_root / name
    stamp = destination / ".asset-sha256"
    if not stamp.is_file() or stamp.read_text().strip() != digest:
        with tempfile.TemporaryDirectory(
            dir=install_root, prefix="download-"
        ) as temporary:
            work = Path(temporary)
            archive = work / asset["name"]
            print(
                f"Downloading pinned Lean {version} through the official asset API",
                flush=True,
            )
            download_verified(asset["url"], archive, digest.removeprefix("sha256:"))
            subprocess.run(
                ["tar", "--zstd", "-xf", str(archive), "-C", str(work)], check=True
            )
            unpacked = work / name
            if (
                not (unpacked / "bin/lean").is_file()
                or not (unpacked / "bin/lake").is_file()
            ):
                raise ValueError("Lean archive does not contain the expected toolchain")
            if destination.exists():
                shutil.rmtree(destination)
            unpacked.rename(destination)
            stamp.write_text(digest + "\n")
    binary_dir = destination / "bin"
    subprocess.run([str(binary_dir / "lean"), "--version"], check=True)
    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with Path(github_path).open("a") as out:
            out.write(str(binary_dir) + "\n")
    print(f"Lean binaries: {binary_dir}", flush=True)
    return binary_dir


if __name__ == "__main__":
    install()
