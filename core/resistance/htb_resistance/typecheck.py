"""Ontology type check for the pathogens, ARO terms and drug names the contracts use.

Issue #10. results/ERRATA.md records a trait (EFO_0803536) used where a Disease was meant. The
equivalent mistake here would be an ARO id for a *gene* where a *drug class* is meant, a drug
class where a mechanism is meant, or a drug name that is not the molecule it claims to be. Names
are not checked, only what the id is in CARD's ontology.

Expected type of each position, from the ARO ontology (CARD 4.0.2):

    gene / determinant   descends from ARO:3000000 "determinant of antibiotic resistance"
    mechanism            Resistance Mechanism category, descends from ARO:1000002
    drug class           Drug Class category (CARD lists three that sit outside ARO:1000003)
    antibiotic molecule  descends from ARO:1000003 "antibiotic molecule"

Pathogens are checked by NCBI taxid; the rank must be species. That needs the network, so the
pinned table below is what the offline tests compare against.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

DETERMINANT = "ARO:3000000"
MECHANISM_ROOT = "ARO:1000002"
ANTIBIOTIC_MOLECULE = "ARO:1000003"

# NCBI taxonomy, rank species, checked 2026-11-07. The three ESKAPE species proposed in tasks.md.
PATHOGENS = {
    1280: "Staphylococcus aureus",
    470: "Acinetobacter baumannii",
    573: "Klebsiella pneumoniae",
}


class Ontology:
    def __init__(self, tables: Path):
        def rows(name):
            with open(tables / f"{name}.tsv", encoding="utf-8", newline="") as f:
                return list(csv.DictReader(f, delimiter="\t"))

        self.terms = {r["aro_accession"]: r for r in rows("aro_terms")}
        self._parents = defaultdict(set)
        for r in rows("aro_relations"):
            if r["relation"] == "is_a":
                self._parents[r["subject"]].add(r["object"])
        self.categories = {(r["category_class"], r["aro_accession"]) for r in rows("aro_categories")}
        self.chembl = defaultdict(set)  # ChEMBL id -> ARO ids
        for r in rows("aro_xrefs"):
            if r["db"] == "ChEMBL":
                self.chembl[r["xref_id"]].add(r["aro_accession"])

    def ancestors(self, aro_id: str) -> set[str]:
        seen: set[str] = set()
        stack = [aro_id]
        while stack:
            for parent in self._parents.get(stack.pop(), ()):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return seen

    def kinds(self, aro_id: str) -> set[str]:
        """What kind of thing an id is: any of determinant, mechanism, drug_class, antibiotic."""
        found = set()
        if aro_id not in self.terms:
            return found
        up = self.ancestors(aro_id)
        if DETERMINANT in up:
            found.add("determinant")
        if MECHANISM_ROOT in up or ("Resistance Mechanism", aro_id) in self.categories:
            found.add("mechanism")
        if ("Drug Class", aro_id) in self.categories:
            found.add("drug_class")
        if ANTIBIOTIC_MOLECULE in up:
            found.add("antibiotic")
        return found


def check_term(onto: Ontology, aro_id: str, expected: str) -> str | None:
    """Return a problem description, or None when the id is the expected kind of term."""
    term = onto.terms.get(aro_id)
    if term is None:
        return f"{aro_id} is not in CARD"
    if term["is_obsolete"] == "true":
        return f"{aro_id} {term['name']!r} is obsolete"
    kinds = onto.kinds(aro_id)
    if expected not in kinds:
        return f"{aro_id} {term['name']!r} is {sorted(kinds) or 'untyped'}, expected {expected}"
    return None


def check_drug(onto: Ontology, chembl_id: str, name: str) -> str | None:
    """A drug is checked through CARD's own ChEMBL cross-reference: the id must point at an
    antibiotic molecule whose name is the drug's name."""
    ids = onto.chembl.get(chembl_id)
    if not ids:
        return f"{chembl_id} ({name}) has no ARO term with that ChEMBL cross-reference"
    for aro_id in ids:
        if "antibiotic" in onto.kinds(aro_id) and onto.terms[aro_id]["name"].lower() == name.lower():
            return None
    return f"{chembl_id} resolves to {sorted(onto.terms[a]['name'] for a in ids)}, not {name!r}"


def check_drug_chembl(conn, chembl_id: str, name: str) -> str | None:
    """Check a drug against ChEMBL itself (``conn`` is a sqlite3 connection to chembl_NN.db).

    The id must be a small molecule whose preferred name is `name` and which carries an ATC code
    under J01 (antibacterials for systemic use). Vancomycin also has A07 and S01 codes, so any
    one J01 code is enough.
    """
    row = conn.execute(
        "select pref_name, molecule_type, molregno from molecule_dictionary where chembl_id = ?",
        (chembl_id,),
    ).fetchone()
    if row is None:
        return f"{chembl_id} is not in ChEMBL"
    pref_name, molecule_type, molregno = row
    if (pref_name or "").lower() != name.lower():
        return f"{chembl_id} is {pref_name!r} in ChEMBL, not {name!r}"
    if molecule_type != "Small molecule":
        return f"{chembl_id} {name!r} is a {molecule_type} in ChEMBL, expected Small molecule"
    atc = [r[0] for r in conn.execute(
        "select level5 from molecule_atc_classification where molregno = ?", (molregno,))]
    if not any(code.startswith("J01") for code in atc):
        return f"{chembl_id} {name!r} has no ATC J01 code in ChEMBL (has {atc or 'none'})"
    return None


def check_fixtures(onto: Ontology, fixtures: Path, chembl=None) -> list[str]:
    """Every id in the frozen contract fixtures, checked for the position it sits in.

    Pass a sqlite3 connection to ChEMBL as `chembl` to check the drugs against it as well.
    """
    problems = []
    profile = json.loads((fixtures / "resistance_profile.json").read_text(encoding="utf-8"))
    for gene in profile["genes"]:
        problems.append(check_term(onto, gene["aro_id"], "determinant"))
        problems += [check_term(onto, m["aro_id"], "mechanism") for m in gene["mechanisms"]]
        problems += [check_term(onto, c["aro_id"], "drug_class") for c in gene["defeated_classes"]]
    for item in profile["mechanisms"]:
        problems.append(check_term(onto, item["aro_id"], "mechanism"))
    for item in profile["defeated_classes"]:
        problems.append(check_term(onto, item["aro_id"], "drug_class"))

    result = json.loads((fixtures / "antibiotic_candidates.json").read_text(encoding="utf-8"))
    for cand in result["candidates"]:
        if cand["source"] != "approved":
            continue
        problems.append(check_drug(onto, cand["candidate_id"], cand["name"]))
        if chembl is not None:
            problems.append(check_drug_chembl(chembl, cand["candidate_id"], cand["name"]))
        drug_class = cand["drug_class"] or {}
        if drug_class.get("aro_id") is None:
            problems.append(f"{cand['candidate_id']} drug class {drug_class.get('name')!r} has no ARO id")
        else:
            problems.append(check_term(onto, drug_class["aro_id"], "drug_class"))
        for pair in cand["evasion"]["defeated_by"]:
            problems.append(check_term(onto, pair["gene_aro_id"], "determinant"))
            problems.append(check_term(onto, pair["mechanism_aro_id"], "mechanism"))
    return [p for p in problems if p]


def check_taxon(taxid: int, name: str, node: dict) -> str | None:
    """`node` is one NCBI Datasets taxonomy node: {"tax_id", "organism_name", "rank"}."""
    if node.get("tax_id") != taxid:
        return f"taxid {taxid} came back as {node.get('tax_id')}"
    if node.get("organism_name") != name:
        return f"taxid {taxid} is {node.get('organism_name')!r}, not {name!r}"
    if node.get("rank") != "SPECIES":
        return f"taxid {taxid} {name!r} has rank {node.get('rank')}, expected SPECIES"
    return None

