"""Resistance mutation records for a target, parsed from CARD variant notation.

A CARD protein-variant model names the substitutions that confer resistance, as ``S83L`` or
``Ser83Leu``. Two things about parsing them are easy to get wrong and are handled explicitly
rather than guessed at.

**Position, not substitution, is the unit of escape.** Ten substitutions at residue 83 is one
escape route that the organism has been seen to take ten ways; one substitution at each of ten
residues is ten routes. Counting substitutions conflates a single well-studied hotspot with a
genuinely plastic target, and the hotspot is the more common case in CARD. So the scorer counts
distinct positions and reports the concentration separately.

**A, G, C and T are both nucleotides and amino acids.** ``A2058G`` in 23S rRNA is a nucleotide
change; ``A2058G`` in a protein would be Ala→Gly. The notation cannot settle it, so the kind is
taken from the target's own molecule type and, where that is unknown, the record is marked
``ambiguous`` rather than assigned a kind. Guessing here would silently misclassify rRNA
targets, which are exactly the ones whose multi-copy constraint changes the band.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PROTEIN, NUCLEOTIDE, AMBIGUOUS = "protein", "nucleotide", "ambiguous"

AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")
NUCLEOTIDES = set("ACGTU")
SHARED = AMINO_ACIDS & NUCLEOTIDES          # A, C, G, T — unresolvable from notation alone

THREE_LETTER = {
    "ala": "A", "arg": "R", "asn": "N", "asp": "D", "cys": "C", "gln": "Q", "glu": "E",
    "gly": "G", "his": "H", "ile": "I", "leu": "L", "lys": "K", "met": "M", "phe": "F",
    "pro": "P", "ser": "S", "thr": "T", "trp": "W", "tyr": "Y", "val": "V",
}

_ONE = re.compile(r"^([A-Z])(\d+)([A-Z*]|del|ins|fs)$", re.IGNORECASE)
_THREE = re.compile(r"^([A-Za-z]{3})(\d+)([A-Za-z]{3}|\*)$")


class MutationParseError(ValueError):
    """The variant notation could not be read. Never a silently dropped mutation."""


@dataclass(frozen=True)
class Mutation:
    """One documented resistance substitution."""

    raw: str
    position: int
    wild_type: str
    variant: str
    kind: str                     # protein | nucleotide | ambiguous
    mechanism: str | None = None
    drug_classes: tuple = ()
    source: str | None = None     # the CARD model or accession it came from

    def as_dict(self) -> dict:
        return {"raw": self.raw, "position": self.position, "wild_type": self.wild_type,
                "variant": self.variant, "kind": self.kind, "mechanism": self.mechanism,
                "drug_classes": list(self.drug_classes), "source": self.source}


def parse_mutation(text: str, *, molecule: str | None = None, mechanism: str | None = None,
                   drug_classes=(), source: str | None = None) -> Mutation:
    """Read one variant string. ``molecule`` is ``protein``/``nucleotide`` when known.

    The kind is resolved from the molecule type, or from letters that can only be one thing.
    When neither settles it, the kind is ``ambiguous`` and the caller is told, because an
    rRNA change misread as a protein change loses the multi-copy constraint.
    """
    raw = (text or "").strip()
    if not raw:
        raise MutationParseError("empty variant notation")

    match = _THREE.match(raw)
    if match and match.group(1).lower() in THREE_LETTER:
        wild = THREE_LETTER[match.group(1).lower()]
        position = int(match.group(2))
        third = match.group(3)
        variant = "*" if third == "*" else THREE_LETTER.get(third.lower(), third.upper())
        kind = PROTEIN          # three-letter codes are amino acids by construction
    else:
        match = _ONE.match(raw)
        if not match:
            raise MutationParseError(f"{raw!r} is not readable variant notation")
        wild = match.group(1).upper()
        position = int(match.group(2))
        variant = match.group(3).upper()
        kind = _resolve_kind(wild, variant, molecule)

    if position <= 0:
        raise MutationParseError(f"{raw!r} has a non-positive position")
    return Mutation(raw=raw, position=position, wild_type=wild, variant=variant, kind=kind,
                    mechanism=mechanism, drug_classes=tuple(drug_classes), source=source)


def _resolve_kind(wild: str, variant: str, molecule: str | None) -> str:
    if molecule in (PROTEIN, NUCLEOTIDE):
        return molecule
    letters = {wild, variant} - {"*", "DEL", "INS", "FS"}
    if letters - NUCLEOTIDES:
        return PROTEIN          # contains a letter no nucleotide uses
    if letters - AMINO_ACIDS:
        return NUCLEOTIDE
    return AMBIGUOUS            # only A/C/G/T/U: notation cannot settle it


@dataclass
class TargetRecord:
    """Everything known about one drug target's documented resistance mutations."""

    target_aro_id: str
    name: str
    molecule: str | None = None          # protein | nucleotide | None when unknown
    copy_number: int | None = None       # gene copies per genome; None when unknown
    mutations: list = field(default_factory=list)
    non_mutational_mechanisms: tuple = ()   # replacement, protection, overexpression
    sources: tuple = ()

    @property
    def multi_copy(self) -> bool:
        return self.copy_number is not None and self.copy_number > 1

    def add(self, text: str, **kw) -> Mutation:
        mutation = parse_mutation(text, molecule=self.molecule, **kw)
        self.mutations.append(mutation)
        return mutation


def from_rows(rows, *, target_aro_id: str, name: str, molecule: str | None = None,
              copy_number: int | None = None) -> TargetRecord:
    """Build a record from table rows, keeping unreadable notation visible.

    Returns the record and the rejected rows. A mutation that cannot be parsed is reported,
    never dropped: a dropped mutation lowers the escape-route count and therefore the band,
    which is the one direction a parsing bug must not be allowed to move the answer.
    """
    record = TargetRecord(target_aro_id=target_aro_id, name=name, molecule=molecule,
                          copy_number=copy_number)
    rejected = []
    seen_sources = []
    for row in rows:
        text = row.get("variant") or row.get("snp") or ""
        try:
            record.add(text, mechanism=row.get("mechanism"),
                       drug_classes=tuple(row.get("drug_classes", ())),
                       source=row.get("source"))
        except MutationParseError as exc:
            rejected.append({"row": dict(row), "reason": str(exc)})
            continue
        if row.get("source"):
            seen_sources.append(row["source"])
    record.sources = tuple(sorted(set(seen_sources)))
    return record, rejected
