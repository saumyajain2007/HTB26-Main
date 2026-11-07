"""Evasion rule: does a resistance profile defeat a given antibiotic? (issue #23)

For one drug and one ResistanceProfile the rule returns the ``evasion`` block of the
AntibioticCandidate contract (docs/contracts.md). It uses only what CARD records:

    unknown         the drug has no CARD drug class, so CARD cannot say either way
    unaffected      no gene in the profile is linked to the drug's class
    partly_affected a gene is linked to the drug's class, but CARD does not name this drug
    defeated        CARD names this drug for a gene in the profile (drug-level link)

Why ``partly_affected`` is the class-only case. CARD's class links on a gene are derived from
the specific drugs CARD lists for it, and CARD's drug-level lists are sparse: mecA is linked to
just methicillin and ceftaroline, yet its classes are all penicillins and cephalosporins. A drug
that shares the class but is not named is therefore *probably* affected, not *known* to be.
Collapsing the two would overstate what CARD says. Both rank below ``unaffected``.

"Unaffected" means no known link in CARD. It is not a measured result.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

STATUSES = ("unaffected", "unknown", "partly_affected", "defeated")
# Best first. `unknown` sits below `unaffected` (no information is not good news) and above
# `partly_affected` (a class link is evidence against the drug; silence is not).
EVASION_ORDER = {status: i for i, status in enumerate(STATUSES)}

DRUG_LINK = "confers_resistance_to_antibiotic"
NAMED_LIMIT = 5


@dataclass(frozen=True)
class Drug:
    """One approved antibiotic from the catalogue, with the CARD keys the rule joins on."""

    chembl_id: str
    name: str
    smiles: str | None
    inchikey: str | None
    class_aro_id: str | None  # CARD drug class; None when the catalogue could not map one
    class_name: str | None
    term_aro_ids: tuple[str, ...]  # the drug's own CARD antibiotic terms (a drug can have several)
    class_route: str | None   # how the class was found: chembl_xref, name or atc_level4
    mechanism: str | None
    target: str | None
    max_phase: int
    first_approval: int | None


class DrugLinks:
    """CARD's drug-level links: for each determinant, the antibiotic terms it is listed against."""

    def __init__(self, links: Mapping[str, set[str]], names: Mapping[str, str], release: str):
        self._links = {gene: frozenset(drugs) for gene, drugs in links.items()}
        self._names = dict(names)
        self.release = release

    @classmethod
    def from_card(cls, release_dir: Path | str) -> "DrugLinks":
        release_dir = Path(release_dir)
        tables = release_dir / "tables"
        names = {r["aro_accession"]: r["name"] for r in _read(tables / "aro_terms.tsv")}
        links: dict[str, set[str]] = defaultdict(set)
        for r in _read(tables / "aro_relations.tsv"):
            if r["relation"] == DRUG_LINK:
                links[r["subject"]].add(r["object"])
        version = json.loads((release_dir / "manifest.json").read_text())["card_data_version"]
        return cls(links, names, f"card-{version}")

    def drugs_for(self, gene_aro_id: str) -> frozenset[str]:
        return self._links.get(gene_aro_id, frozenset())

    def name(self, aro_id: str) -> str:
        return self._names.get(aro_id, aro_id)


def _read(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle, delimiter="\t")


def _named(links: DrugLinks, gene: dict) -> str:
    names = sorted(links.name(a) for a in links.drugs_for(gene["aro_id"]))
    if not names:
        return "no individual drugs"
    shown = ", ".join(names[:NAMED_LIMIT])
    return shown if len(names) <= NAMED_LIMIT else f"{shown} and {len(names) - NAMED_LIMIT} more"


def _hits(genes: list[dict], mechanism_ids: set[str] | None = None) -> list[dict]:
    """One {gene_aro_id, mechanism_aro_id} per gene and mechanism, in profile order."""
    return [
        {"gene_aro_id": g["aro_id"], "mechanism_aro_id": m["aro_id"]}
        for g in genes for m in g["mechanisms"]
        if mechanism_ids is None or m["aro_id"] in mechanism_ids
    ]


def assess_evasion(profile: dict, drug: Drug, links: DrugLinks) -> dict:
    """The `evasion` block for one drug under one profile."""
    genes = profile["genes"]
    all_evidence = sorted({e for g in genes for e in g["evidence_ids"]}, key=_evidence_key)

    if drug.class_aro_id is None:
        return {
            "status": "unknown", "defeated_by": [], "profile_evidence_ids": all_evidence,
            "rationale": f"{drug.name.title()} has no CARD drug class in the catalogue, so CARD cannot say "
                         "whether any gene in the profile affects it.",
        }

    terms = set(drug.term_aro_ids)
    named = [g for g in genes if terms & links.drugs_for(g["aro_id"])]
    by_class = [g for g in genes if any(c["aro_id"] == drug.class_aro_id for c in g["defeated_classes"])]

    if named:
        genes_hit, status = named, "defeated"
        rationale = "CARD lists {drug} for {genes}.".format(
            drug=drug.name.title(), genes=_join(g["name"] for g in named))
    elif by_class:
        genes_hit, status = by_class, "partly_affected"
        listed = "; ".join(f"for {g['name']} it lists {_named(links, g)}" for g in by_class)
        rationale = (
            f"CARD links {_join(g['name'] for g in by_class)} to {drug.class_name}, but {listed}, not "
            f"{drug.name.title()}. {drug.name.title()} shares the class, so it is probably affected; "
            "CARD does not say so directly."
        )
    else:
        return {
            "status": "unaffected", "defeated_by": [], "profile_evidence_ids": all_evidence,
            "rationale": f"No gene in the profile is linked to {drug.class_name} in CARD.",
        }

    return {
        "status": status,
        "defeated_by": _hits(genes_hit),
        "profile_evidence_ids": _evidence_behind(profile, genes_hit, None if named else drug.class_aro_id),
        "rationale": rationale,
    }


def _evidence_behind(profile: dict, genes_hit: list[dict], class_aro_id: str | None) -> list[str]:
    """The profile evidence a verdict rests on, not everything known about the genes.

    A gene can carry CARD's own evidence and a curated one (source "curated", a class CARD's
    download omits). A drug CARD names directly rests on CARD's own record. A drug that only
    shares a class rests on the evidence behind that class, so a penicillin never cites the
    curated carbapenem entry, and a carbapenem cites only that one.
    """
    ids = {e for g in genes_hit for e in g["evidence_ids"]}
    if class_aro_id is None:
        source = {e["id"]: e["source"] for e in profile["evidence"]}
        ids = {e for e in ids if source.get(e) == "card"}
    else:
        rolled = next((c for c in profile["defeated_classes"] if c["aro_id"] == class_aro_id), None)
        ids &= set(rolled["evidence_ids"]) if rolled else set()
    return sorted(ids, key=_evidence_key)


def _join(names) -> str:
    names = list(dict.fromkeys(names))
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _evidence_key(evidence_id: str) -> tuple[str, int]:
    return evidence_id[:1], int(evidence_id[1:])


def mechanisms_evaded(profile: dict, evasion: dict) -> list[str]:
    """Names of the profile's mechanisms that none of the drug's defeating genes use.

    For `unknown` this is empty: with no class, nothing can be said to be evaded.
    """
    if evasion["status"] == "unknown":
        return []
    used = {h["mechanism_aro_id"] for h in evasion["defeated_by"]}
    return [m["name"] for m in profile["mechanisms"] if m["aro_id"] not in used]
