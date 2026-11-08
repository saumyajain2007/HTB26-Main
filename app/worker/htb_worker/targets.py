"""WS3 target registry: every target states whether a resistance-mutant structure exists.

scope.md WS3 asks for a wild-type and a resistance-mutant entry per target "where one
exists", and for the mutant case: "where no mutant structure exists, say so and skip,
rather than faking it". A sentence in a document does not stop anyone docking a wild-type
receptor and labelling it the mutant, so the rule is enforced here instead:

    check_registry()    a target that says nothing about its mutant is an error; a mutant
                        PDB id that names no mutation is an error; a status other than
                        "exists" that still carries a PDB id is an error.

The registry is ``structures/targets.json``. Two checks need something this module cannot
assume, so both are opt-in:

    resolve(pdb_id)             reads RCSB for one entry: organism, resolution, ligands and
                                the mutation count RCSB records. Needs the network.
    mutations(release, name)    the resistance mutations CARD lists for a determinant, read
                                from a built CARD release's tables. Needs that release.

``mutations`` reads the release's TSVs directly with the standard library rather than
importing htb_resistance, so this package gains no dependency on the data layer.

    python -m htb_worker.targets                      the statement table, offline
    python -m htb_worker.targets --verify             plus the RCSB check on every recorded id
    python -m htb_worker.targets --mutations DIR      plus CARD's mutations per determinant
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

STRUCTURES_DIR = Path(__file__).resolve().parents[1] / "structures"
REGISTRY = STRUCTURES_DIR / "targets.json"

RCSB_ENTRY = "https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
RCSB_POLYMER = "https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb_id}/{entity}"
RCSB_NONPOLYMER = "https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{pdb_id}/{entity}"

STATUSES = {"exists", "none_known", "not_determined", "not_applicable"}
TARGET_FIELDS = {"id", "name", "organism", "card_determinant", "card_mechanism", "why",
                 "essentiality_evidence", "wild_type", "mutant", "source_check"}
OPTIONAL_TARGET_FIELDS = {"ncbi_taxid", "candidate_organisms"}
ENTRY_FIELDS = {"pdb_id", "symbol", "organism", "uniprot", "ligand", "verdict", "reason",
                "source_check"}
VERDICTS = {"keep", "drop", "replace", "not_reviewed"}

# Resistance by altering an existing target is the only case where a resistance mutant of
# that target is the right thing to look for.
ALTERATION = "antibiotic target alteration"


class RegistryError(ValueError):
    """The registry is malformed. Never a guessed or partial target."""


def load(path: Path | str = REGISTRY) -> dict:
    try:
        registry = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"{path} does not exist") from exc
    except ValueError as exc:
        raise RegistryError(f"{path} is not valid JSON: {exc}") from exc
    problems = check_registry(registry)
    if problems:
        raise RegistryError(f"{path} is not a usable registry: " + "; ".join(problems))
    return registry


def targets(registry: dict) -> list:
    return registry["targets"]


def _check_slot(problems: list, target_id: str, slot: str, value: Any, *, is_mutant: bool):
    """A wild_type or mutant block. The point of the whole module is in here."""
    if not isinstance(value, dict):
        problems.append(f"{target_id}: {slot} is not an object")
        return
    status = value.get("status")
    if status not in STATUSES:
        problems.append(f"{target_id}: {slot} status {status!r} is not one of {sorted(STATUSES)}")
        return
    pdb_id = value.get("pdb_id")

    if status == "exists":
        if not pdb_id:
            problems.append(f"{target_id}: {slot} says it exists but names no PDB id")
        elif not (isinstance(pdb_id, str) and len(pdb_id) == 4 and pdb_id.isalnum()
                  and pdb_id == pdb_id.upper()):
            problems.append(f"{target_id}: {slot} pdb_id {pdb_id!r} is not a 4-character "
                            "upper-case PDB id")
        if is_mutant and not value.get("mutations"):
            # The whole point: a structure called a mutant has to say which mutation it
            # carries, or it is a wild type with a label on it.
            problems.append(f"{target_id}: mutant says it exists but names no mutations")
        if not is_mutant and not value.get("has_cocrystallised_ligand"):
            problems.append(f"{target_id}: wild_type exists but has no co-crystallised "
                            "ligand, so the redocking control cannot run (scope.md WS3)")
    else:
        if pdb_id:
            problems.append(f"{target_id}: {slot} status is {status!r} but it still carries "
                            f"pdb_id {pdb_id!r}")
        if not value.get("reason"):
            problems.append(f"{target_id}: {slot} is {status!r} without a reason")
        if is_mutant and value.get("mutations"):
            problems.append(f"{target_id}: mutant is {status!r} but lists mutations")


def check_registry(registry: dict) -> list:
    """Return a list of problems. Empty means every target states its mutant position."""
    problems: list = []
    if not isinstance(registry, dict) or "targets" not in registry:
        return ["the registry needs a 'targets' list"]

    seen: set = set()
    for target in registry["targets"]:
        target_id = target.get("id", "<no id>")
        missing = TARGET_FIELDS - set(target)
        extra = set(target) - TARGET_FIELDS - OPTIONAL_TARGET_FIELDS
        if missing:
            problems.append(f"{target_id}: missing {sorted(missing)}")
        if extra:
            problems.append(f"{target_id}: unexpected {sorted(extra)}")
        if target_id in seen:
            problems.append(f"{target_id}: duplicate target")
        seen.add(target_id)
        if not target.get("source_check"):
            problems.append(f"{target_id}: no source_check recording what was read")
        if not target.get("why"):
            problems.append(f"{target_id}: no 'why', so its place in the target list is unstated")
        if target.get("organism") is None and not target.get("candidate_organisms"):
            problems.append(f"{target_id}: organism is null and no candidate_organisms given")

        _check_slot(problems, target_id, "wild_type", target.get("wild_type"), is_mutant=False)
        _check_slot(problems, target_id, "mutant", target.get("mutant"), is_mutant=True)

        # Only a target-alteration determinant can wave the mutant question away.
        mutant = target.get("mutant") or {}
        if (mutant.get("status") == "not_applicable"
                and target.get("card_mechanism") == ALTERATION):
            problems.append(f"{target_id}: mutant is not_applicable, but the mechanism is "
                            f"{ALTERATION!r}, where a resistance mutant is exactly the point")

    for entry in registry.get("reviewed_entries", []):
        pdb_id = entry.get("pdb_id", "<no id>")
        if set(entry) != ENTRY_FIELDS:
            problems.append(f"{pdb_id}: reviewed entry fields "
                            f"{sorted(set(entry) ^ ENTRY_FIELDS)} are wrong")
        if entry.get("verdict") not in VERDICTS:
            problems.append(f"{pdb_id}: verdict {entry.get('verdict')!r} is not one of "
                            f"{sorted(VERDICTS)}")
        if not entry.get("reason") or not entry.get("source_check"):
            problems.append(f"{pdb_id}: a reviewed entry needs a reason and a source_check")
    return problems


def prepared_entries(structures_dir: Path | str = STRUCTURES_DIR) -> dict:
    """What is actually committed under structures/, read from each meta.json.

    This is how the four inherited entries were identified, so the finding is reproducible
    rather than asserted.
    """
    found = {}
    for meta_path in sorted(Path(structures_dir).glob("*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        found[meta["pdb_id"]] = {
            "symbol": meta.get("symbol"),
            "uniprot": meta.get("uniprot", []),
            "title": meta.get("title", ""),
            "target_id": meta.get("target_id"),
            "ligand": (meta.get("ligand") or {}).get("name"),
        }
    return found


def unreviewed(registry: dict, structures_dir: Path | str = STRUCTURES_DIR) -> list:
    """Prepared structures the registry has not given a verdict on."""
    reviewed = {e["pdb_id"] for e in registry.get("reviewed_entries", [])}
    return sorted(set(prepared_entries(structures_dir)) - reviewed)


def recorded_structures(registry: dict) -> list:
    """Every (target id, slot, PDB id) the registry actually claims."""
    out = []
    for target in targets(registry):
        for slot in ("wild_type", "mutant"):
            pdb_id = (target.get(slot) or {}).get("pdb_id")
            if pdb_id:
                out.append((target["id"], slot, pdb_id))
    return out


def mutations(release_dir: Path | str, determinant: str) -> list:
    """The resistance mutations CARD lists for a determinant, by its ARO term name.

    Reads a release built by ``python -m htb_resistance build``. Returns [] when the
    determinant is absent, so a caller can tell "CARD knows none" from "not looked up".
    """
    tables = Path(release_dir) / "tables"

    def rows(name: str):
        with (tables / f"{name}.tsv").open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle, delimiter="\t")

    wanted = determinant.strip().lower()
    accessions = {r["aro_accession"] for r in rows("aro_terms")
                  if r["name"].strip().lower() == wanted}
    if not accessions:
        return []
    found = {r["mutation"] for r in rows("model_variants")
             if r["aro_accession"] in accessions and r["mutation"]}
    return sorted(found)


def resolve(pdb_id: str, timeout: float = 20.0) -> dict:
    """Read one entry from RCSB: organism, resolution, ligands and recorded mutations.

    Needs the network. Returns {"error": ...} rather than raising, so one unreachable
    entry does not stop a whole registry check.
    """
    import urllib.error
    import urllib.request

    def get(url: str):
        request = urllib.request.Request(url, headers={"User-Agent": "htb26-targets-check"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        entry = get(RCSB_ENTRY.format(pdb_id=pdb_id))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"error": f"unreachable: {exc}"}

    organisms: list = []
    mutation_count = 0
    for entity in (entry.get("rcsb_entry_container_identifiers", {})
                   .get("polymer_entity_ids", []) or []):
        try:
            polymer = get(RCSB_POLYMER.format(pdb_id=pdb_id, entity=entity))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            continue
        for source in polymer.get("rcsb_entity_source_organism", []) or []:
            name = source.get("scientific_name")
            if name and name not in organisms:
                organisms.append(name)
        mutation_count += (polymer.get("entity_poly", {}) or {}).get("rcsb_mutation_count", 0) or 0

    # The entry-level "bound components" field leaves out some co-crystallised ligands (3G7B's B47
    # and 3U2K's 087 are missing from it), so the components are read from the entities themselves.
    comp_ids: list = []
    for entity in (entry.get("rcsb_entry_container_identifiers", {})
                   .get("non_polymer_entity_ids", []) or []):
        try:
            nonpoly = get(RCSB_NONPOLYMER.format(pdb_id=pdb_id, entity=entity))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            continue
        comp = (nonpoly.get("pdbx_entity_nonpoly", {}) or {}).get("comp_id")
        if comp and comp not in comp_ids:
            comp_ids.append(comp)

    return {
        "title": (entry.get("struct", {}) or {}).get("title", ""),
        "organisms": organisms,
        "nonpolymer_comp_ids": comp_ids,
        "resolution_angstrom": ((entry.get("rcsb_entry_info", {}) or {})
                                .get("resolution_combined") or [None])[0],
        "ligand_ids": (entry.get("rcsb_entry_info", {}) or {})
                      .get("nonpolymer_bound_components", []) or [],
        "recorded_mutation_count": mutation_count,
    }


def _also_passing(registry: dict) -> list:
    """(target id, entry) for the extra passing structures a wild_type slot lists."""
    return [(t["id"], other) for t in targets(registry)
            for other in (t.get("wild_type") or {}).get("also_passing", []) or []]


def verify(registry: dict) -> list:
    """Check every recorded structure against RCSB. Returns a list of problems."""
    problems = []
    checks = [(target_id, slot, pdb_id) for target_id, slot, pdb_id in recorded_structures(registry)]
    checks += [(target_id, "also_passing", other["pdb_id"]) for target_id, other in _also_passing(registry)]
    for target_id, slot, pdb_id in checks:
        found = resolve(pdb_id)
        if "error" in found:
            problems.append(f"{target_id} {slot} {pdb_id}: {found['error']}")
            continue
        target = next(t for t in targets(registry) if t["id"] == target_id)
        if slot == "also_passing":
            claimed = {"ligand_comp_id": next(o["ligand_comp_id"] for o in target["wild_type"]["also_passing"]
                                              if o["pdb_id"] == pdb_id),
                       "organism": target["wild_type"].get("organism")}
            slot = "wild_type"
        else:
            claimed = target[slot]
        if slot == "mutant" and found["recorded_mutation_count"] == 0:
            problems.append(f"{target_id} mutant {pdb_id}: RCSB records no mutation for this "
                            f"entry, but the registry calls it a mutant carrying "
                            f"{claimed.get('mutations')}")
        if slot == "wild_type":
            ligand = claimed.get("ligand_comp_id")
            if ligand and ligand not in found["nonpolymer_comp_ids"]:
                problems.append(f"{target_id} wild_type {pdb_id}: the registry names ligand {ligand}, but RCSB "
                                f"lists these components: {found['nonpolymer_comp_ids']}")
            elif not ligand and not found["ligand_ids"]:
                problems.append(f"{target_id} wild_type {pdb_id}: RCSB lists no bound ligand, so "
                                "the redocking control cannot run")
        organism = claimed.get("organism") or (
            next(t for t in targets(registry) if t["id"] == target_id).get("organism"))
        if organism and found["organisms"] and not any(
                organism.lower() in name.lower() or name.lower() in organism.lower()
                for name in found["organisms"]):
            problems.append(f"{target_id} {slot} {pdb_id}: RCSB says {found['organisms']}, "
                            f"the registry says {organism!r}")
    return problems


def statement_table(registry: dict) -> str:
    """The thing WS3 asks for: each target's position on a mutant structure."""
    lines = [f"{'target':24} {'mechanism':32} {'wild type':15} mutant", "-" * 95]
    for target in targets(registry):
        wild = target["wild_type"]
        mutant = target["mutant"]
        wild_text = wild["pdb_id"] if wild["status"] == "exists" else wild["status"]
        mutant_text = (f"{mutant['pdb_id']} ({', '.join(mutant['mutations'])})"
                       if mutant["status"] == "exists" else mutant["status"])
        lines.append(f"{target['id']:24} {str(target['card_mechanism'] or '-'):32} "
                     f"{wild_text:15} {mutant_text}")
    exists = sum(1 for t in targets(registry) if t["mutant"]["status"] == "exists")
    lines += ["", f"{len(targets(registry))} targets; {exists} with a mutant structure. "
                  "Every target states its position, which is what WS3 requires."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m htb_worker.targets",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--verify", action="store_true",
                        help="check every recorded structure against RCSB (needs the network)")
    parser.add_argument("--mutations", type=Path, metavar="RELEASE_DIR",
                        help="list the resistance mutations CARD holds for each determinant")
    args = parser.parse_args(argv)

    try:
        registry = load(args.registry)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(statement_table(registry))
    problems = []
    missing = unreviewed(registry)
    if missing:
        problems.append(f"prepared but not reviewed: {', '.join(missing)}")

    if args.mutations:
        print("\nCARD resistance mutations per determinant:")
        for target in targets(registry):
            determinant = target.get("card_determinant")
            if not determinant:
                continue
            found = mutations(args.mutations, determinant)
            print(f"  {target['id']:24} {', '.join(found) if found else 'none in this release'}")

    if args.verify:
        print("\nRCSB check:")
        found = verify(registry)
        problems += found
        print("  every recorded structure matches" if not found else "")

    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
