# pyright: reportMissingImports=false, reportMissingTypeStubs=false
"""Prepare the docking structures (docs/engineering/build-reference.md C2 and C3).

    python -m oxhack_worker.prepare            # every structure, in $DOCKING_VENV
    python -m oxhack_worker.prepare 6WTO 6WTN  # some of them

The prepared set is the one the API lists, `api/oxhack_api/fixtures/structures.json`
(PDB entry, chain, protein, co-crystal ligand). For each entry this downloads it
from RCSB, checks the listing against RCSB's own records and writes
`worker/structures/{PDB}/`, which is committed:

- `receptor.pdb` and `receptor.pdbqt`: the docking chain, prepared by Meeko's
  `mk_prepare_receptor.py` (hydrogens added from its residue templates). Before
  that, gemmi keeps only the chain's protein atoms (no waters, ions or ligands; the
  first of any alternate locations) and makes every residue match a template:
  - a phosphorylated residue (PTR, SEP, TPO) loses its phosphate, and MSE becomes
    MET, when it lies outside the box (refused inside it);
  - a residue whose side chain the crystal does not resolve is cut back to the
    atoms it has: alanine when CB is there, else glycine. No coordinates are
    invented; `meta.json` lists every change.
- `crystal_ligand.sdf`: the co-crystal ligand in its crystal pose (RCSB
  ModelServer), checked atom by atom against the entry's HETATM records.
- `meta.json`: the structure's listing, the box (a 25 angstrom cube on the
  crystal ligand's heavy-atom centroid), the control SMILES (from the PDB
  chemical component dictionary), every receptor change and the sources' SHA-256.

It also writes `worker/structures/settings.json`: the docking settings and the
versions of this toolchain. Jobs are queued with these settings (they are part of
the cache key), and the worker refuses to run with another toolchain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dock import STRUCTURES_DIR, toolchain

REPO_ROOT = Path(__file__).resolve().parents[3]
LISTING = REPO_ROOT / "api" / "oxhack_api" / "fixtures" / "structures.json"

BOX_SIZE = 25.0
SETTINGS = {"engine": "vina", "exhaustiveness": 8, "seed": 42, "n_poses": 9}
"""docs/engineering/build-reference.md C5. Run times at 8, 16 and 32 are in worker/README.md."""

ENTRY_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"
ENTRY_API = "https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
INSTANCE_API = "https://data.rcsb.org/rest/v1/core/polymer_entity_instance/{pdb_id}/{chain}"
ENTITY_API = "https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb_id}/{entity}"
CHEMCOMP_API = "https://data.rcsb.org/rest/v1/core/chemcomp/{comp_id}"
LIGAND_URL = (
    "https://models.rcsb.org/v1/{pdb_id}/ligand"
    "?auth_asym_id={chain}&label_comp_id={comp_id}&encoding=sdf"
)

BACKBONE = ("N", "CA", "C", "O")
SIDE_CHAINS: dict[str, tuple[str, ...]] = {
    "ALA": ("CB",),
    "ARG": ("CB", "CG", "CD", "NE", "CZ", "NH1", "NH2"),
    "ASN": ("CB", "CG", "OD1", "ND2"),
    "ASP": ("CB", "CG", "OD1", "OD2"),
    "CYS": ("CB", "SG"),
    "GLN": ("CB", "CG", "CD", "OE1", "NE2"),
    "GLU": ("CB", "CG", "CD", "OE1", "OE2"),
    "GLY": (),
    "HIS": ("CB", "CG", "ND1", "CD2", "CE1", "NE2"),
    "ILE": ("CB", "CG1", "CG2", "CD1"),
    "LEU": ("CB", "CG", "CD1", "CD2"),
    "LYS": ("CB", "CG", "CD", "CE", "NZ"),
    "MET": ("CB", "CG", "SD", "CE"),
    "PHE": ("CB", "CG", "CD1", "CD2", "CE1", "CE2", "CZ"),
    "PRO": ("CB", "CG", "CD"),
    "SER": ("CB", "OG"),
    "THR": ("CB", "OG1", "CG2"),
    "TRP": ("CB", "CG", "CD1", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"),
    "TYR": ("CB", "CG", "CD1", "CD2", "CE1", "CE2", "CZ", "OH"),
    "VAL": ("CB", "CG1", "CG2"),
}
"""Heavy atoms of each standard residue's side chain."""

MODIFIED: dict[str, tuple[str, dict[str, str]]] = {
    "PTR": ("TYR", {}),
    "SEP": ("SER", {}),
    "TPO": ("THR", {}),
    "MSE": ("MET", {"SE": "SD"}),
}
"""Modified residue -> parent residue, and atoms to rename. Other atoms are dropped."""


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "oxhack-worker/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read()
    return body


def fetch_json(url: str) -> Any:
    return json.loads(fetch(url))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Receptor ---------------------------------------------------------------------


def _keep_atoms(residue: Any, names: Iterable[str]) -> None:
    wanted = set(names)
    for i in reversed(range(len(residue))):
        if residue[i].name not in wanted:
            del residue[i]


def _inside(residue: Any, center: Sequence[float], half: float) -> bool:
    return any(
        all(abs(c - m) <= half for c, m in zip(atom.pos.tolist(), center, strict=True))
        for atom in residue
    )


def clean_receptor(
    pdb_text: str, chain_name: str, center: Sequence[float]
) -> tuple[str, dict[str, Any]]:
    """The chain's protein atoms, every residue complete for a Meeko template, as PDB
    text; and a record of each change."""
    import gemmi

    structure = gemmi.read_pdb_string(pdb_text)
    structure.merge_chain_parts()  # ligands after TER would otherwise be a second chain
    structure.remove_alternative_conformations()
    structure.remove_hydrogens()
    model = structure[0]
    for name in [chain.name for chain in model]:
        if name != chain_name:
            model.remove_chain(name)
    chain = model[chain_name]
    changes: dict[str, Any] = {
        "removed_residues": {},
        "modified_to_parent": [],
        "truncated_side_chains": [],
        "incomplete_backbone_removed": [],
    }
    for i in reversed(range(len(chain))):
        residue = chain[i]
        if residue.name in SIDE_CHAINS or residue.name in MODIFIED:
            continue
        removed = changes["removed_residues"]
        removed[residue.name] = removed.get(residue.name, 0) + 1
        del chain[i]

    for i in reversed(range(len(chain))):
        residue = chain[i]
        where = f"{residue.name} {chain_name}{residue.seqid.num}{residue.seqid.icode.strip()}"
        if residue.name in MODIFIED:
            if _inside(residue, center, BOX_SIZE / 2):
                raise SystemExit(
                    f"{where} is a modified residue inside the docking box; prepare it by hand"
                )
            parent, renames = MODIFIED[residue.name]
            for atom in residue:
                atom.name = renames.get(atom.name, atom.name)
            _keep_atoms(residue, (*BACKBONE, "OXT", *SIDE_CHAINS[parent]))
            residue.name = parent
            residue.het_flag = "A"
            changes["modified_to_parent"].append(f"{where} -> {parent}")
        have = {atom.name for atom in residue}
        if not set(BACKBONE[:3]) <= have:
            changes["incomplete_backbone_removed"].append(where)
            del chain[i]
            continue
        if set(SIDE_CHAINS[residue.name]) - have:
            stub = "ALA" if "CB" in have else "GLY"
            _keep_atoms(residue, (*BACKBONE, "OXT", *SIDE_CHAINS[stub]))
            changes["truncated_side_chains"].append(
                f"{residue.name} {chain_name}{residue.seqid.num} -> {stub}"
            )
            residue.name = stub
    for key in ("modified_to_parent", "truncated_side_chains", "incomplete_backbone_removed"):
        changes[key].reverse()
    structure.setup_entities()
    return structure.make_pdb_string(gemmi.PdbWriteOptions(minimal=True)), changes


def meeko_receptor(clean_pdb: str, out: Path, center: Sequence[float]) -> str:
    """Run mk_prepare_receptor.py; writes receptor.pdbqt and receptor.pdb in `out`."""
    tool = shutil.which("mk_prepare_receptor.py", path=str(Path(sys.executable).parent))
    tool = tool or shutil.which("mk_prepare_receptor.py")
    if tool is None:
        raise SystemExit("mk_prepare_receptor.py is not installed; install Meeko")
    box = [
        "--box_center", *(f"{c:.3f}" for c in center),
        "--box_size", *(f"{BOX_SIZE:g}" for _ in range(3)),
    ]  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="oxhack-prepare-") as scratch:
        source = Path(scratch) / "clean.pdb"
        source.write_text(clean_pdb)
        command = [
            sys.executable,
            tool,
            "--read_pdb", str(source),
            "--write_pdbqt", str(out / "receptor.pdbqt"),
            "--write_pdb", str(out / "receptor.pdb"),
            *box,
        ]  # fmt: skip
        done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"mk_prepare_receptor.py failed:\n{done.stdout}\n{done.stderr}")
    return " ".join(
        ["--read_pdb clean.pdb --write_pdbqt receptor.pdbqt --write_pdb receptor.pdb", *box]
    )


# Crystal ligand ---------------------------------------------------------------


def crystal_ligand(
    pdb_text: str, sdf_text: str, chain_name: str, comp_id: str
) -> tuple[list[list[float]], str]:
    """Check the ModelServer SDF holds exactly the entry's ligand atoms; return its
    heavy-atom coordinates and residue number."""
    import gemmi
    from rdkit import Chem

    supplier = Chem.SDMolSupplier()
    supplier.SetData(sdf_text, sanitize=False, removeHs=False)
    records = [mol for mol in supplier if mol is not None]
    if len(records) != 1:
        raise SystemExit(f"{comp_id}: expected one ligand record, got {len(records)}")
    mol = records[0]
    heavy = [
        (atom.GetSymbol(), list(mol.GetConformer().GetAtomPosition(atom.GetIdx())))
        for atom in mol.GetAtoms()
        if atom.GetAtomicNum() > 1
    ]

    structure = gemmi.read_pdb_string(pdb_text)
    structure.merge_chain_parts()
    structure.remove_alternative_conformations()
    residues = [r for r in structure[0][chain_name] if r.name == comp_id]
    if len(residues) != 1:
        raise SystemExit(f"{comp_id} chain {chain_name}: expected one residue, got {len(residues)}")
    entry = [(a.element.name, a.pos.tolist()) for a in residues[0] if a.element.name != "H"]
    if len(entry) != len(heavy) or any(
        e[0] != h[0] or max(abs(p - q) for p, q in zip(e[1], h[1], strict=True)) > 1e-3
        for e, h in zip(sorted(entry), sorted(heavy), strict=True)
    ):
        raise SystemExit(f"the ModelServer {comp_id} atoms differ from the entry's HETATM records")
    return [xyz for _, xyz in heavy], str(residues[0].seqid.num)


def complete_molfile(sdf_text: str, title: str, properties: dict[str, str]) -> str:
    """The ModelServer record's connection table with a title, a 3D dimension code,
    the counts line's V2000 tag (which the ModelServer leaves out, so readers would
    take the pose for 2D) and our own properties instead of its per-request ones."""
    lines = sdf_text.split("$$$$")[0].splitlines()
    end = next(i for i, line in enumerate(lines) if line.startswith("M  END"))
    counts = lines[3].ljust(30)[:30] + "999 V2000"
    block = [title, "  oxhack            3D", "", counts, *lines[4 : end + 1]]
    for key, value in properties.items():
        block += [f"> <{key}>", value, ""]
    return "\n".join([*block, "$$$$"]) + "\n"


def control_smiles(comp_id: str, sdf_text: str) -> tuple[str, str]:
    """The ligand's stereo SMILES from the chemical component dictionary, checked to
    fit the crystal pose."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    url = CHEMCOMP_API.format(comp_id=comp_id)
    descriptor = fetch_json(url)["rcsb_chem_comp_descriptor"]
    smiles = descriptor.get("SMILES_stereo") or descriptor["SMILES"]
    crystal = Chem.MolFromMolBlock(sdf_text.split("$$$$")[0], sanitize=False)
    AllChem.AssignBondOrdersFromTemplate(
        Chem.MolFromSmiles(smiles), Chem.RemoveHs(crystal, sanitize=False)
    )
    return smiles, url


# One structure ----------------------------------------------------------------


def prepare(listing: dict[str, Any], prepared_on: str) -> dict[str, Any]:
    pdb_id, chain = listing["pdb_id"], listing["chain"]
    comp_id = listing["ligand"]["comp_id"]
    out = STRUCTURES_DIR / pdb_id
    out.mkdir(parents=True, exist_ok=True)

    entry_url = ENTRY_URL.format(pdb_id=pdb_id)
    entry_bytes = fetch(entry_url)
    entry_text = entry_bytes.decode()
    record = fetch_json(ENTRY_API.format(pdb_id=pdb_id))
    method = record["exptl"][0]["method"]
    resolution = float(record["rcsb_entry_info"]["resolution_combined"][0])
    if (method, round(resolution, 2)) != (listing["method"], round(listing["resolution"], 2)):
        raise SystemExit(
            f"{pdb_id}: RCSB says {method} at {resolution} angstroms; the listing says "
            f"{listing['method']} at {listing['resolution']}"
        )
    instance = fetch_json(INSTANCE_API.format(pdb_id=pdb_id, chain=chain))
    entity_id = instance["rcsb_polymer_entity_instance_container_identifiers"]["entity_id"]
    entity = fetch_json(ENTITY_API.format(pdb_id=pdb_id, entity=entity_id))
    uniprot = entity["rcsb_polymer_entity_container_identifiers"].get("uniprot_ids") or []
    if not uniprot:
        raise SystemExit(f"{pdb_id} chain {chain}: RCSB maps it to no UniProt accession")
    if len(uniprot) > 1:
        # e.g. 6O0K: a BCL2 construct with a BCL-XL loop. Recorded, not hidden.
        print(f"  note: {pdb_id} chain {chain} is a chimera of {', '.join(uniprot)}")

    ligand_url = LIGAND_URL.format(pdb_id=pdb_id, chain=chain, comp_id=comp_id)
    sdf_text = fetch(ligand_url).decode()
    coords, residue_number = crystal_ligand(entry_text, sdf_text, chain, comp_id)
    center = [round(sum(axis) / len(coords), 3) for axis in zip(*coords, strict=True)]
    smiles, smiles_url = control_smiles(comp_id, sdf_text)

    clean, changes = clean_receptor(entry_text, chain, center)
    meeko_args = meeko_receptor(clean, out, center)
    title = (
        f"{listing['ligand']['name']}, crystal pose from PDB {pdb_id} chain {chain}, "
        f"residue {comp_id} {residue_number}"
    )
    properties = {
        "comp_id": comp_id,
        "name": listing["ligand"]["name"],
        "pdb_id": pdb_id,
        "chain": chain,
        "residue_number": residue_number,
        "source": ligand_url,
    }
    (out / "crystal_ligand.sdf").write_text(complete_molfile(sdf_text, title, properties))

    meta = {
        "id": listing["id"],
        "pdb_id": pdb_id,
        "chain": chain,
        "uniprot": uniprot,
        "target_id": listing["target_id"],
        "symbol": listing["target_symbol"],
        "title": listing["title"],
        "method": method,
        "resolution": resolution,
        "ligand": {
            "comp_id": comp_id,
            "name": listing["ligand"]["name"],
            "candidate_id": listing["ligand"]["candidate_id"],
            "residue_number": residue_number,
            "heavy_atoms": len(coords),
        },
        "box_center": center,
        "box_size": [BOX_SIZE] * 3,
        "control_smiles": smiles,
        "receptor": {
            **changes,
            "meeko": f"mk_prepare_receptor.py {meeko_args}",
        },
        "sources": {
            "entry": entry_url,
            "entry_sha256": sha256(entry_bytes),
            "ligand": ligand_url,
            "control_smiles": smiles_url,
        },
        "prepared_on": prepared_on,
        "toolchain": toolchain(),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    listed = [round(c, 3) for c in listing["box"]["center"]]
    if max(abs(a - b) for a, b in zip(listed, center, strict=True)) > 0.01:
        print(f"  note: the listing's box centre {listed} differs from the computed {center}")
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("pdb_ids", nargs="*", help="Default: every listed structure.")
    args = parser.parse_args(argv)
    listings = json.loads(LISTING.read_text())["structures"]
    wanted = {p.upper() for p in args.pdb_ids}
    unknown = wanted - {s["pdb_id"] for s in listings}
    if unknown:
        raise SystemExit(f"not in {LISTING.name}: {', '.join(sorted(unknown))}")
    prepared_on = datetime.now(UTC).date().isoformat()
    versions = toolchain()
    for listing in listings:
        if wanted and listing["pdb_id"] not in wanted:
            continue
        meta = prepare(listing, prepared_on)
        receptor = meta["receptor"]
        print(
            f"{meta['id']}: box centre {meta['box_center']}, "
            f"{len(receptor['truncated_side_chains'])} side chains cut back, "
            f"{len(receptor['modified_to_parent'])} modified residues converted"
        )
    settings = {
        **SETTINGS,
        "engine_version": versions["vina"],
        "meeko_version": versions["meeko"],
        "rdkit_version": versions["rdkit"],
        "toolchain": versions,
    }
    (STRUCTURES_DIR / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
