"""The deploy folder's data survives Vercel's upload limits: build.py packs it, and
the function's start-up mirror gives back the same files."""

import importlib.util
import shutil
import sys
from pathlib import Path

VERCEL = Path(__file__).resolve().parents[1] / "vercel"


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"vercel_{name}", VERCEL / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_packed_data_is_restored_byte_for_byte(tmp_path, monkeypatch):
    build, mirror = load("build"), load("mirror")
    monkeypatch.setattr(build, "UPLOAD_LIMIT", 1_000)
    data = tmp_path / "prepared"
    (data / "few").mkdir(parents=True)
    (data / "few" / "a.json").write_text('{"a": 1}')
    (data / "big.npy").write_bytes(bytes(range(256)) * 20)  # over the patched limit
    for i in range(build.FOLDER_LIMIT + 5):  # one folder of many small files
        target = data / "cache" / "http" / f"{i % 3}" / f"{i}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'{{"i": {i}}}')
    # macOS metadata a tarball made on a Mac carries: never shipped as data.
    (data / "few" / "._a.json").write_bytes(b"\x00\x05\x16\x07")
    (data / ".DS_Store").write_bytes(b"Bud1")
    (data / "experiments").mkdir()  # run-time output stays behind
    (data / "experiments" / "audit.json").write_text("{}")

    bundled = tmp_path / "deploy" / "data"
    shutil.copytree(
        data, bundled, ignore=build.data_ignore(data), copy_function=build.copy_data
    )
    build.pack_folders(bundled)
    shipped = sorted(
        p.relative_to(bundled).as_posix() for p in bundled.rglob("*") if p.is_file()
    )
    assert shipped == ["big.npy.vercel.gz", "cache.vercel.tgz", "few/a.json"]

    restored = mirror.writable_mirror(bundled, tmp_path / "tmp" / "data")
    expected = {
        p.relative_to(data): p.read_bytes()
        for p in data.rglob("*")
        if p.is_file()
        and "experiments" not in p.parts
        and not p.name.startswith("._")
        and p.name != ".DS_Store"
    }
    got = {
        p.relative_to(restored): p.read_bytes()
        for p in restored.rglob("*")
        if p.is_file()
    }
    assert got == expected
    assert (restored / "few" / "a.json").is_symlink(), (
        "small files stay links to the bundle"
    )
    # Run-time caches can be written beside the bundled files, and a warm start reuses them.
    (restored / "cache" / "http" / "0" / "new.json").write_text("{}")
    mirror.writable_mirror(bundled, restored)
    assert (restored / "cache" / "http" / "0" / "new.json").exists()
