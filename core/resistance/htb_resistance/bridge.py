"""Resolve AMRFinderPlus-style symbols against CARD where the plain resolver gives up.

``Reference.resolve`` matches a name exactly, case-insensitively, or with a leading ``bla``
removed. Real AMRFinderPlus output uses spellings that fail all three: ``mph(A)`` for CARD's
``mphA``, ``aadA1`` listed inside a multi-name synonym, and point mutations such as
``gyrA_S83L`` that CARD holds only under a species-specific variant model
("Staphylococcus aureus gyrA conferring resistance to fluoroquinolones").

This bridge adds three steps, all mechanical, none hand-curated, and each recorded in the
resolution's ``how`` so a profile never presents a guess as an exact match:

  normalised_name           same letters and digits, ignoring case and punctuation, after
                            splitting CARD's multi-name synonyms ("aadA, aadA1, aad(3'')(9)")
  species_variant_model     a point mutation resolved to the CARD variant or knockout model
                            for that gene *in the isolate's own species*
  homolog_species_model     as above, but from a named related species, used only when CARD
                            holds no model for the isolate's species (K. pneumoniae gyrA and
                            parC use the E. coli models)

Nothing is guessed when a step is ambiguous: several candidates are reported as ambiguous with
the list, never picked. A bare allele-family symbol such as ``blaTEM`` or ``blaOXA`` names no
single CARD determinant and stays unresolved.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace

from .reference import Reference, Resolution

NORMALISED = "normalised_name"
SPECIES_MODEL = "species_variant_model"
HOMOLOG_MODEL = "homolog_species_model"
# `how` values that mean "matched by a rule we added", for the profile's caveat.
BRIDGED = (NORMALISED, SPECIES_MODEL, HOMOLOG_MODEL)

# CARD holds no gyrA/parC model for these species, so the named related species is used.
# The fluoroquinolone-resistance mutations sit in the same conserved quinolone-resistance
# determining regions, but this is a homology assumption and the profile says so.
HOMOLOG_SPECIES = {"klebsiella pneumoniae": ("escherichia coli",)}

_SPLIT = re.compile(r"\s*[,;/]\s*")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _key(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower())


class Bridge:
    """A resolver built once per Reference."""

    def __init__(self, reference: Reference):
        self.reference = reference
        self._norm: dict[str, set[str]] = defaultdict(set)
        for entry in reference.entries.values():
            for name in entry.names:
                for piece in (name, *_SPLIT.split(name)):
                    if piece.strip():
                        self._norm[_key(piece)].add(entry.aro)

    # ------------------------------------------------------------------ public

    def resolve(self, symbol: str, species: str | None = None,
                mutation: str | None = None) -> Resolution:
        """The plain resolver first, then the bridge steps. Unchanged results stay unchanged."""
        if mutation and species:
            found = self._variant_model(symbol, species, mutation)
            if found is not None:
                return found
        res = self.reference.resolve(symbol)
        if res.status == "resolved":
            return res
        found = self._normalised(symbol)
        return found if found is not None else res

    def resolver_for(self, species: str | None):
        """A ``resolver(token)`` for ``build_profile``, bound to the isolate's species."""
        return lambda token: self.resolve(token.lookup, species, token.mutation)

    # ------------------------------------------------------------------ steps

    def _pick(self, aros, how: str, token: str) -> Resolution | None:
        if len(aros) == 1:
            return Resolution("resolved", entry=self.reference.entries[next(iter(aros))], how=how)
        if len(aros) > 1:
            names = tuple(sorted(f"{self.reference.entries[a].short_name} ({a})" for a in aros))
            return Resolution("ambiguous", candidates=names,
                              reason=f"'{token}' matches {len(aros)} CARD determinants")
        return None

    def _normalised(self, symbol: str) -> Resolution | None:
        key = _key(symbol)
        hits = self._norm.get(key)
        if not hits and key.startswith("bla") and len(key) > 3:
            hits = self._norm.get(key[3:])
        return self._pick(hits, NORMALISED, symbol) if hits else None

    def _models_for(self, gene: str, species: str) -> set[str]:
        """Entries with a model named "<species> <gene> ..." (case-insensitive)."""
        pattern = re.compile(rf"^{re.escape(species.lower())}\s+{re.escape(gene.lower())}\b")
        return {e.aro for e in self.reference.entries.values()
                if any(pattern.match(n.lower()) for n in e.names)}

    def _variant_model(self, gene: str, species: str, mutation: str) -> Resolution | None:
        for how, name in [(SPECIES_MODEL, species.lower()),
                          *((HOMOLOG_MODEL, h) for h in HOMOLOG_SPECIES.get(species.lower(), ()))]:
            cands = self._models_for(gene, name)
            if not cands:
                continue
            listing = {a for a in cands
                       if any(v.mutation == mutation for v in self.reference.entries[a].variants)}
            chosen = listing or cands
            res = self._pick(chosen, how, f"{gene} {mutation}")
            if res is not None and res.status == "resolved" and how == HOMOLOG_MODEL:
                res = replace(res, how=f"{HOMOLOG_MODEL}:{name}")
            return res
        return None
