"""The CARD reference that typed gene names, ARO IDs and preset entries resolve against.

The reference is a release written by ``python -m htb_resistance build`` (card.py, WS1).
This module only reads that release's tables, so profiling never re-parses the raw CARD
downloads and never touches the network.

Term typing is delegated to :mod:`typecheck`, which decides what an ARO id *is* from
``is_a`` ancestry and CARD's categories. That matters: a determinant must descend from
ARO:3000000, while drug classes have to be tested by the Drug Class category rather than
by ancestry, because three of CARD's class terms sit outside ARO:1000003
(see docs/ontology-check.md). Keeping one checker avoids a second, divergent opinion.

Resolution order for one token:
  1. ARO ID (ARO:0000000, format checked, must be a determinant in this release)
  2. exact match on a gene's ARO name, CARD short name, model name or EXACT synonym
  3. the same names, case-insensitively
  4. the same names again with a leading "bla" removed (blaCTX-M-15 -> CTX-M-15)

Anything else is unknown. A name matching several determinants is reported ambiguous with
the candidates listed; it is never picked silently.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from .card import CardError, read_table, verify_release
from .typecheck import Ontology, check_term

SUPPLEMENT_PATH = Path(__file__).with_name("supplement.json")

CLASS_DRUG = "Drug Class"
CLASS_MECHANISM = "Resistance Mechanism"
CLASS_FAMILY = "AMR Gene Family"

# Only EXACT synonyms are used as names: RELATED and BROAD synonyms in the ARO are too
# loose to match a typed gene name on.
EXACT_SYNONYM_SCOPE = "EXACT"

_ARO_LIKE = re.compile(r"^ARO(:|\d)", re.IGNORECASE)
_ARO_ID = re.compile(r"^ARO:\d{7}$")


@dataclass(frozen=True)
class Term:
    """An ARO term as the contract carries it: join on the id, never the name."""

    aro_id: str
    name: str

    def as_dict(self) -> dict:
        return {"aro_id": self.aro_id, "name": self.name}


@dataclass(frozen=True)
class Variant:
    mutation: str
    param_type: str | None

    def as_dict(self) -> dict:
        return {"mutation": self.mutation, "param_type": self.param_type}


@dataclass(frozen=True)
class Curated:
    """A drug class added from the curated supplement, which CARD's release does not link to the gene."""

    id: str
    drug_class: Term
    reason: str
    citations: tuple             # tuple[dict], each with a PubMed id


@dataclass(frozen=True)
class Entry:
    """One resistance determinant, as the reference holds it."""

    aro: str
    name: str                     # the ARO term name
    short_name: str               # CARD short name, for display
    model_type: str
    model_ids: tuple
    drug_classes: tuple           # tuple[Term]
    mechanisms: tuple             # tuple[Term]
    gene_families: tuple          # tuple[Term]
    variants: tuple               # tuple[Variant], CARD's known resistance mutations
    names: tuple                  # every string this entry can be looked up by
    curated: tuple = ()           # tuple[Curated]: classes the supplement adds, none CARD already has


@dataclass(frozen=True)
class Resolution:
    status: str                  # resolved | unknown | ambiguous | malformed
    entry: Entry | None = None
    how: str = ""                # aro_id | exact | case_insensitive | bla_prefix_stripped
    candidates: tuple = ()
    reason: str = ""


class Reference:
    def __init__(self, entries, release: str, problems=(), supplement_release: str | None = None):
        self.release = release               # contract form, e.g. "card-4.0.2"
        self.supplement_release = supplement_release   # e.g. "curated_supplement-1"; None when not applied
        self.entries = {e.aro: e for e in entries}
        self.problems = tuple(problems)      # terms dropped because they were mistyped
        self._exact = defaultdict(set)
        self._lower = defaultdict(set)
        for e in entries:
            for name in e.names:
                self._exact[name].add(e.aro)
                self._lower[name.lower()].add(e.aro)

    # -------------------------------------------------------------------- loading

    @classmethod
    def from_release(cls, release_dir, supplement: Path | str | None = SUPPLEMENT_PATH) -> "Reference":
        """Load a release directory written by ``build``.

        `supplement` is the curated file of drug classes that CARD's download omits but that a
        cited source supports (supplement.json); None turns it off. A stale or uncited entry stops
        the load. It is never skipped.

        A release whose tables no longer match its manifest is refused, so a profile is
        never built from data that has drifted from what was recorded.
        """
        release_dir = Path(release_dir)
        if not (release_dir / "manifest.json").exists():
            raise ValueError(f"{release_dir} is not a CARD release (no manifest.json). "
                             "Build one with: python -m htb_resistance build")
        problems = verify_release(release_dir)
        if problems:
            raise ValueError(f"{release_dir} does not match its manifest "
                             f"({'; '.join(problems)}). Rebuild it.")
        manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
        version = str(manifest.get("card_data_version") or release_dir.name)
        release = f"card-{version}"          # the contract's source-version form

        onto = Ontology(release_dir / "tables")
        terms = onto.terms
        synonyms: dict[str, set] = defaultdict(set)
        for r in read_table(release_dir, "aro_synonyms"):
            if r["scope"] == EXACT_SYNONYM_SCOPE:
                synonyms[r["aro_accession"]].add(r["synonym"])

        variants: dict[str, set] = defaultdict(set)
        for r in read_table(release_dir, "model_variants"):
            variants[r["aro_accession"]].add((r["mutation"], r["param_type"]))

        # Candidate determinants are the ARO accessions CARD holds a detection model for.
        by_gene: dict[str, dict] = defaultdict(
            lambda: {"models": [], CLASS_DRUG: {}, CLASS_MECHANISM: {}, CLASS_FAMILY: {}})
        for model in read_table(release_dir, "models"):
            by_gene[model["aro_accession"]]["models"].append(model)

        mistyped: list[str] = []
        expected_kind = {CLASS_DRUG: "drug_class", CLASS_MECHANISM: "mechanism"}
        for link in read_table(release_dir, "model_categories"):
            gene = by_gene.get(link["aro_accession"])  # .get: never invent a gene from a link
            group = link["category_class"]
            if gene is None or group not in gene:
                continue
            acc = link["category_aro_accession"]
            # The ERRATA lesson: confirm the id is the kind of thing this field means.
            if group in expected_kind:
                problem = check_term(onto, acc, expected_kind[group])
                if problem:
                    mistyped.append(f"{group} link on {link['aro_accession']}: {problem}")
                    continue
            gene[group][acc] = terms[acc]["name"] if acc in terms else acc

        entries = []
        for acc in sorted(by_gene):
            term = terms.get(acc, {})
            problem = check_term(onto, acc, "determinant")
            if problem:
                mistyped.append(f"gene {problem}")
                continue
            gene = by_gene[acc]
            models = gene["models"]
            short = (term.get("short_name")
                     or next((m["short_name"] for m in models if m["short_name"]), "")
                     or term.get("name", acc))
            model_types = _unique(m["model_type"] for m in models)
            entries.append(Entry(
                aro=acc,
                name=term.get("name", short),
                short_name=short,
                model_type=model_types[0] if len(model_types) == 1 else ", ".join(model_types),
                model_ids=tuple(_unique(m["model_id"] for m in models)),
                drug_classes=_terms(gene[CLASS_DRUG]),
                mechanisms=_terms(gene[CLASS_MECHANISM]),
                gene_families=_terms(gene[CLASS_FAMILY]),
                variants=tuple(sorted((Variant(m, p) for m, p in variants.get(acc, ())),
                                      key=lambda v: v.mutation)),
                names=tuple(_unique([
                    short,
                    term.get("name", ""),
                    *(m["name"] for m in models),
                    *(m["short_name"] for m in models),
                    *sorted(synonyms.get(acc, ())),
                ])),
            ))
        supplement_release = None
        if supplement:
            data, entries = _apply_supplement(Path(supplement), entries, onto, terms, version)
            supplement_release = data["release"] if any(e.curated for e in entries) else None
        return cls(entries, release=release, problems=mistyped, supplement_release=supplement_release)

    # -------------------------------------------------------------------- resolution

    def _pick(self, hits, how: str, token: str):
        if len(hits) == 1:
            return Resolution("resolved", entry=self.entries[next(iter(hits))], how=how)
        if len(hits) > 1:
            candidates = tuple(sorted(f"{self.entries[a].short_name} ({a})" for a in hits))
            return Resolution("ambiguous", candidates=candidates,
                              reason=f"'{token}' matches {len(hits)} CARD determinants")
        return None

    def _by_name(self, name: str):
        return (self._pick(self._exact.get(name, set()), "exact", name)
                or self._pick(self._lower.get(name.lower(), set()), "case_insensitive", name))

    def _resolve_aro(self, token: str) -> Resolution:
        norm = "ARO:" + token[3:].lstrip(":")
        if not _ARO_ID.match(norm):
            return Resolution(
                "malformed",
                reason=f"'{token}' is not a valid ARO ID (expected ARO:0000000, seven digits)")
        entry = self.entries.get(norm)
        if entry is None:
            return Resolution("unknown",
                              reason=f"{norm} is not a CARD determinant with a detection model "
                                     f"in release {self.release}")
        return Resolution("resolved", entry=entry, how="aro_id")

    def resolve(self, token: str) -> Resolution:
        t = token.strip()
        if _ARO_LIKE.match(t):
            return self._resolve_aro(t)
        found = self._by_name(t)
        if found:
            return found
        if t.lower().startswith("bla") and len(t) > 3:
            found = self._by_name(t[3:])
            if found:
                return replace(found, how="bla_prefix_stripped")
        return Resolution(
            "unknown", reason="no CARD term or synonym matches this name")


def _apply_supplement(path: Path, entries: list, onto: Ontology, terms: dict, version: str) -> tuple[dict, list]:
    """Check the curated supplement against this CARD release and attach its additions to entries.

    Each addition needs a reason and a citation with a PubMed id, must name determinants that exist
    in the release, and must name a real Drug Class term under its true name. A class CARD already
    links to a gene is skipped for that gene, so an entry CARD later catches up with does nothing.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    by_aro = {e.aro: e for e in entries}
    added: dict[str, list] = defaultdict(list)
    for add in data["additions"]:
        where = f"supplement {add.get('id', '?')}"
        cites = add.get("citations") or []
        if not cites or not all(str(c.get("pmid", "")).isdigit() and c.get("citation") for c in cites):
            raise CardError(f"{where}: every added class needs at least one citation with a PubMed id")
        if not add.get("reason"):
            raise CardError(f"{where}: no reason given")
        cls = add["drug_class"]
        problem = check_term(onto, cls["aro_id"], "drug_class")
        if problem or terms[cls["aro_id"]]["name"] != cls["name"]:
            raise CardError(f"{where}: {cls['aro_id']} is not the Drug Class {cls['name']!r} in release {version}"
                            + (f" ({problem})" if problem else ""))
        for model in add["models"]:
            entry = by_aro.get(model)
            if entry is None:
                raise CardError(f"{where}: {model} is not a CARD determinant in release {version}")
            if cls["aro_id"] not in {t.aro_id for t in entry.drug_classes}:
                added[model].append(Curated(add["id"], Term(cls["aro_id"], cls["name"]), add["reason"], tuple(cites)))
    return data, [replace(e, curated=tuple(added[e.aro])) if e.aro in added else e for e in entries]


def latest_release(data_dir) -> Path:
    """The newest release under ``data_dir/releases``, by version number."""
    root = Path(data_dir) / "releases"
    found = [m.parent for m in root.glob("*/manifest.json")] if root.is_dir() else []
    if not found:
        raise ValueError(f"no CARD release under {root}. "
                         "Build one with: python -m htb_resistance build")

    def version_key(path: Path) -> tuple:
        return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", path.name))

    return max(found, key=version_key)


def _terms(mapping: dict) -> tuple:
    return tuple(Term(acc, name) for acc, name in sorted(mapping.items(), key=lambda kv: kv[1]))


def _unique(values) -> list:
    out: list = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out
