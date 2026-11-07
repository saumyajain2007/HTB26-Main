"""Make the function's read-only data folder usable: index.py's start-up step.

`writable_mirror` copies the folder tree into /tmp with every file a symlink to the
bundled one, so readers see all the data and run-time caches can be written beside
it. Files and folders that build.py packed for Vercel's upload limits are restored
in the mirror instead of linked.
"""

from __future__ import annotations

import gzip
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

PACKED_SUFFIX = ".vercel.gz"
"""build.py gzips files over Vercel's upload limit; they are restored in the mirror."""
FOLDER_SUFFIX = ".vercel.tgz"
"""build.py archives folders of many files (Hobby's daily upload count); unpacked there."""


def writable_mirror(bundled: Path, mirror: Path) -> Path:
    """`mirror` with `bundled`'s folders, each file a symlink to the bundled one, or a
    restored copy of a packed one."""
    for folder, _, files in os.walk(bundled):
        relative = Path(folder).relative_to(bundled)
        (mirror / relative).mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.endswith(FOLDER_SUFFIX):
                unpack(Path(folder) / name, mirror / relative)
                continue
            if name.endswith(PACKED_SUFFIX):
                restore(
                    Path(folder) / name,
                    mirror / relative / name.removesuffix(PACKED_SUFFIX),
                )
                continue
            link = mirror / relative / name
            if not link.exists():
                link.symlink_to(Path(folder) / name)
    return mirror


def unpack(archive: Path, parent: Path) -> None:
    """Unpack a folder archive into `parent`, once; the folder appears whole or not at all."""
    target = parent / archive.name.removesuffix(FOLDER_SUFFIX)
    if target.exists():
        return
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=parent))
    with tarfile.open(archive) as source:
        source.extractall(staging, filter="data")
    (staging / target.name).rename(target)
    shutil.rmtree(staging, ignore_errors=True)


def restore(packed: Path, target: Path) -> None:
    if target.exists():
        return
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with gzip.open(packed, "rb") as source, temporary.open("wb") as output:
        shutil.copyfileobj(source, output, 1 << 20)
    temporary.replace(target)
