"""Freeze the WS5 retrospective protocol before any result exists.

Follows the pattern in ``results/``: a human protocol in ``protocol.md``, and a
``preregistered.json`` holding ``frozen_at``, the ``declaration`` of settings, the
protocol's own sha256 and an ``inputs_sha256`` map, exactly as
``results/experiment_b_replication/preregistered.json`` does.

The point is that a result cannot be tuned afterwards, so the tool is built to refuse:

  - ``freeze`` will not run if a results file already exists. A protocol written after a
    result is not pre-registered, and the timestamp alone cannot show which came first.
  - ``freeze`` will not overwrite an existing ``preregistered.json``. Re-freezing is how a
    protocol quietly becomes a description of what happened. A real change goes through
    ``amend``, which appends to ``amendments`` with a reason and keeps the original
    declaration intact, the way Amendment 1 is handled in the Experiment B protocol.
  - ``verify`` fails if ``protocol.md`` or any declared input has changed since the freeze.
  - ``require_frozen`` raises on anything ``verify`` reports, and is what a scoring run
    calls before it is allowed to compute a number.

The checksums are of files on the machine that runs the freeze, so they cannot be written
in advance. ``preregistered.json`` is deliberately **not** committed by whoever wrote this
module: it is produced by running ``--freeze``, and that run is the moment the protocol
becomes frozen.

    python -m eval.protocol --freeze
    python -m eval.protocol --verify
    python -m eval.protocol --amend "why" --change "what"
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "results" / "ws5_retrospective"
PROTOCOL = DIR / "protocol.md"
PREREGISTERED = DIR / "preregistered.json"
# A results file here means the experiment has already been run.
RESULT_FILES = ("results.json", "results.md")

# Everything the retrospective test consumes. A release manifest already carries the
# sha256 of every table it holds, so pinning the manifest pins the tables with it.
INPUTS = (
    "eval/ground_truth.json",
    "data/card/releases/4.0.2/manifest.json",
    "core/resistance/htb_resistance/data/presets.json",
    "core/ranking/antibiotic/protocol_v1.json",
    "data/antibiotics/releases/chembl-37_card-4.0.2/manifest.json",
)

DECLARATION = {
    "experiment": "ws5_retrospective",
    "question": "For a resistance profile, does the ranking put drugs that are known to work "
                "above drugs the profile defeats?",
    "seed": 20261108,
    "metrics": {
        "primary": "hit_at_1",
        "reported": ["hit_at_1", "hit_at_3", "mean_reciprocal_rank", "inverted_rate"],
        "inverted_rate": "the share of rows where a drug on the ineffective list outranks every "
                         "drug on the effective list. A wrong answer, not a near miss, and it is "
                         "reported even when the hit rates look acceptable.",
    },
    "baselines": {
        "random": "shuffle the pool under the declared seed",
        "alphabetical": "the pool in name order, which is the ranking's own tie-break and so the "
                        "floor any ordering must beat",
        "evasion_only": "the ordered rule with the activity and safety keys removed",
    },
    "uncertainty": {
        "method": "bootstrap over ground-truth rows",
        "resamples": 2000,
        "interval": 0.95,
        "note": "With 6 rows the interval will be very wide. That is the honest result for this "
                "sample size and is not to be narrowed by adding rows after seeing it.",
    },
    "rules": [
        "Rows marked partly_verified in the ground truth are excluded from the primary metric "
        "and reported separately. Which rows those are is fixed by the frozen ground truth.",
        "No row may be added, removed or re-labelled after the freeze. A row whose citation "
        "turns out to be wrong is recorded as an erratum and the result is reported with and "
        "without it, never silently dropped.",
        "Each row is ranked from its own profile_genes, never from a species preset. A gene "
        "that does not resolve in the pinned CARD release is an error, not a smaller profile.",
        "A row is hit-eligible only when at least one of its effective drugs is in the "
        "candidate pool. The headline n and all four metrics are over hit-eligible rows. A row "
        "with only ineffective drugs in the pool is reported separately as a demotion row (the "
        "rank of the best-placed defeated drug, beside the baselines); hit@k and inversion are "
        "undefined for it, and inversion is never credited when no effective drug is rankable. "
        "A row with no drug in the pool is named as unscorable, not skipped quietly.",
        "Every baseline is run on the same pool and the same rows as the method.",
        "The metric set above is complete. A metric not listed here may be reported as an "
        "observation but never as the headline.",
        "Every attempt is reported, including runs that failed or were abandoned.",
        "A negative result stands. If the method does not beat the alphabetical baseline, "
        "that is the finding.",
    ],
    "preconditions": [
        "At least one ground-truth row is hit-eligible, or nothing can be scored.",
        "The profiles are built from the full pinned CARD release (data/card/releases/4.0.2), "
        "not from a synthetic fixture slice.",
    ],
}


class ProtocolError(RuntimeError):
    """The protocol is not frozen, or no longer matches what was frozen."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def declaration_sha256(declaration: dict) -> str:
    """Hash of the declaration itself, so a change to it is visible even in the same file."""
    return hashlib.sha256(
        json.dumps(declaration, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git_commit(root: Path) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def existing_results(root: Path = ROOT) -> list:
    directory = root / DIR.relative_to(ROOT)
    return [name for name in RESULT_FILES if (directory / name).exists()]


def missing_inputs(root: Path = ROOT, inputs=INPUTS) -> list:
    return [p for p in inputs if not (root / p).exists()]


def freeze(root: Path = ROOT, *, inputs=INPUTS, declaration=None, now=None) -> dict:
    """Write preregistered.json. Refuses if a result exists or the protocol is already frozen."""
    declaration = DECLARATION if declaration is None else declaration
    directory = root / DIR.relative_to(ROOT)
    protocol = directory / PROTOCOL.name
    preregistered = directory / PREREGISTERED.name

    if not protocol.exists():
        raise ProtocolError(f"{protocol} does not exist: write the protocol before freezing it")
    produced = existing_results(root)
    if produced:
        raise ProtocolError(
            f"{', '.join(produced)} already exists, so this protocol would not be "
            "pre-registered. Freeze before running, or record an amendment instead.")
    if preregistered.exists():
        raise ProtocolError(
            f"{preregistered} already exists. Re-freezing would let the protocol follow the "
            "result; use amend() to record a change with its reason.")
    absent = missing_inputs(root, inputs)
    if absent:
        raise ProtocolError("cannot freeze a protocol whose inputs do not exist: "
                            + ", ".join(absent))

    record = {
        "frozen_at": (now or datetime.now(timezone.utc)).isoformat(),
        "git_commit": _git_commit(root),
        "declaration": declaration,
        "declaration_sha256": declaration_sha256(declaration),
        "protocol_sha256": sha256_file(protocol),
        "inputs_sha256": {p: sha256_file(root / p) for p in inputs},
        "amendments": [],
    }
    preregistered.parent.mkdir(parents=True, exist_ok=True)
    preregistered.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8", newline="\n")
    return record


def load(root: Path = ROOT) -> dict:
    preregistered = root / PREREGISTERED.relative_to(ROOT)
    if not preregistered.exists():
        raise ProtocolError(f"{preregistered} does not exist: the protocol has not been frozen")
    try:
        return json.loads(preregistered.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ProtocolError(f"{preregistered} is not valid JSON: {exc}") from exc


def verify(root: Path = ROOT) -> list:
    """Return a list of problems. Empty means nothing has moved since the freeze."""
    try:
        record = load(root)
    except ProtocolError as exc:
        return [str(exc)]

    problems = []
    protocol = root / PROTOCOL.relative_to(ROOT)
    if not protocol.exists():
        problems.append(f"{protocol} is missing")
    elif sha256_file(protocol) != record.get("protocol_sha256"):
        problems.append("protocol.md has changed since the freeze")
    if declaration_sha256(record.get("declaration", {})) != record.get("declaration_sha256"):
        problems.append("the declaration has been edited in place since the freeze")
    for path, expected in sorted((record.get("inputs_sha256") or {}).items()):
        full = root / path
        if not full.exists():
            problems.append(f"{path}: pinned input is missing")
        elif sha256_file(full) != expected:
            problems.append(f"{path}: changed since the freeze")
    return problems


def require_frozen(root: Path = ROOT) -> dict:
    """The gate a scoring run calls first. Raises rather than returning a number."""
    problems = verify(root)
    if problems:
        raise ProtocolError("the protocol is not in the state it was frozen in: "
                            + "; ".join(problems))
    return load(root)


def amend(reason: str, change: str, root: Path = ROOT, *, now=None) -> dict:
    """Record a change without rewriting the original declaration."""
    if not reason.strip() or not change.strip():
        raise ProtocolError("an amendment needs both a reason and what it changes")
    record = load(root)
    protocol = root / PROTOCOL.relative_to(ROOT)
    record["amendments"].append({
        "at": (now or datetime.now(timezone.utc)).isoformat(),
        "reason": reason,
        "change": change,
        "git_commit": _git_commit(root),
        "protocol_sha256_now": sha256_file(protocol) if protocol.exists() else None,
        "results_existed": existing_results(root),
    })
    (root / PREREGISTERED.relative_to(ROOT)).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return record


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m eval.protocol",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true", help="write preregistered.json")
    group.add_argument("--verify", action="store_true", help="check nothing has moved")
    group.add_argument("--amend", metavar="REASON", help="record a change, with --change")
    parser.add_argument("--change", help="what the amendment changes")
    args = parser.parse_args(argv)

    try:
        if args.freeze:
            record = freeze(args.root)
            print(f"frozen at {record['frozen_at']}")
            print(f"  commit            {record['git_commit']}")
            print(f"  protocol_sha256   {record['protocol_sha256']}")
            print(f"  declaration_sha   {record['declaration_sha256']}")
            for path, digest in sorted(record["inputs_sha256"].items()):
                print(f"  {digest[:16]}  {path}")
            print("\nCommit preregistered.json now, before producing any result.")
            return 0
        if args.amend:
            if not args.change:
                print("error: --amend needs --change", file=sys.stderr)
                return 2
            record = amend(args.amend, args.change, args.root)
            print(f"amendment {len(record['amendments'])} recorded")
            return 0
        problems = verify(args.root)
        record = load(args.root)
        print(f"frozen at {record['frozen_at']} (commit {record['git_commit']})")
        for problem in problems:
            print(f"  {problem}")
        print("nothing has moved since the freeze" if not problems
              else f"{len(problems)} problem(s): a result produced now would not match the protocol")
        return 1 if problems else 0
    except ProtocolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
