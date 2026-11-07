"""Map resolved resistance determinants to a ResistanceProfile (issue #16).

Input is a list of determinants already resolved to CARD detection models, each with the text
the user typed and any point mutations they named. Turning typed names, species presets or
AMRFinderPlus output into determinants is input handling (#15). Output is the frozen
ResistanceProfile contract (docs/contracts.md).

Everything comes from the CARD tables, so a profile says what CARD records and nothing more:

    mechanisms        the model's Resistance Mechanism categories
    defeated classes  the model's Drug Class categories (class level; CARD also records some
                      drug-level links, which the evasion rule in #23 will use)
    variants          the named mutations that CARD lists for the model
    affected target   the sensitive target the resistant form derives from, when CARD has one

Anything that cannot be turned into a gene row is reported in ``unresolved_inputs`` with a
reason. It is never dropped.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .card import read_table

CONTRACT_VERSION = "1"
VARIANT_MODELS = {"protein variant model", "rRNA gene variant model"}
CONFIDENCE = {
    "gene_list": ("low", "Gene presence was asserted by the user. Expression and copy number were not assessed."),
    "species_preset": ("low", "The genes are typical of the species, not observed in an isolate."),
    "amrfinderplus": ("medium", "Genes were detected in an isolate genome by AMRFinderPlus. Expression and copy "
                                "number were not assessed."),
}


@dataclass(frozen=True)
class Determinant:
    aro_id: str
    text: str  # what the user typed; reported back if the determinant cannot be used
    mutations: tuple[str, ...] = ()


class CardProfiler:
    """The CARD tables a profile needs, loaded once."""

    def __init__(self, release: Path | str):
        release = Path(release)
        self.release = release
        self.version = self._version(release)
        self.terms = {r["aro_accession"]: r for r in read_table(release, "aro_terms")}
        self.models = {r["aro_accession"]: r for r in read_table(release, "models")}
        self._parents, self._children = defaultdict(set), defaultdict(set)
        self._derives, self._targets = defaultdict(set), set()
        for r in read_table(release, "aro_relations"):
            if r["relation"] == "is_a":
                self._parents[r["subject"]].add(r["object"])
                self._children[r["object"]].add(r["subject"])
            elif r["relation"] == "derives_from":
                self._derives[r["subject"]].add(r["object"])
            elif r["relation"] == "targeted_by_antibiotic":
                self._targets.add(r["subject"])
        self.mechanisms, self.classes = defaultdict(set), defaultdict(set)
        for r in read_table(release, "model_categories"):
            if r["category_class"] == "Resistance Mechanism":
                self.mechanisms[r["aro_accession"]].add(r["category_aro_accession"])
            elif r["category_class"] == "Drug Class":
                self.classes[r["aro_accession"]].add(r["category_aro_accession"])
        self.variants = defaultdict(list)
        for r in read_table(release, "model_variants"):
            self.variants[r["aro_accession"]].append((r["mutation"], r["param_type"]))

    @staticmethod
    def _version(release: Path) -> str:
        import json
        return json.loads((release / "manifest.json").read_text())["card_data_version"]

    def name(self, aro_id: str) -> str:
        return self.terms[aro_id]["name"]

    def _chain(self, aro_id: str) -> list[str]:
        """The term and its is_a ancestors, nearest first."""
        order, seen, frontier = [aro_id], {aro_id}, [aro_id]
        while frontier:
            frontier = sorted({p for x in frontier for p in self._parents.get(x, ()) if p not in seen})
            seen.update(frontier)
            order += frontier
        return order

    def _is_target(self, aro_id: str) -> bool:
        """True if antibiotics target this term or a more specific one below it. CARD marks
        'fluoroquinolone sensitive gyrA' as targeted, and its parent 'antibiotic sensitive ...
        gyrA' is what the resistant gyrA derives from."""
        seen, stack = {aro_id}, [aro_id]
        while stack:
            term = stack.pop()
            if term in self._targets:
                return True
            for child in self._children.get(term, ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        return False

    def affected_target(self, aro_id: str) -> str | None:
        """Name of the sensitive target this model's resistant form derives from, nearest first."""
        for ancestor in self._chain(aro_id):
            for origin in sorted(self._derives.get(ancestor, ())):
                if self._is_target(origin):
                    return self.name(origin)
        return None

    def problem(self, det: Determinant) -> str | None:
        """Why a determinant cannot become a gene row, or None if it can."""
        model = self.models.get(det.aro_id)
        if model is None:
            if det.aro_id in self.terms:
                return (f"{det.aro_id} ({self.name(det.aro_id)}) is a CARD ontology term, not a resistance "
                        "determinant model; name a specific gene")
            return f"{det.aro_id} is not in CARD {self.version}"
        if not self.mechanisms.get(det.aro_id):
            return f"{det.aro_id} ({model['name']}) has no resistance mechanism in CARD"
        listed = {m for m, _ in self.variants.get(det.aro_id, ())}
        if model["model_type"] in VARIANT_MODELS:
            if not det.mutations:
                return (f"{model['name']} is a variant model: it confers resistance only with one of its "
                        f"{len(listed)} listed mutations, and none was named")
            unknown = [m for m in det.mutations if m not in listed]
            if unknown:
                return f"{', '.join(unknown)} is not among the mutations CARD lists for {model['name']}"
        elif det.mutations:
            return f"{model['name']} is not a variant model; CARD lists no point mutations for it"
        return None


def build_profile(card: CardProfiler, determinants: Sequence[Determinant], *, kind: str,
                  species: dict | None = None, requested: Sequence[str] | None = None,
                  unresolved: Iterable[dict] = (), profile_id: str | None = None) -> dict:
    """Build a ResistanceProfile. `unresolved` holds names the caller could not resolve to a
    determinant at all ({"text", "reason"}); determinants that fail here are added to it."""
    if kind not in CONFIDENCE:
        raise ValueError(f"unknown input kind {kind!r}; expected one of {sorted(CONFIDENCE)}")
    requested = list(requested) if requested is not None else [d.text for d in determinants]
    unresolved = [dict(u) for u in unresolved]

    merged: dict[str, Determinant] = {}
    for det in determinants:
        reason = card.problem(det)
        if reason:
            unresolved.append({"text": det.text, "reason": reason})
        elif det.aro_id in merged:
            old = merged[det.aro_id]
            merged[det.aro_id] = Determinant(det.aro_id, old.text, tuple(dict.fromkeys(old.mutations + det.mutations)))
        else:
            merged[det.aro_id] = det

    release = f"card-{card.version}"
    genes, evidence = [], []
    for n, det in enumerate(merged.values(), start=1):
        model = card.models[det.aro_id]
        mechanisms = [{"aro_id": a, "name": card.name(a)} for a in sorted(card.mechanisms[det.aro_id])]
        classes = [{"aro_id": a, "name": card.name(a)} for a in sorted(card.classes[det.aro_id])]
        kinds = dict(card.variants.get(det.aro_id, ()))
        variants = [{"mutation": m, "param_type": kinds[m]} for m in det.mutations]
        target = card.affected_target(det.aro_id)
        statement = f"CARD links {model['name']} to " + (
            "the " + _join([c["name"] for c in classes]) + " drug " + ("class" if len(classes) == 1 else "classes")
            if classes else "no drug class") + " and to " + _join([m["name"] for m in mechanisms]) + "."
        if variants:
            statement += (f" CARD lists {_join([v['mutation'] for v in variants])} among the resistance variants "
                          f"of this model.")
        evidence.append({"id": f"P{n}", "source": "card", "release": release, "aro_id": det.aro_id,
                         "statement": statement})
        genes.append({
            "aro_id": det.aro_id, "name": model["name"], "model_type": model["model_type"],
            "mechanisms": mechanisms, "defeated_classes": classes, "variants": variants,
            # CARD names the sensitive target but carries no structures: PDB entries come from the
            # target list (#20), so pdb_ids stays empty here.
            "affected_target": {"name": target, "pdb_ids": []} if target else None,
            "evidence_ids": [f"P{n}"],
        })

    level, basis = CONFIDENCE[kind]
    if not genes:
        level, basis = "low", "No determinant could be resolved, so the profile is empty."
    caveats = [
        "A gene in CARD can confer resistance. It does not show the gene is expressed in this isolate.",
        "Drug classes are CARD's vocabulary, not ATC.",
        "Defeated classes are class-level. Some drugs in a class may still work against a given gene, so use them "
        "to rule drugs out, not to rule them in.",
    ]
    if unresolved:
        caveats.append("Input names that could not be resolved are excluded from the profile. See unresolved_inputs.")
    if any(g["affected_target"] is None and any(m["name"].startswith("antibiotic target") for m in g["mechanisms"])
           for g in genes):
        caveats.append("For some target-related genes CARD names no sensitive target, so no affected target is given.")

    return {
        "contract_version": CONTRACT_VERSION,
        "profile_id": profile_id or str(uuid.uuid4()),
        "input": {"kind": kind, "species": species, "requested": requested},
        "unresolved_inputs": unresolved,
        "releases": [release],
        "genes": genes,
        "mechanisms": _rollup(genes, "mechanisms", evidence=False),
        "defeated_classes": _rollup(genes, "defeated_classes", evidence=True),
        "affected_targets": _targets(genes),
        "evidence": evidence,
        "confidence": {"level": level, "basis": basis},
        "caveats": caveats,
    }


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _rollup(genes: list[dict], field: str, *, evidence: bool) -> list[dict]:
    groups: dict[str, dict] = {}
    for gene in genes:
        for term in gene[field]:
            item = groups.setdefault(term["aro_id"], {"aro_id": term["aro_id"], "name": term["name"],
                                                      "gene_aro_ids": [], "evidence_ids": []})
            item["gene_aro_ids"].append(gene["aro_id"])
            item["evidence_ids"] += gene["evidence_ids"]
    out = [groups[a] for a in sorted(groups)]
    if not evidence:
        for item in out:
            del item["evidence_ids"]
    return out


def _targets(genes: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for gene in genes:
        target = gene["affected_target"]
        if target:
            item = groups.setdefault(target["name"], {"name": target["name"], "gene_aro_ids": [], "pdb_ids": []})
            item["gene_aro_ids"].append(gene["aro_id"])
            item["pdb_ids"] = sorted(set(item["pdb_ids"]) | set(target["pdb_ids"]))
    return [groups[n] for n in sorted(groups)]
