"""One interface for every scoring method, and an append-only ledger of what each call cost (issue #88).

Every oracle answers ``score(smiles) -> OracleResult``. ``CostedOracle`` wraps one so that each
call is timed with a monotonic clock and appended to the ledger, whether it succeeds, fails or is
served from the cache. The ledger is what every economic claim is read from, so it holds
**measured** seconds only, never estimates.

Fidelities, cheapest first (the spec's table, with what is actually wired today):

    0  FilterOracle    the filter cascade (#87); a gate, about a millisecond to tens of ms
    1  DockingOracle   AutoDock Vina through the existing docking worker; weak on its own
    2  (not built)     Boltz-2 affinity: out at the 10-hour budget (#93)
    3  (not built)     OpenMM stability: out at the 10-hour budget (#94)

The spec says QuickVina2. The repository's worker runs AutoDock Vina 1.2.7, so that is what is
wrapped; the ledger records the engine version so the two are never confused.

The ledger is a JSON-lines file in which every row carries the hash of the row before it, so an
edited or removed row is detected by ``Ledger.verify``. It is opened for append only.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .chem import standardise

GENESIS = "0" * 64


class OracleError(RuntimeError):
    """An oracle call failed. The failed call is still in the ledger, with its measured cost."""


@dataclass(frozen=True)
class OracleResult:
    score: float | None            # higher is better for every oracle
    uncertainty: float | None = None
    detail: dict = field(default_factory=dict)


class Oracle(Protocol):
    name: str
    fidelity: int

    @property
    def version(self) -> str: ...

    def score(self, smiles: str) -> OracleResult: ...


def _row_hash(row: dict) -> str:
    body = {k: v for k, v in row.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Ledger:
    """Append-only, hash-chained JSON-lines file. Safe to append from several processes (flock)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, **fields) -> dict:
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                last = None
                for line in handle:
                    if line.strip():
                        last = line
                prev = json.loads(last) if last else None
                row = {"seq": (prev["seq"] + 1) if prev else 0,
                       "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                       **fields, "prev": prev["hash"] if prev else GENESIS}
                row["hash"] = _row_hash(row)
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                return row
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def rows(self) -> list[dict]:
        with self.path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def verify(self) -> list[str]:
        """Problems found in the chain; empty when every row is intact and in order."""
        problems, prev = [], GENESIS
        for i, row in enumerate(self.rows()):
            if row.get("seq") != i:
                problems.append(f"row {i}: sequence number is {row.get('seq')}")
            if row.get("prev") != prev:
                problems.append(f"row {i}: does not follow the row before it (a row was removed or reordered)")
            if row.get("hash") != _row_hash(row):
                problems.append(f"row {i}: contents differ from their hash (the row was edited)")
            prev = row.get("hash", "")
        return problems

    def total_seconds(self, oracle: str | None = None, include_cache_hits: bool = False) -> float:
        return round(sum(r["seconds"] for r in self.rows()
                         if (oracle is None or r["oracle"] == oracle)
                         and (include_cache_hits or not r["cache_hit"])), 6)

    def summary(self) -> dict:
        """Calls, failures, cache hits and measured seconds per oracle."""
        out: dict[str, dict] = {}
        for r in self.rows():
            s = out.setdefault(r["oracle"], {"fidelity": r["fidelity"], "calls": 0, "cache_hits": 0,
                                             "failures": 0, "seconds": 0.0})
            s["calls"] += 1
            s["cache_hits"] += int(r["cache_hit"])
            s["failures"] += int(not r["ok"])
            if not r["cache_hit"]:
                s["seconds"] = round(s["seconds"] + r["seconds"], 6)
        return out


def identity(smiles: str) -> str:
    """The molecule's InChIKey, or a stable stand-in for a SMILES that cannot be standardised."""
    std = standardise(smiles)
    return std[1] if not isinstance(std, str) else "invalid:" + hashlib.sha1((smiles or "").encode()).hexdigest()[:16]


def _hardware() -> str:
    return f"{platform.system()}-{platform.machine()}-{os.cpu_count()}cpu"


class CostedOracle:
    """Wrap an oracle: time every call, log it, and reuse earlier successful results.

    The cache is keyed by ``(InChIKey, oracle name, oracle version)`` and is rebuilt from the ledger
    on start, so a rerun in a new process does not pay again. A cache hit is logged as its own row
    with ``cache_hit`` true and the (tiny) measured lookup time; summaries leave those out of cost.
    """

    def __init__(self, oracle: Oracle, ledger: Ledger, use_cache: bool = True):
        self.oracle, self.ledger, self.use_cache = oracle, ledger, use_cache
        self._cache: dict[tuple[str, str, str], OracleResult] = {}
        if use_cache:
            for r in ledger.rows():
                if r["ok"] and not r["cache_hit"] and r["oracle"] == oracle.name:
                    self._cache[(r["inchikey"], r["oracle"], r["oracle_version"])] = OracleResult(
                        r["score"], r["uncertainty"], r.get("detail") or {})

    def call(self, candidate_id: str, smiles: str) -> OracleResult:
        key = (identity(smiles), self.oracle.name, self.oracle.version)
        base = dict(candidate_id=candidate_id, inchikey=key[0], oracle=self.oracle.name,
                    oracle_version=self.oracle.version, fidelity=self.oracle.fidelity, hardware=_hardware())
        started = time.perf_counter()
        if self.use_cache and key in self._cache:
            hit = self._cache[key]
            self.ledger.append(**base, seconds=round(time.perf_counter() - started, 6), cache_hit=True, ok=True,
                               error=None, score=hit.score, uncertainty=hit.uncertainty, detail=hit.detail)
            return hit
        try:
            result = self.oracle.score(smiles)
        except Exception as exc:
            self.ledger.append(**base, seconds=round(time.perf_counter() - started, 6), cache_hit=False, ok=False,
                               error=f"{type(exc).__name__}: {exc}"[:500], score=None, uncertainty=None, detail={})
            raise OracleError(f"{self.oracle.name} failed for {candidate_id}: {exc}") from exc
        self.ledger.append(**base, seconds=round(time.perf_counter() - started, 6), cache_hit=False, ok=True,
                           error=None, score=result.score, uncertainty=result.uncertainty, detail=result.detail)
        if self.use_cache:
            self._cache[key] = result
        return result


class FilterOracle:
    """Fidelity 0: the filter cascade as a gate. Score 1.0 passes, 0.0 fails; ``detail`` names the stage and reason."""

    name, fidelity = "filters", 0

    def __init__(self, entry: str = "flag"):
        self.entry = entry

    @property
    def version(self) -> str:
        import rdkit
        return f"cascade-1-entry-{self.entry}-rdkit-{rdkit.__version__}"

    def score(self, smiles: str) -> OracleResult:
        from . import filters
        ev = filters.evaluate(smiles, entry=self.entry)
        return OracleResult(1.0 if ev.passed else 0.0, None,
                            {"stage": ev.failed_stage, "reason": ev.reason, "entry_flags": list(ev.entry_flags)})


Runner = Callable[[list[str], dict, float], "tuple[int, str, str]"]


def subprocess_runner(cmd: list[str], env: dict, timeout: float) -> tuple[int, str, str]:
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    return done.returncode, done.stdout, done.stderr


class DockingOracle:
    """Fidelity 1: AutoDock Vina through ``htb_worker.dock``, in the docking environment.

    ``python`` is the docking environment's interpreter (Vina publishes Linux x86_64 wheels only, so
    on a Mac this means the amd64 container or a Vultr x86_64 VM). The score returned is the **negative**
    of the best pose's Vina score, so that higher is better like every other oracle. A Vina score is a
    rough, unitless estimate of fit, not a measured affinity.
    """

    name, fidelity = "vina", 1

    def __init__(self, structure_id: str, *, python: str, worker_dir: Path | str, structures_dir: Path | str,
                 cpu: int = 1, timeout: float = 180.0, runner: Runner = subprocess_runner):
        self.structure_id, self.python = structure_id, python
        self.worker_dir, self.structures_dir = Path(worker_dir), Path(structures_dir)
        self.cpu, self.timeout, self.runner = cpu, timeout, runner
        settings = json.loads((self.structures_dir / "settings.json").read_text())
        self.exhaustiveness, self.seed, self.n_poses = settings["exhaustiveness"], settings["seed"], settings["n_poses"]
        self._engine: str | None = None

    def _env(self) -> dict:
        return {**os.environ, "PYTHONPATH": str(self.worker_dir)}

    @property
    def version(self) -> str:
        if self._engine is None:
            code, out, err = self.runner([self.python, "-m", "htb_worker.dock", "--toolchain"], self._env(), 60.0)
            if code != 0:
                raise OracleError(f"could not read the docking toolchain: {err.strip()[-300:]}")
            self._engine = json.loads(out)["vina"]
        return f"vina-{self._engine}-ex{self.exhaustiveness}-seed{self.seed}-{self.structure_id}"

    def score(self, smiles: str) -> OracleResult:
        _ = self.version
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            cmd = [self.python, "-m", "htb_worker.dock", "--structure", str(self.structures_dir / self.structure_id),
                   "--smiles", smiles, "--out", str(out), "--exhaustiveness", str(self.exhaustiveness),
                   "--seed", str(self.seed), "--n-poses", str(self.n_poses), "--cpu", str(self.cpu)]
            code, _, err = self.runner(cmd, self._env(), self.timeout)
            if code != 0:
                raise OracleError(f"docking exited {code}: {err.strip()[-300:]}")
            result = json.loads((out / "scores.json").read_text())
        best = min(s["score"] for s in result["scores"])
        return OracleResult(-best, None, {"best_vina_score": best, "structure": self.structure_id,
                                          "engine_version": result["toolchain"]["vina"],
                                          "worker_seconds": result["timing"]["total_s"]})
