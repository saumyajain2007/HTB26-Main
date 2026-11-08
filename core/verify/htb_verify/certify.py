"""Lean 4 certificates for a molecule's property rules.

For each molecule this writes a small Lean file that imports `HtbVerify`, states the
molecule's scaled descriptors, and asks Lean to prove one theorem per rule
(`rule_mw`, `rule_logp`, ...) plus `all_rules`. Lean accepting the file is the
certificate; a failing theorem names the rule that was broken.

What a certificate means: the scaled descriptor values RDKit computed satisfy the
thresholds written in `lean/HtbVerify/Rules.lean`. It does not cover how RDKit
computed the descriptors, nor safety, selectivity or activity.

If Lean is not installed or cannot build, `certify` returns `ran=False` and never
reports a molecule as certified.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .smoke import SmokeResult, check_molecule

LEAN_DIR = Path(__file__).resolve().parents[1] / "lean"

# Rule-set name in Python -> the threshold constant in Rules.lean.
LEAN_THRESHOLDS = {"oral_druglike": "oralDruglike", "antibiotic_relaxed": "antibioticRelaxed"}

# (theorem name, Lean field of Desc and Thresholds, label)
_RULES = [
    ("rule_mw", "mwX10", "mw"),
    ("rule_logp", "logpX100", "logp"),
    ("rule_hbd", "hbd", "hbd"),
    ("rule_hba", "hba", "hba"),
    ("rule_rot_bonds", "rotBonds", "rot_bonds"),
    ("rule_psa", "psaX10", "psa"),
]

_built: bool | None = None
_cache: dict[tuple[str, str], "Certificate"] = {}


def clear_certificate_cache() -> None:
    """Clear the in-memory certificate cache (keyed by (inchikey, rule_set))."""
    _cache.clear()


def load_certificate_cache(path: Path | str) -> int:
    """Load persisted (inchikey, rule_set) -> Certificate entries from JSON into `_cache`."""
    p = Path(path)
    if not p.exists():
        return 0
    raw = json.loads(p.read_text(encoding="utf-8"))
    loaded = 0
    for item in raw.get("certificates", []):
        if not item.get("ran"):
            continue
        key = (item["key"], item["rule_set"])
        _cache[key] = Certificate(
            ran=bool(item["ran"]),
            certified=bool(item["certified"]),
            rule_set=item["rule_set"],
            failed_rules=tuple(item.get("failed_rules", ())),
            lean_version=item.get("lean_version"),
            seconds=item.get("seconds"),
            detail=item.get("detail"),
            source=item.get("source"),
        )
        loaded += 1
    return loaded


def save_certificate_cache(path: Path | str) -> int:
    """Write all `ran=True` entries in `_cache` to `path` as deterministic JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for (key, rule_set), cert in sorted(_cache.items()):
        if not cert.ran:
            continue
        row = asdict(cert)
        row["key"] = key
        row["failed_rules"] = list(cert.failed_rules)
        items.append(row)
    p.write_text(json.dumps({"certificates": items}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(items)


@dataclass(frozen=True)
class Certificate:
    ran: bool                       # False when Lean was not available or the input was unusable
    certified: bool                 # True only when Lean accepted every theorem
    rule_set: str
    failed_rules: tuple[str, ...] = ()
    lean_version: str | None = None
    seconds: float | None = None
    detail: str | None = None       # why it did not run, or Lean's first error line
    source: str | None = None       # the Lean file that was checked


def lean_available() -> bool:
    return shutil.which("lake") is not None and (LEAN_DIR / "lakefile.toml").exists()


def lean_version() -> str | None:
    if not lean_available():
        return None
    out = subprocess.run(["lake", "env", "lean", "--version"], cwd=LEAN_DIR,
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip() or None


def ensure_built() -> bool:
    """Build the HtbVerify library once per process. Returns True on success."""
    global _built
    if _built is None:
        if not lean_available():
            _built = False
        else:
            r = subprocess.run(["lake", "build"], cwd=LEAN_DIR, capture_output=True, text=True, timeout=600)
            _built = r.returncode == 0
    return _built


def _int(v: int) -> str:
    return f"({v} : Int)" if v < 0 else str(v)


def generate(smoke: SmokeResult) -> tuple[str, dict[int, str]]:
    """Return the Lean source and a map from 1-based line number to theorem name."""
    d = smoke.descriptors
    assert d is not None
    const = LEAN_THRESHOLDS[smoke.rule_set]
    values = {
        "mwX10": str(d.mw_x10), "logpX100": _int(d.logp_x100), "hbd": str(d.hbd),
        "hba": str(d.hba), "rotBonds": str(d.rot_bonds), "psaX10": str(d.psa_x10),
    }
    lines = [
        "import HtbVerify",
        "open HtbVerify",
        "",
        "def mol : Desc :=",
        "  { " + ", ".join(f"{k} := {v}" for k, v in values.items()) + " }",
        "",
    ]
    line_to_theorem: dict[int, str] = {}
    for name, field, _ in _RULES:
        lines.append(f"theorem {name} : mol.{field} ≤ {const}.{field} := by decide")
        line_to_theorem[len(lines)] = name
    lines.append(f"theorem all_rules : mol.Passes {const} := by decide")
    line_to_theorem[len(lines)] = "all_rules"
    return "\n".join(lines) + "\n", line_to_theorem


def certify(
    molecule: str | SmokeResult,
    rule_set: str = "oral_druglike",
    *,
    timeout: float = 60.0,
    cache_path: Path | str | None = None,
) -> Certificate:
    """Check a molecule's property rules in Lean. Accepts a SMILES string or a SmokeResult."""
    if cache_path is not None:
        load_certificate_cache(cache_path)
    smoke = check_molecule(molecule, rule_set) if isinstance(molecule, str) else molecule
    rule_set = smoke.rule_set
    if rule_set not in LEAN_THRESHOLDS:
        return Certificate(False, False, rule_set, detail=f"no Lean thresholds for rule set {rule_set!r}")
    if not smoke.valid or smoke.descriptors is None:
        return Certificate(False, False, rule_set, detail="invalid molecule")

    key = (smoke.inchikey or smoke.smiles, rule_set)
    if key in _cache:
        return _cache[key]
    if not ensure_built():
        return Certificate(False, False, rule_set, detail="Lean is not installed or the HtbVerify library did not build")

    source, line_to_theorem = generate(smoke)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Mol.lean"
        path.write_text(source, encoding="utf-8")
        start = time.monotonic()
        try:
            r = subprocess.run(["lake", "env", "lean", str(path)], cwd=LEAN_DIR,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return Certificate(True, False, rule_set, detail=f"Lean timed out after {timeout:.0f} s", source=source)
        seconds = round(time.monotonic() - start, 2)

    output = (r.stdout or "") + (r.stderr or "")
    errors = [(int(m.group(1)), line) for line in output.splitlines()
              if (m := re.search(r"Mol\.lean:(\d+):\d+: error", line))]
    failed = tuple(dict.fromkeys(line_to_theorem[n] for n, _ in errors if n in line_to_theorem))
    # all_rules fails whenever any single rule fails; report only the specific rules.
    specific = tuple(f for f in failed if f != "all_rules")
    first_error = errors[0][1] if errors else (output.strip().splitlines()[0] if output.strip() else None)
    cert = Certificate(
        ran=True,
        certified=r.returncode == 0,
        rule_set=rule_set,
        failed_rules=specific or failed,
        lean_version=lean_version(),
        seconds=seconds,
        detail=None if r.returncode == 0 else first_error,
        source=source,
    )
    _cache[key] = cert
    if cache_path is not None:
        save_certificate_cache(cache_path)
    return cert


def _batch_block(smoke: SmokeResult, i: int) -> tuple[list[str], dict[int, str]]:
    """Lean lines for molecule `i` in a batch file, with theorem names suffixed `_i`."""
    d = smoke.descriptors
    assert d is not None
    const = LEAN_THRESHOLDS[smoke.rule_set]
    values = {
        "mwX10": str(d.mw_x10), "logpX100": _int(d.logp_x100), "hbd": str(d.hbd),
        "hba": str(d.hba), "rotBonds": str(d.rot_bonds), "psaX10": str(d.psa_x10),
    }
    lines = [f"def mol_{i} : Desc :=", "  { " + ", ".join(f"{k} := {v}" for k, v in values.items()) + " }"]
    offsets: dict[int, str] = {}
    for name, field, _ in _RULES:
        lines.append(f"theorem {name}_{i} : mol_{i}.{field} ≤ {const}.{field} := by decide")
        offsets[len(lines)] = name
    lines.append(f"theorem all_rules_{i} : mol_{i}.Passes {const} := by decide")
    offsets[len(lines)] = "all_rules"
    return lines, offsets


def certify_batch(
    smokes: Sequence[SmokeResult],
    *,
    timeout: float = 300.0,
    cache_path: Path | str | None = None,
) -> list[Certificate]:
    """Certify many molecules in one Lean run. Returns one Certificate per input, in order.

    Each theorem is checked independently, so one molecule failing a rule does not affect the
    others. If Lean reports any error that cannot be tied to a molecule's theorem (a broken
    build, a syntax error), nothing in the batch is certified: every pending molecule gets
    ``ran=False`` and the first error as ``detail``. Results are cached by InChIKey and rule set
    for the life of the process (and optionally persisted to ``cache_path``), and duplicate
    InChIKeys within the same batch are deduplicated before calling Lean. `seconds` is the batch
    time divided evenly over the unique molecules that were checked.
    """
    if cache_path is not None:
        load_certificate_cache(cache_path)

    out: list[Certificate | None] = [None] * len(smokes)
    pending: list[int] = []  # representative index for each unique (inchikey, rule_set)
    key_to_indices: dict[tuple[str, str], list[int]] = {}
    for i, smoke in enumerate(smokes):
        if smoke.rule_set not in LEAN_THRESHOLDS:
            out[i] = Certificate(False, False, smoke.rule_set,
                                 detail=f"no Lean thresholds for rule set {smoke.rule_set!r}")
        elif not smoke.valid or smoke.descriptors is None:
            out[i] = Certificate(False, False, smoke.rule_set, detail="invalid molecule")
        else:
            key = (smoke.inchikey or smoke.smiles, smoke.rule_set)
            if (cached := _cache.get(key)) is not None:
                out[i] = cached
            else:
                if key not in key_to_indices:
                    pending.append(i)
                key_to_indices.setdefault(key, []).append(i)
    if not pending:
        return out  # type: ignore[return-value]
    if not ensure_built():
        for i in pending:
            key = (smokes[i].inchikey or smokes[i].smiles, smokes[i].rule_set)
            unavail = Certificate(False, False, smokes[i].rule_set,
                                  detail="Lean is not installed or the HtbVerify library did not build")
            for idx in key_to_indices[key]:
                out[idx] = unavail
        return out  # type: ignore[return-value]

    lines = ["import HtbVerify", "open HtbVerify", ""]
    where: dict[int, tuple[int, str]] = {}   # file line -> (representative index into smokes, theorem)
    blocks: dict[int, list[str]] = {}
    for i in pending:
        block, offsets = _batch_block(smokes[i], i)
        start = len(lines)
        lines += block + [""]
        blocks[i] = block
        where.update({start + off: (i, name) for off, name in offsets.items()})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Mol.lean"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        start_time = time.monotonic()
        try:
            r = subprocess.run(["lake", "env", "lean", str(path)], cwd=LEAN_DIR,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            for i in pending:
                key = (smokes[i].inchikey or smokes[i].smiles, smokes[i].rule_set)
                timed_out = Certificate(True, False, smokes[i].rule_set,
                                        detail=f"Lean timed out after {timeout:.0f} s")
                for idx in key_to_indices[key]:
                    out[idx] = timed_out
            return out  # type: ignore[return-value]
        seconds = round((time.monotonic() - start_time) / len(pending), 3)

    output = (r.stdout or "") + (r.stderr or "")
    errors = [(int(m.group(1)), line) for line in output.splitlines()
              if (m := re.search(r"Mol\.lean:(\d+):\d+: error", line))]
    unattributed = [line for n, line in errors if n not in where]
    if unattributed or (r.returncode != 0 and not errors):
        detail = (unattributed or output.strip().splitlines() or ["Lean failed with no output"])[0]
        for i in pending:
            key = (smokes[i].inchikey or smokes[i].smiles, smokes[i].rule_set)
            err_cert = Certificate(False, False, smokes[i].rule_set,
                                   detail=f"batch could not be checked: {detail}")
            for idx in key_to_indices[key]:
                out[idx] = err_cert
        return out  # type: ignore[return-value]

    failed: dict[int, dict[str, str]] = {}
    for n, line in errors:
        i, name = where[n]
        failed.setdefault(i, {})[name] = line
    version = lean_version()
    for i in pending:
        smoke, broken = smokes[i], failed.get(i, {})
        specific = tuple(f for f in broken if f != "all_rules")
        cert = Certificate(
            ran=True, certified=not broken, rule_set=smoke.rule_set,
            failed_rules=specific or tuple(broken), lean_version=version, seconds=seconds,
            detail=next(iter(broken.values())) if broken else None,
            source="\n".join(["import HtbVerify", "open HtbVerify", ""] + blocks[i]) + "\n",
        )
        key = (smoke.inchikey or smoke.smiles, smoke.rule_set)
        _cache[key] = cert
        for idx in key_to_indices[key]:
            out[idx] = cert
    if cache_path is not None:
        save_certificate_cache(cache_path)
    return out  # type: ignore[return-value]
