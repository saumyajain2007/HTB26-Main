"""Antibiotic catalogue from ChEMBL, mapped onto CARD's drug-class vocabulary (issue #12).

One row per parent drug with an ATC code under J01 (antibacterials for systemic use). Salts and
other forms are merged into their parent, and each merge is logged. Nothing else is dropped:
every field a drug lacks (structure, mechanism, CARD class) is logged with a reason instead,
so a missing value is never silent.

CARD classes are found by three routes, tried in order, and the route is recorded:

    chembl_xref   CARD's own ChEMBL cross-reference on an antibiotic term (most reliable)
    name          the drug's ChEMBL name or synonym equals the name or synonym of a CARD
                  antibiotic term
    atc_level4    the drug's ATC level-4 group maps to one CARD class (ATC_LEVEL4_TO_CARD below);
                  only for groups where the correspondence is unambiguous

A drug's CARD class is the nearest Drug Class category term above its antibiotic term in the
ARO ``is_a`` tree. Join on ARO ids, never names.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from .card import CardError, DEFAULT_DIR, read_table, sha256_file, write_table

CHEMBL_DB = DEFAULT_DIR.parent / "chembl_extract" / "chembl_37" / "chembl_37_sqlite" / "chembl_37.db"
CHEMBL_ARCHIVE = DEFAULT_DIR.parent / "chembl_37_sqlite.tar.gz"
DEFAULT_OUT = DEFAULT_DIR.parent / "antibiotics"

ANTIBIOTIC_MOLECULE = "ARO:1000003"

# ATC level-4 group -> CARD Drug Class (ARO id). Only groups whose members all fall in one CARD
# class. J01XX (other antibacterials), J01XA..XD and the combination groups are left out on
# purpose: they are heterogeneous, so those drugs get a logged reason instead of a guess.
ATC_LEVEL4_TO_CARD = {
    "J01AA": "ARO:3000050",  # Tetracyclines -> tetracycline antibiotic
    "J01CA": "ARO:3000008",  # Penicillins with extended spectrum -> penicillin beta-lactam
    "J01CE": "ARO:3000008",  # Beta-lactamase sensitive penicillins
    "J01CF": "ARO:3000008",  # Beta-lactamase resistant penicillins
    "J01DH": "ARO:0000020",  # Carbapenems -> carbapenem
    "J01EB": "ARO:3000282",  # Short-acting sulfonamides -> sulfonamide antibiotic
    "J01EC": "ARO:3000282",  # Intermediate-acting sulfonamides
    "J01ED": "ARO:3000282",  # Long-acting sulfonamides
    "J01FA": "ARO:0000000",  # Macrolides -> macrolide antibiotic
    "J01FG": "ARO:0000026",  # Streptogramins -> streptogramin antibiotic
    "J01GA": "ARO:0000016",  # Streptomycins -> aminoglycoside antibiotic
    "J01GB": "ARO:0000016",  # Other aminoglycosides
    "J01MA": "ARO:0000001",  # Fluoroquinolones -> fluoroquinolone antibiotic
    "J01MB": "ARO:0000001",  # Other quinolones (CARD files quinolones under fluoroquinolone)
    "J01XE": "ARO:3004116",  # Nitrofuran derivatives -> nitrofuran antibiotic
}

TABLES = {
    "antibiotics": (
        "chembl_id", "name", "molecule_type", "max_phase", "first_approval", "withdrawn",
        "smiles", "inchikey", "n_indications",
    ),
    "antibiotic_atc": ("chembl_id", "atc_code", "level4", "level4_description", "who_name"),
    "antibiotic_mechanisms": (
        "chembl_id", "mechanism_of_action", "action_type", "target_chembl_id", "target_name",
        "target_type", "target_organism",
    ),
    "antibiotic_card": ("chembl_id", "match", "term_aro_id", "term_name", "class_aro_id", "class_name"),
    "catalogue_log": ("chembl_id", "name", "kind", "field", "reason"),
}

LICENCE = {
    "chembl": "CC-BY-SA-3.0. Attribute ChEMBL release 37; adaptations are share-alike.",
    "card": "CC-BY-4.0 as stated by CARD; commercial use needs McMaster's permission (see THIRD_PARTY_NOTICES.md).",
}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


class CardIndex:
    """What the catalogue needs from the CARD tables: names, the is_a tree and Drug Classes."""

    def __init__(self, release: Path):
        self.terms = {r["aro_accession"]: r for r in read_table(release, "aro_terms")}
        self.parents = defaultdict(set)
        for r in read_table(release, "aro_relations"):
            if r["relation"] == "is_a":
                self.parents[r["subject"]].add(r["object"])
        self.drug_classes = {r["aro_accession"] for r in read_table(release, "aro_categories")
                             if r["category_class"] == "Drug Class"}
        self.by_chembl = defaultdict(set)
        for r in read_table(release, "aro_xrefs"):
            if r["db"] == "ChEMBL":
                self.by_chembl[r["xref_id"]].add(r["aro_accession"])
        self.by_name = defaultdict(set)
        for aro_id, term in self.terms.items():
            self.by_name[norm(term["name"])].add(aro_id)
        for r in read_table(release, "aro_synonyms"):
            self.by_name[norm(r["synonym"])].add(r["aro_accession"])

    def is_antibiotic(self, aro_id: str) -> bool:
        return aro_id in self.drug_classes or ANTIBIOTIC_MOLECULE in self.ancestors(aro_id)

    def ancestors(self, aro_id: str) -> set[str]:
        seen, stack = set(), [aro_id]
        while stack:
            for parent in self.parents.get(stack.pop(), ()):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return seen

    def nearest_classes(self, aro_id: str) -> list[str]:
        """Drug Class terms at the smallest is_a distance above (or equal to) the term."""
        seen, frontier = {aro_id}, [aro_id]
        while frontier:
            found = sorted(x for x in frontier if x in self.drug_classes)
            if found:
                return found
            frontier = sorted({p for x in frontier for p in self.parents.get(x, ()) if p not in seen})
            seen.update(frontier)
        return []


def _family(db) -> dict[int, list[int]]:
    """parent molregno -> every molregno (parent included) of J01 drugs, with the J01 members only."""
    parents = defaultdict(set)
    for molregno, parent in db.execute(
        """select a.molregno, coalesce(h.parent_molregno, a.molregno)
           from molecule_atc_classification a left join molecule_hierarchy h using (molregno)
           where a.level5 like 'J01%'"""
    ):
        parents[parent].add(molregno)
    return parents


def build_catalogue(chembl_db: Path | str, card_release: Path | str, out_root: Path | str = DEFAULT_OUT,
                    chembl_archive: Path | str | None = CHEMBL_ARCHIVE, log=print) -> Path:
    chembl_db, card_release = Path(chembl_db), Path(card_release)
    if not chembl_db.exists():
        raise CardError(f"{chembl_db} does not exist (extract it from the ChEMBL sqlite archive)")
    card_manifest_path = card_release / "manifest.json"
    if not card_manifest_path.exists():
        raise CardError(f"{card_manifest_path} does not exist (run: python -m htb_resistance build)")
    card_manifest = json.loads(card_manifest_path.read_text())
    card = CardIndex(card_release)

    db = sqlite3.connect(f"file:{chembl_db}?mode=ro", uri=True)
    chembl_version = db.execute("select name, creation_date from version where name like 'ChEMBL_%'").fetchone()
    if chembl_version is None:
        raise CardError("no ChEMBL release recorded in the version table")
    release_name = chembl_version[0].lower().replace("_", "-")

    family = _family(db)
    antibiotics, atc_rows, mech_rows, card_rows, log_rows = [], [], [], [], []
    counts = defaultdict(int)

    def logrow(chembl_id, name, kind, field, reason):
        log_rows.append((chembl_id, name, kind, field, reason))

    chembl_ids = {m: c for m, c in db.execute(
        f"select molregno, chembl_id from molecule_dictionary where molregno in ({','.join(map(str, family))})")}
    for parent in sorted(family, key=chembl_ids.get):
        chembl_id, name, mol_type, max_phase, first_approval, withdrawn = db.execute(
            """select chembl_id, pref_name, molecule_type, max_phase, first_approval, withdrawn_flag
               from molecule_dictionary where molregno=?""", (parent,)).fetchone()
        name = name or chembl_id
        members = sorted({parent} | {r[0] for r in db.execute(
            "select molregno from molecule_hierarchy where parent_molregno=?", (parent,))})
        marks = ",".join("?" * len(members))

        for molregno in sorted(family[parent] - {parent}):
            form_id, form_name = db.execute(
                "select chembl_id, coalesce(pref_name, chembl_id) from molecule_dictionary where molregno=?",
                (molregno,)).fetchone()
            logrow(form_id, form_name, "merged", "", f"J01 code on a salt or form; merged into parent {chembl_id} ({name})")
            counts["merged_forms"] += 1

        structure = db.execute(
            "select canonical_smiles, standard_inchi_key from compound_structures where molregno=?", (parent,)).fetchone()
        smiles, inchikey = structure if structure else ("", "")
        if not smiles:
            logrow(chembl_id, name, "gap", "smiles", f"no structure in ChEMBL (molecule_type {mol_type})")
        n_indications = db.execute(
            f"select count(distinct mesh_id) from drug_indication where molregno in ({marks})", members).fetchone()[0]
        antibiotics.append((chembl_id, name, mol_type or "", "" if max_phase is None else int(max_phase),
                            first_approval or "", int(bool(withdrawn)), smiles or "", inchikey or "", n_indications))

        codes = db.execute(
            f"""select distinct a.level5, c.level4, c.level4_description, c.who_name
                from molecule_atc_classification a join atc_classification c using (level5)
                where a.level5 like 'J01%' and a.molregno in ({marks}) order by a.level5""", members).fetchall()
        atc_rows += [(chembl_id, *row) for row in codes]

        mechanisms = db.execute(
            f"""select distinct dm.mechanism_of_action, coalesce(dm.action_type, ''), coalesce(t.chembl_id, ''),
                       coalesce(t.pref_name, ''), coalesce(t.target_type, ''), coalesce(t.organism, '')
                from drug_mechanism dm left join target_dictionary t using (tid)
                where dm.molregno in ({marks}) order by 1, 3""", members).fetchall()
        mech_rows += [(chembl_id, *row) for row in mechanisms]
        if not mechanisms:
            logrow(chembl_id, name, "gap", "mechanism", "no mechanism of action recorded in ChEMBL")
        elif not any(m[2] for m in mechanisms):
            logrow(chembl_id, name, "gap", "target", "mechanism recorded but no target")

        # CARD class: xref, then name, then ATC group.
        family_ids = {chembl_id} | {r[0] for r in db.execute(
            f"select chembl_id from molecule_dictionary where molregno in ({marks})", members)}
        names = {norm(name)} | {norm(r[0]) for r in db.execute(
            f"select synonyms from molecule_synonyms where molregno in ({marks})", members)}
        named = {a for n in names for a in card.by_name.get(n, ())}
        terms, match = sorted({a for f in family_ids for a in card.by_chembl.get(f, ())}), "chembl_xref"
        if len(terms) > 1 and set(terms) & named:
            # CARD 4.0.2 puts cefdinir's term on iclaprim's ChEMBL id: keep terms that agree by name.
            ignored = sorted(set(terms) - named)
            terms = sorted(set(terms) & named)
            if ignored:
                logrow(chembl_id, name, "note", "card_xref",
                       "CARD cross-reference also points at " + ", ".join(card.terms[t]["name"] for t in ignored)
                       + ", ignored because the name does not match")
        if not terms:
            terms, match = sorted(a for a in named if card.is_antibiotic(a)), "name"
        classes: list[str] = []
        if terms:
            classes = sorted({c for t in terms for c in card.nearest_classes(t)})
            if not classes:
                logrow(chembl_id, name, "gap", "card_class",
                       f"CARD term {', '.join(card.terms[t]['name'] for t in terms)} ({match}) is not under a Drug Class")
        else:
            level4 = sorted({row[1] for row in codes})
            mapped = sorted({ATC_LEVEL4_TO_CARD[c] for c in level4 if c in ATC_LEVEL4_TO_CARD})
            if len(mapped) == 1 and all(c in ATC_LEVEL4_TO_CARD for c in level4):
                if mapped[0] not in card.drug_classes:
                    raise CardError(f"ATC map points at {mapped[0]}, which is not a Drug Class in this CARD release")
                classes, match = mapped, "atc_level4"
            else:
                match = ""
                logrow(chembl_id, name, "gap", "card_class",
                       "no CARD antibiotic term by ChEMBL cross-reference or name, and ATC group "
                       f"{'/'.join(level4)} has no single CARD class")
        if len(classes) > 1:
            logrow(chembl_id, name, "note", "card_class",
                   "maps to more than one CARD class: " + ", ".join(card.terms[c]["name"] for c in classes))
        if classes:
            counts[f"card_{match}"] += 1
            for c in classes:
                if match == "atc_level4":
                    card_rows.append((chembl_id, match, "", "", c, card.terms[c]["name"]))
                else:
                    owners = [t for t in terms if c in card.nearest_classes(t)]
                    for t in owners:
                        card_rows.append((chembl_id, match, t, card.terms[t]["name"], c, card.terms[c]["name"]))
        else:
            counts["card_unmapped"] += 1
            for t in terms:
                card_rows.append((chembl_id, match, t, card.terms[t]["name"], "", ""))

    tables = {"antibiotics": antibiotics, "antibiotic_atc": atc_rows, "antibiotic_mechanisms": mech_rows,
              "antibiotic_card": sorted(set(card_rows)), "catalogue_log": log_rows}

    release = Path(out_root) / "releases" / f"{release_name}_card-{card_manifest['card_data_version']}"
    checksums = {n: write_table(release / "tables" / f"{n}.tsv", TABLES[n], tables[n]) for n in TABLES}
    archive = Path(chembl_archive) if chembl_archive and Path(chembl_archive).exists() else None
    manifest = {
        "schema": 1,
        "kind": "antibiotic_catalogue",
        "chembl": {
            "release": chembl_version[0], "creation_date": chembl_version[1],
            "database": chembl_db.name, "database_bytes": chembl_db.stat().st_size,
            "archive": ({"file": archive.name, "bytes": archive.stat().st_size, "sha256": sha256_file(archive)}
                        if archive else None),
        },
        "card": {"version": card_manifest["card_data_version"],
                 "manifest_sha256": sha256_file(card_manifest_path)},
        "rules": {
            "include": "parent drugs with an ATC code under J01 on the parent or any salt or form",
            "card_class_routes": ["chembl_xref", "name", "atc_level4"],
            "atc_level4_to_card": ATC_LEVEL4_TO_CARD,
        },
        "tables": {n: {"rows": len(tables[n]), "sha256": checksums[n], "columns": list(TABLES[n])} for n in TABLES},
        "summary": {"drugs": len(antibiotics), **dict(sorted(counts.items()))},
        "licence": LICENCE,
    }
    (release / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    log(f"wrote {len(antibiotics)} antibiotics to {release}")
    for key, value in manifest["summary"].items():
        log(f"  {key:22} {value:>5}")
    return release


def verify_catalogue(release_dir: Path | str, card_root: Path | str = DEFAULT_DIR) -> list[str]:
    """Problems found (empty if the release matches its manifest and the CARD release it used)."""
    release_dir = Path(release_dir)
    try:
        manifest = json.loads((release_dir / "manifest.json").read_text())
    except (OSError, ValueError) as exc:
        return [f"manifest.json unreadable: {exc}"]
    problems = []
    for name in TABLES:
        info = manifest.get("tables", {}).get(name)
        path = release_dir / "tables" / f"{name}.tsv"
        if info is None:
            problems.append(f"{name}: not in manifest")
        elif not path.exists():
            problems.append(f"{name}: file missing")
        elif sha256_file(path) != info["sha256"]:
            problems.append(f"{name}: checksum differs from manifest")
        elif sum(1 for _ in _rows(path)) != info["rows"]:
            problems.append(f"{name}: row count differs from manifest")
    card_manifest = Path(card_root) / "releases" / manifest.get("card", {}).get("version", "?") / "manifest.json"
    if card_manifest.exists() and sha256_file(card_manifest) != manifest["card"]["manifest_sha256"]:
        problems.append("the CARD release this catalogue was built from has changed")
    return problems


def _rows(path: Path):
    import csv
    with path.open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f, delimiter="\t")
