"""WS2 input handling: parse the three input types into tokens for resolution.

Nothing is dropped silently. Every string read is kept in ``Parsed.requested`` exactly as
it was typed, and anything not turned into a token is recorded in ``Parsed.rejected`` with
a reason, so the profile can report it under ``unresolved_inputs``.

The three input kinds use the contract's own names (docs/contracts.md):
  gene_list       parse_gene_text    names or ARO IDs, optionally with a mutation
  species_preset  parse_preset       a species and its typical resistance profile
  amrfinderplus   parse_amrfinder    AMRFinderPlus output for an isolate genome
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

GENE_LIST = "gene_list"
SPECIES_PRESET = "species_preset"
AMRFINDERPLUS = "amrfinderplus"


class InputError(Exception):
    """The input cannot be used. The message names the problem entries."""


@dataclass
class Token:
    """One candidate determinant, before it is resolved against CARD."""

    raw: str                      # exactly what the user or the tool reported
    lookup: str                   # the name to resolve (without any mutation)
    origin: str                   # e.g. "line 3", "preset Acinetobacter baumannii"
    method: str                   # user_name | preset | amrfinder:<METHOD>
    identity: float | None = None
    coverage: float | None = None
    mutation: str | None = None
    amrfinder_class: str = ""


@dataclass
class Rejected:
    """A string that was read but will not become a gene row, and why."""

    raw: str
    origin: str
    reason: str


@dataclass
class Species:
    name: str
    ncbi_taxid: int | None = None

    def as_dict(self) -> dict:
        return {"name": self.name, "ncbi_taxid": self.ncbi_taxid}


@dataclass
class Parsed:
    kind: str                     # gene_list | species_preset | amrfinderplus
    requested: list = field(default_factory=list)   # every string read, as typed
    tokens: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    species: Species | None = None
    preset_status: str | None = None
    notes: list = field(default_factory=list)


# A point mutation as CARD and AMRFinderPlus write them: S83L, G79C, A2059G, and the
# insertion/deletion forms CARD also carries.
_MUTATION = re.compile(r"^[A-Za-z*]\d+[A-Za-z*]+$|^[A-Za-z]?\d+(?:ins|del|dup)[A-Za-z*]*$",
                       re.IGNORECASE)
# Items are separated by commas, semicolons or newlines. Spaces are handled per item,
# because one item may be a gene and its mutation, as in "gyrA S84L".
_ITEM_SPLIT = re.compile(r"[,;\n]+")


def _split_item(item: str) -> list:
    """Split one item into (name, mutation) pairs.

    ``gyrA S84L`` is one determinant with a mutation. ``mecA gyrA`` is two determinants.
    """
    parts = item.split()
    if len(parts) == 2 and _MUTATION.match(parts[1]):
        return [(item, parts[0], parts[1])]
    return [(p, p, None) for p in parts]


def parse_gene_text(text: str, species: Species | None = None) -> Parsed:
    """Input (a): gene names or ARO IDs, optionally each with a point mutation.

    Items are separated by commas, semicolons or lines; ``#`` starts a comment. An item
    of the form ``gyrA S84L`` is read as that gene carrying that mutation. A repeated
    entry is reported, not counted twice.
    """
    parsed = Parsed(kind=GENE_LIST, species=species)
    seen: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        for item in _ITEM_SPLIT.split(body):
            item = item.strip()
            if not item:
                continue
            for raw, name, mutation in _split_item(item):
                origin = f"line {lineno}"
                parsed.requested.append(raw)
                key = raw.lower()
                if key in seen:
                    parsed.rejected.append(
                        Rejected(raw, origin, f"duplicate of '{seen[key]}' earlier in the input"))
                    continue
                seen[key] = raw
                parsed.tokens.append(Token(raw=raw, lookup=name, origin=origin,
                                           method="user_name", mutation=mutation))
    return parsed


def parse_preset(species: str, presets_path) -> Parsed:
    """Input (b): a species preset with its typical resistance profile.

    The shipped lists are drafts until they are derived from CARD and cited. The status
    travels with the tokens so every profile built from a preset says so.
    """
    path = Path(presets_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"preset file {path} does not exist") from exc
    except ValueError as exc:
        raise InputError(f"preset file {path} is not valid JSON: {exc}") from exc

    presets = data.get("presets", {})
    wanted = species.strip().lower()
    key = next((k for k in presets if k.lower() == wanted), None)
    if key is None:
        aliases = {a.lower(): k for k, v in presets.items() for a in v.get("aliases", [])}
        key = aliases.get(wanted)
    if key is None:
        available = ", ".join(sorted(presets)) or "none"
        raise InputError(f"unknown species preset {species!r}. Available: {available}")

    entry = presets[key]
    genes = entry.get("genes", [])
    if not genes:
        raise InputError(f"preset {key!r} lists no genes")

    taxid = entry.get("ncbi_taxid")
    parsed = Parsed(kind=SPECIES_PRESET,
                    species=Species(key, int(taxid) if taxid is not None else None),
                    preset_status=entry.get("status", "unspecified"))
    if entry.get("note"):
        parsed.notes.append(entry["note"])

    seen: dict[str, str] = {}
    origin = f"preset {key}"
    for gene in genes:
        name = str(gene).strip()
        if not name:
            continue
        parsed.requested.append(name)
        if name.lower() in seen:
            parsed.rejected.append(
                Rejected(name, origin, f"listed twice in preset {key!r}"))
            continue
        seen[name.lower()] = name
        lookup, mutation = name, None
        split = _split_item(name)
        if len(split) == 1:
            _, lookup, mutation = split[0]
        parsed.tokens.append(Token(raw=name, lookup=lookup, origin=origin,
                                   method="preset", mutation=mutation))
    return parsed


# Suffixes NCBI Pathogen Detection appends to an AMRFinderPlus symbol: "gyrA_S83L=POINT",
# "blaOXA=MISTRANSLATION", "mecA=PARTIAL". No suffix means a complete match.
_NCBI_POINT = re.compile(r"^(?P<gene>.+)_(?P<mutation>[A-Za-z*]\d+[A-Za-z*]+(?:[A-Za-z]+\d*)?)$")


def parse_ncbi_genotypes(text: str, species: Species | None = None,
                         exclude_methods: tuple = ()) -> Parsed:
    """Input (c'): the ``AMR_genotypes_core`` string NCBI Pathogen Detection holds per isolate.

    ``"gyrA_S83Y=POINT,blaSHV-12,mecA=PARTIAL"`` becomes one token each. A POINT symbol is split
    into the gene and its mutation, the way ``parse_amrfinder`` splits a ``POINT`` row. Methods in
    ``exclude_methods`` (for example ``PARTIAL``) are rejected with a reason rather than dropped.
    """
    parsed = Parsed(kind=AMRFINDERPLUS, species=species)
    seen: set = set()
    for item in (x.strip() for x in text.split(",")):
        if not item or item.upper() == "NULL":
            continue
        raw = item
        symbol, _, suffix = item.partition("=")
        method = (suffix or "EXACT").upper()
        parsed.requested.append(raw)
        if raw in seen:
            parsed.rejected.append(Rejected(raw, "genotype string", "listed twice"))
            continue
        seen.add(raw)
        if method in exclude_methods:
            parsed.rejected.append(Rejected(raw, "genotype string",
                                            f"method {method} excluded by the caller"))
            continue
        lookup, mutation = symbol, None
        if method.startswith("POINT"):
            m = _NCBI_POINT.match(symbol)
            if m:
                lookup, mutation = m.group("gene"), m.group("mutation")
        parsed.tokens.append(Token(raw=raw, lookup=lookup, origin="genotype string",
                                   method=f"amrfinder:{method}", mutation=mutation))
    return parsed


def _first_present(header, names):
    return next((n for n in names if n in header), None)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_amrfinder(path, include_plus: bool = False, species: Species | None = None) -> Parsed:
    """Input (c), optional: AMRFinderPlus output for an isolate genome.

    Both header generations are accepted: the current 'Gene symbol' and the older
    'Element symbol'. Only ``Element type`` AMR rows become gene rows, and by default only
    ``Scope`` core rows, since plus-scope rows include virulence and stress genes. A POINT
    method symbol such as ``gyrA_S83L`` is split into the gene to resolve and the mutation.

    Every symbol in the file goes into ``requested``, so a row that is skipped is still
    reported rather than disappearing.
    """
    path = Path(path)
    parsed = Parsed(kind=AMRFINDERPLUS, species=species)
    try:
        handle = path.open(newline="", encoding="utf-8")
    except FileNotFoundError as exc:
        raise InputError(f"{path} does not exist") from exc

    with handle as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        header = reader.fieldnames or []
        sym_col = _first_present(header, ["Gene symbol", "Element symbol"])
        if sym_col is None:
            raise InputError(f"{path.name} has no 'Gene symbol' or 'Element symbol' column; "
                             "it does not look like AMRFinderPlus output")
        type_col = _first_present(header, ["Element type"])
        scope_col = _first_present(header, ["Scope"])
        method_col = _first_present(header, ["Method"])
        id_col = _first_present(header, ["% Identity to reference sequence"])
        cov_col = _first_present(header, ["% Coverage of reference sequence"])
        class_col = _first_present(header, ["Class"])

        for i, row in enumerate(reader, start=2):  # line 1 is the header
            origin = f"{path.name} line {i}"
            sym = (row.get(sym_col) or "").strip()
            if not sym:
                parsed.rejected.append(Rejected("", origin, "the row has no gene symbol"))
                continue
            parsed.requested.append(sym)
            etype = (row.get(type_col) or "").strip() if type_col else "AMR"
            if etype.upper() != "AMR":
                parsed.rejected.append(Rejected(
                    sym, origin, f"element type {etype or 'blank'} is not AMR, so it is not a "
                                 "resistance determinant"))
                continue
            scope = (row.get(scope_col) or "").strip() if scope_col else "core"
            if scope.lower() != "core" and not include_plus:
                parsed.rejected.append(Rejected(
                    sym, origin, f"scope '{scope}' is not core; pass --include-plus to profile it"))
                continue
            method = (row.get(method_col) or "").strip().upper() if method_col else "UNKNOWN"
            lookup, mutation = sym, None
            if method.startswith("POINT") and "_" in sym:
                lookup, mutation = sym.rsplit("_", 1)
            parsed.tokens.append(Token(
                raw=sym, lookup=lookup, origin=origin,
                method=f"amrfinder:{method or 'UNKNOWN'}",
                identity=_num(row.get(id_col)) if id_col else None,
                coverage=_num(row.get(cov_col)) if cov_col else None,
                mutation=mutation,
                amrfinder_class=(row.get(class_col) or "").strip() if class_col else "",
            ))
    return parsed
