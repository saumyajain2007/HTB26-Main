"""Prepare the result files of the fixture's precomputed docking jobs.

    uv run python scripts/prepare_docking_files.py

For every control in `fixtures/docking.json` with `"result_files": true`, this
downloads its structure from RCSB and writes `fixtures/docking_files/{job_id}/`:

- `receptor.pdb`: the docking chain's protein atoms. Waters, ligands, ions and
  other chains are removed; modified residues listed in MODRES (such as
  phosphotyrosine) are kept, and of alternate locations only the first.
- `crystal_ligand.sdf`: the co-crystal ligand in its crystal position, from the
  RCSB ModelServer (bond orders from the chemical component dictionary). Its
  atoms are checked against the entry's HETATM records.
- `poses.sdf`: the crystal ligand again, as pose 1, labelled as a fixture copy.
  No docking program runs here, so nothing in these files is a Vina result.
- `scores.json`: the fixture's made-up scores, marked `fixture: true`.
- `log.txt`: what was done, with the sources and the download's SHA-256.

Plain Python only: no RDKit, Vina or Meeko. Run it again after changing the
controls; the API hashes the files when it starts, so `DockJob.files` follows.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "oxhack_api" / "fixtures"
ENTRY_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"
LIGAND_URL = (
    "https://models.rcsb.org/v1/{pdb_id}/ligand"
    "?auth_asym_id={chain}&label_comp_id={comp_id}&encoding=sdf"
)
WATERS = {"HOH", "WAT", "DOD"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        body: bytes = response.read()
        return body


@dataclass(frozen=True)
class Atom:
    line: str

    @property
    def record(self) -> str:
        return self.line[:6].strip()

    @property
    def altloc(self) -> str:
        return self.line[16]

    @property
    def resname(self) -> str:
        return self.line[17:20].strip()

    @property
    def chain(self) -> str:
        return self.line[21]

    @property
    def resseq(self) -> str:
        return self.line[22:27].strip()

    @property
    def xyz(self) -> tuple[float, float, float]:
        return float(self.line[30:38]), float(self.line[38:46]), float(self.line[46:54])

    @property
    def element(self) -> str:
        return self.line[76:78].strip()


def parse_entry(pdb: str) -> tuple[list[Atom], set[str]]:
    """Atoms of the first model, and the residue names MODRES marks as modified."""
    atoms: list[Atom] = []
    modified: set[str] = set()
    for line in pdb.splitlines():
        if line.startswith("MODRES"):
            modified.add(line[12:15].strip())
        elif line.startswith(("ATOM  ", "HETATM")):
            atoms.append(Atom(line.ljust(80)))
        elif line.startswith("ENDMDL"):
            break
    return atoms, modified


def receptor_pdb(
    atoms: list[Atom], modified: set[str], chain: str, header: list[str]
) -> tuple[str, dict[str, int]]:
    """The chain's protein atoms as PDB text, and counts of what was left out."""
    kept: list[str] = []
    left_out: dict[str, int] = {}
    for atom in atoms:
        protein = atom.record == "ATOM" or atom.resname in modified
        if atom.chain != chain or not protein or atom.resname in WATERS:
            key = "waters" if atom.resname in WATERS else f"{atom.resname} chain {atom.chain}"
            left_out[key] = left_out.get(key, 0) + 1
            continue
        if atom.altloc not in (" ", "A"):
            left_out["alternate locations"] = left_out.get("alternate locations", 0) + 1
            continue
        kept.append((atom.line[:16] + " " + atom.line[17:]).rstrip())
    remarks = [f"REMARK 999 {text}".ljust(80).rstrip() for text in header]
    return "\n".join([*remarks, *kept, "TER", "END"]) + "\n", left_out


@dataclass(frozen=True)
class Molfile:
    """A V2000 connection table: the counts line through `M  END`."""

    title: str
    table: list[str]

    @property
    def atom_count(self) -> int:
        return int(self.table[0][:3])

    def atoms(self) -> list[tuple[str, tuple[float, float, float]]]:
        rows = self.table[1 : 1 + self.atom_count]
        return [(r[31:34].strip(), (float(r[:10]), float(r[10:20]), float(r[20:30]))) for r in rows]

    def sdf(self, title: str, properties: dict[str, str]) -> str:
        lines = [title, "  oxhack            3D", "", *self.table]
        for key, value in properties.items():
            lines += [f"> <{key}>", value, ""]
        return "\n".join([*lines, "$$$$"]) + "\n"


def parse_single_molfile(sdf: str) -> Molfile:
    records = [r for r in sdf.split("$$$$") if r.strip()]
    if len(records) != 1:
        raise SystemExit(f"expected one ligand record, got {len(records)}")
    lines = records[0].splitlines()
    end = next(i for i, line in enumerate(lines) if line.startswith("M  END"))
    counts = lines[3]
    if "V3000" in counts:
        raise SystemExit("the ligand is a V3000 molfile; only V2000 is handled")
    # The ModelServer leaves out the counts line's version tag; write a complete one.
    atoms, bonds = int(counts[:3]), int(counts[3:6])
    counts = f"{atoms:3d}{bonds:3d}  0  0  0  0  0  0  0  0999 V2000"
    return Molfile(title=lines[0].strip(), table=[counts, *lines[4 : end + 1]])


def check_ligand(molfile: Molfile, atoms: list[Atom], comp_id: str, chain: str) -> str:
    """Check the SDF holds exactly the entry's ligand atoms; return its residue number."""
    hetatms = [a for a in atoms if a.resname == comp_id and a.chain == chain]
    residues = {a.resseq for a in hetatms}
    if len(residues) != 1:
        raise SystemExit(f"{comp_id} chain {chain}: expected one residue, got {sorted(residues)}")
    if any(a.altloc not in (" ", "A") for a in hetatms):
        raise SystemExit(f"{comp_id} has alternate locations; choose one explicitly")
    expected = sorted((a.element.capitalize(), a.xyz) for a in hetatms)
    got = sorted(molfile.atoms())
    if len(expected) != len(got) or any(
        e[0] != g[0] or max(abs(p - q) for p, q in zip(e[1], g[1], strict=True)) > 1e-3
        for e, g in zip(expected, got, strict=True)
    ):
        raise SystemExit(f"the ModelServer {comp_id} atoms differ from the entry's HETATM records")
    return residues.pop()


def prepare(control: dict[str, object], structure: dict[str, object], date: str) -> None:
    job_id = str(control["id"])
    pdb_id = str(structure["pdb_id"])
    chain = str(structure["chain"])
    ligand = structure["ligand"]
    assert isinstance(ligand, dict)
    comp_id, ligand_name = str(ligand["comp_id"]), str(ligand["name"])
    if control["candidate_id"] != ligand["candidate_id"]:
        # Pose 1 is a copy of the crystal ligand, so it only stands in for that drug.
        raise SystemExit(f"{job_id} docks another drug than {structure['id']}'s crystal ligand")
    entry_url = ENTRY_URL.format(pdb_id=pdb_id)
    ligand_url = LIGAND_URL.format(pdb_id=pdb_id, chain=chain, comp_id=comp_id)

    entry = fetch(entry_url)
    atoms, modified = parse_entry(entry.decode())
    molfile = parse_single_molfile(fetch(ligand_url).decode())
    resseq = check_ligand(molfile, atoms, comp_id, chain)
    entry_chain = f"PDB {pdb_id} chain {chain}"
    where = f"{entry_chain}, residue {comp_id} {resseq}"

    kept_modified = sorted(modified & {a.resname for a in atoms if a.chain == chain})
    header = [
        f"Docking receptor: {entry_chain} ({structure['target_symbol']}).",
        "Protein atoms only, no hydrogens added. Of alternate locations, the first is kept.",
        f"Modified residues kept as HETATM: {', '.join(kept_modified) or 'none'}.",
        f"Source: {entry_url}, retrieved {date}.",
    ]
    receptor, left_out = receptor_pdb(atoms, modified, chain, header)

    crystal = molfile.sdf(
        f"{ligand_name}, crystal pose from {where}",
        {
            "comp_id": comp_id,
            "name": ligand_name,
            "pdb_id": pdb_id,
            "chain": chain,
            "residue_number": resseq,
            "source": ligand_url,
        },
    )
    poses = molfile.sdf(
        f"Pose 1: crystal pose of {ligand_name}, fixture copy, not a docking result",
        {
            "pose": "1",
            "fixture": "true",
            "note": (
                f"Fixture file. Pose 1 is the crystal ligand of {where}, copied unchanged. "
                "No docking program was run, so this is not a Vina result."
            ),
            "comp_id": comp_id,
            "candidate_id": str(control["candidate_id"]),
            "job_id": job_id,
        },
    )
    raw_scores = control["scores"]
    assert isinstance(raw_scores, list)
    scores = {
        "fixture": True,
        "note": (
            "Fixture result. No docking program was run: pose 1 is the crystal ligand and "
            "every score is a made-up placeholder, not a Vina score."
        ),
        "job_id": job_id,
        "structure_id": structure["id"],
        "candidate_id": control["candidate_id"],
        "scores": [{"pose": i, "score": s} for i, s in enumerate(raw_scores, 1)],
    }
    removed = ", ".join(f"{n} {what}" for what, n in sorted(left_out.items()))
    log = "\n".join(
        [
            "Fixture result. No docking program was run.",
            "",
            f"Job {job_id} ({control['kind']}): {ligand_name} ({control['candidate_id']}) "
            f"in {structure['id']}.",
            f"Prepared on {date} by api/scripts/prepare_docking_files.py from:",
            f"  {entry_url}",
            f"    sha256 {hashlib.sha256(entry).hexdigest()}",
            f"  {ligand_url}",
            "",
            f"receptor.pdb: chain {chain}, {receptor.count(chr(10) + 'ATOM')} ATOM and "
            f"{receptor.count(chr(10) + 'HETATM')} HETATM records ({', '.join(kept_modified)}).",
            f"  Left out: {removed}.",
            f"crystal_ligand.sdf: {comp_id} {resseq}, {molfile.atom_count} heavy atoms.",
            "poses.sdf: pose 1 is the crystal ligand, copied. It is not a Vina result.",
            "scores.json: made-up placeholder scores.",
            "",
        ]
    )

    out = FIXTURES / "docking_files" / job_id
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "receptor.pdb": receptor,
        "crystal_ligand.sdf": crystal,
        "poses.sdf": poses,
        "scores.json": json.dumps(scores, indent=2) + "\n",
        "log.txt": log,
    }
    for name, text in files.items():
        (out / name).write_text(text)
        print(f"{out.relative_to(FIXTURES)}/{name}: {len(text.encode())} bytes")


def main() -> int:
    structures = {
        s["id"]: s for s in json.loads((FIXTURES / "structures.json").read_text())["structures"]
    }
    docking = json.loads((FIXTURES / "docking.json").read_text())
    date = datetime.now(UTC).date().isoformat()
    for control in docking["controls"]:
        if control.get("result_files"):
            prepare(control, structures[control["structure_id"]], date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
