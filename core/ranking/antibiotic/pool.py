"""Candidate pool: approved antibiotics from the ChEMBL catalogue (WS1, issue #12).

"Approved" is ChEMBL ``max_phase == 4`` and not withdrawn. Phase 2 and 3 drugs are in the
catalogue but are not approved, so they are left out of the ranking. Every drug that is left
out is logged with the reason, so the pool size is never a silent number.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .evasion import Drug

APPROVED_PHASE = 4


def _read(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle, delimiter="\t")


def _int(value: str) -> int | None:
    return int(value) if value not in ("", None) else None


def catalogue_release(release_dir: Path | str) -> str:
    """The `chembl-37` style release string recorded in the catalogue manifest."""
    manifest = json.loads((Path(release_dir) / "manifest.json").read_text())
    name = manifest["chembl"]["release"]  # e.g. "ChEMBL_37"
    return name.lower().replace("_", "-")


def load_pool(release_dir: Path | str, approved_only: bool = True) -> tuple[list[Drug], list[dict]]:
    """Return (approved drugs, exclusion log). Both are deterministic for a given release.

    ``approved_only=False`` keeps every catalogue drug (investigational, withdrawn, or without
    a structure) so the evasion rule can be checked against drugs the ranking does not offer,
    such as colistin. The ranking itself always uses the default.
    """
    tables = Path(release_dir) / "tables"
    cards: dict[str, list[dict]] = defaultdict(list)
    for r in _read(tables / "antibiotic_card.tsv"):
        cards[r["chembl_id"]].append(r)
    mechanisms: dict[str, list[dict]] = defaultdict(list)
    for r in _read(tables / "antibiotic_mechanisms.tsv"):
        mechanisms[r["chembl_id"]].append(r)

    drugs, log = [], []
    for r in _read(tables / "antibiotics.tsv"):
        reason = None
        if not approved_only:
            pass
        elif _int(r["max_phase"]) != APPROVED_PHASE:
            reason = f"not approved (ChEMBL max_phase {r['max_phase']})"
        elif r["withdrawn"] == "1":
            reason = "withdrawn from the market"
        elif not r["smiles"] or not r["inchikey"]:
            reason = "no structure in ChEMBL, so no smoke test is possible"
        if reason:
            log.append({"chembl_id": r["chembl_id"], "name": r["name"], "reason": reason})
            continue
        rows = cards.get(r["chembl_id"], [])
        found = sorted({c["class_aro_id"] for c in rows if c["class_aro_id"]})
        if len(found) > 1:  # not in the current catalogue; refuse to pick between classes
            log.append({"chembl_id": r["chembl_id"], "name": r["name"],
                        "reason": f"maps to several CARD classes {found}; class left unknown"})
            found = []
        chosen = next((c for c in rows if found and c["class_aro_id"] == found[0]), None)
        mech = mechanisms.get(r["chembl_id"], [])
        drugs.append(Drug(
            chembl_id=r["chembl_id"], name=r["name"], smiles=r["smiles"], inchikey=r["inchikey"],
            class_aro_id=found[0] if found else None,
            class_name=chosen["class_name"] if chosen else None,
            term_aro_ids=tuple(sorted({c["term_aro_id"] for c in rows if c["term_aro_id"]})),
            class_route=chosen["match"] if chosen else None,
            mechanism="; ".join(dict.fromkeys(m["mechanism_of_action"] for m in mech)) or None,
            target="; ".join(dict.fromkeys(m["target_name"] for m in mech)) or None,
            max_phase=_int(r["max_phase"]) or 0, first_approval=_int(r["first_approval"]),
        ))
    return drugs, log
