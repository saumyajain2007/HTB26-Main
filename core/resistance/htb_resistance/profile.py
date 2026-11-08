"""Build a ``ResistanceProfile``, contract version 1 (docs/contracts.md).

``build_profile`` returns a :class:`Profile`, whose ``contract`` is exactly the frozen
shape that ranking and the app read, matching tests/fixtures/resistance_profile.json.
Fields outside the contract (how each name was matched, the ok/partial status for an exit
code) stay on the Python object and never reach the JSON.

The rules the rest of the pipeline relies on:

  - Every string read is in ``input.requested``. Anything that did not become a gene row
    is in ``unresolved_inputs`` with a reason. Nothing is silently dropped.
  - Nothing resolvable at all raises ``InputError`` naming every unknown entry.
  - ``strict=True`` turns any unresolved entry into an ``InputError``.
  - The ``mechanisms``, ``defeated_classes`` and ``affected_targets`` roll-ups are derived
    from the gene rows, so they can never disagree with them.
  - Every gene row cites a ``P#`` evidence item naming the CARD release it came from.
  - Mechanism and class terms carry ARO ids, because the contract says to join on ids.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from .inputs import AMRFINDERPLUS, GENE_LIST, SPECIES_PRESET, InputError, Parsed, Token
from .reference import Entry, Reference

CONTRACT_VERSION = "1"

PRESENCE_CAVEAT = ("A gene in CARD can confer resistance. It does not show the gene is "
                   "expressed in this isolate, and AMRFinderPlus documents the same limit.")
VOCABULARY_CAVEAT = "Drug classes are CARD's vocabulary, not ATC."
TARGET_CAVEAT = ("Affected target names are CARD's own determinant names, not curated protein "
                 "names, and pdb_ids are left empty for WS3 to fill.")

# CARD mechanism names that mean the drug's target is changed rather than the drug
# destroyed or expelled. Only these give the profile an affected target.
_TARGET_MECHANISMS = ("target alteration", "target replacement", "target protection")

_HIGH_METHODS = ("ALLELE", "EXACT", "POINT")
_BRIDGED = ("normalised_name", "species_variant_model", "homolog_species_model")


@dataclass
class Call:
    """Internal provenance for one gene row. Not part of the contract."""

    requested_as: str
    origin: str
    aro_id: str
    short_name: str
    match: str
    source_method: str
    evidence_id: str
    mutation: str | None = None
    mutation_in_card: bool = True


@dataclass
class Profile:
    contract: dict
    calls: list = field(default_factory=list)
    status: str = "ok"            # ok | partial, for the CLI exit code

    def to_dict(self) -> dict:
        return self.contract

    def to_json(self) -> str:
        return json.dumps(self.contract, indent=2)


def _profile_id(release: str, kind: str, requested, supplement: str | None = None) -> str:
    """A UUID that is stable for the same inputs against the same release.

    uuid5 of the inputs, with the version and variant bits set to those of a version 4
    UUID so it satisfies the contract while staying reproducible across runs.
    """
    seed = "htb26:resistance-profile:" + "\u001f".join([release, supplement or "", kind, *requested])
    raw = bytearray(uuid.uuid5(uuid.NAMESPACE_URL, seed).bytes)
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _confidence(parsed: Parsed, calls) -> dict:
    if parsed.kind == SPECIES_PRESET:
        return {"level": "low",
                "basis": f"Genes come from the {parsed.preset_status!r} species preset for "
                         f"{parsed.species.name if parsed.species else 'this species'}, not from "
                         "this isolate. No genome was examined."}
    if parsed.kind == AMRFINDERPLUS:
        methods = [c.source_method.split(":", 1)[1] for c in calls]
        if methods and all(m.startswith(_HIGH_METHODS) for m in methods):
            return {"level": "high",
                    "basis": "Every call is an exact, allele or point match reported by "
                             "AMRFinderPlus against the isolate's assembly. Expression and copy "
                             "number were not assessed."}
        return {"level": "medium",
                "basis": "Calls come from AMRFinderPlus against the isolate's assembly, but some "
                         "rest on a BLAST, HMM or partial hit rather than an exact match. "
                         "Expression and copy number were not assessed."}
    return {"level": "low",
            "basis": "Gene presence was asserted by the user. Expression and copy number were "
                     "not assessed."}


def _statement(entry: Entry, release: str, mutation: str | None) -> str:
    classes = ", ".join(t.name for t in entry.drug_classes) or "no drug class"
    mechanisms = ", ".join(t.name for t in entry.mechanisms)
    text = (f"CARD release {release} links {entry.name} ({entry.aro}) to {classes} "
            f"and to {mechanisms}.")
    if mutation:
        listed = {v.mutation for v in entry.variants}
        text += (f" {mutation} is among the resistance variants CARD lists for this model."
                 if mutation in listed
                 else f" {mutation} was supplied with the input and is not among the resistance "
                      "variants CARD lists for this model.")
    return text


def _affected_target(entry: Entry) -> dict | None:
    """Only a mechanism that changes the drug's target gives the profile a target."""
    if not any(m for m in entry.mechanisms if any(k in m.name for k in _TARGET_MECHANISMS)):
        return None
    return {"name": entry.short_name or entry.name, "pdb_ids": []}


def _join(items: list) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _curated_statement(entry: Entry, supplement_release: str, card_release: str) -> str:
    added = [c.drug_class.name for c in entry.curated]
    cites = "; ".join(f"{c['citation']} (PMID {c['pmid']})"
                      for cur in entry.curated for c in cur.citations)
    reasons = " ".join(dict.fromkeys(cur.reason for cur in entry.curated))
    return (f"Curated supplement, not in {card_release.replace('card-', 'CARD ')}: {entry.name} also defeats the "
            f"{_join(added)} drug {'class' if len(added) == 1 else 'classes'}. {reasons} Sources: {cites}")


def _rollup(calls, rows, key, evidence=None) -> list:
    """Group a per-gene term list into a roll-up carrying the genes behind each term.

    `evidence` maps (gene, term) to the evidence ids behind that link, so a class the curated
    supplement added cites the supplement's item and a class CARD holds cites CARD's. Without it
    every term cites the gene's CARD item.
    """
    out: dict[str, dict] = {}
    for call, row in zip(calls, rows):
        for term in row[key]:
            item = out.setdefault(term["aro_id"], {"aro_id": term["aro_id"], "name": term["name"],
                                                   "gene_aro_ids": [], "evidence_ids": []})
            if row["aro_id"] not in item["gene_aro_ids"]:
                item["gene_aro_ids"].append(row["aro_id"])
            for ev in (evidence or {}).get((row["aro_id"], term["aro_id"]), [call.evidence_id]):
                if ev not in item["evidence_ids"]:
                    item["evidence_ids"].append(ev)
    return [out[k] for k in sorted(out)]


def build_profile(parsed: Parsed, reference: Reference, strict: bool = False,
                  resolver=None) -> Profile:
    """Build the profile. ``resolver(token) -> Resolution`` replaces plain CARD name matching
    (see ``bridge.Bridge.resolver_for``); left out, behaviour is exactly as before."""
    release = reference.release
    # unresolved_inputs is about names the caller supplied, and every text in it has to be
    # in input.requested. A row with no name at all is counted in the caveats instead.
    unresolved = [{"text": r.raw, "reason": r.reason} for r in parsed.rejected if r.raw]
    nameless = sum(1 for r in parsed.rejected if not r.raw)
    calls: list = []
    rows: list = []
    seen_aro: dict[str, str] = {}

    for token in parsed.tokens:
        res = reference.resolve(token.lookup) if resolver is None else resolver(token)
        if res.status != "resolved":
            reason = res.reason
            if res.candidates:
                reason += f" (candidates: {', '.join(res.candidates)})"
            unresolved.append({"text": token.raw, "reason": reason})
            continue
        entry = res.entry
        if entry.aro in seen_aro:
            unresolved.append({
                "text": token.raw,
                "reason": f"the same CARD determinant as '{seen_aro[entry.aro]}' "
                          f"({entry.aro}), already in the profile"})
            continue
        if not entry.mechanisms:
            unresolved.append({
                "text": token.raw,
                "reason": f"{entry.aro} has no resistance mechanism in CARD {release}, so it "
                          "cannot be reported as a determinant"})
            continue
        seen_aro[entry.aro] = token.raw

        evidence_id = f"P{len(rows) + 1}"
        listed = {v.mutation: v.param_type for v in entry.variants}
        variants = []
        if token.mutation:
            variants.append({"mutation": token.mutation,
                             "param_type": listed.get(token.mutation)})
        rows.append({
            "aro_id": entry.aro,
            "name": entry.name,
            "model_type": entry.model_type,
            "mechanisms": [t.as_dict() for t in entry.mechanisms],
            "defeated_classes": [t.as_dict() for t in entry.drug_classes],
            "variants": variants,
            "affected_target": _affected_target(entry),
            "evidence_ids": [evidence_id],
        })
        calls.append(Call(
            requested_as=token.raw, origin=token.origin, aro_id=entry.aro,
            short_name=entry.short_name or entry.name, match=res.how,
            source_method=token.method, evidence_id=evidence_id, mutation=token.mutation,
            mutation_in_card=token.mutation in listed if token.mutation else True,
        ))

    if not rows:
        if unresolved:
            raise InputError("nothing could be profiled. " + _describe(unresolved))
        raise InputError("no entries to profile")
    if strict and unresolved:
        raise InputError("strict mode: " + _describe(unresolved))

    evidence = [{"id": c.evidence_id, "source": "card", "release": release,
                 "aro_id": c.aro_id,
                 "statement": _statement(reference.entries[c.aro_id], release, c.mutation)}
                for c in calls]

    # Classes from the curated supplement come after CARD's own, each gene with one extra evidence
    # item (source "curated") so they can always be told apart from CARD's links.
    class_evidence: dict[tuple[str, str], list[str]] = {}
    for call, row in zip(calls, rows):
        for term in row["defeated_classes"]:
            class_evidence[(row["aro_id"], term["aro_id"])] = [call.evidence_id]
    curated_genes = 0
    for call, row in zip(calls, rows):
        entry = reference.entries[call.aro_id]
        if not entry.curated:
            continue
        curated_genes += 1
        curated_id = f"P{len(evidence) + 1}"
        evidence.append({"id": curated_id, "source": "curated", "release": reference.supplement_release,
                         "aro_id": call.aro_id,
                         "statement": _curated_statement(entry, reference.supplement_release, release)})
        row["evidence_ids"].append(curated_id)
        row["defeated_classes"] = sorted(row["defeated_classes"] + [c.drug_class.as_dict() for c in entry.curated],
                                         key=lambda t: t["name"])
        for c in entry.curated:
            class_evidence[(call.aro_id, c.drug_class.aro_id)] = [curated_id]
    releases = [release] + ([reference.supplement_release] if curated_genes else [])

    targets: dict[str, dict] = {}
    for row in rows:
        target = row["affected_target"]
        if target is None:
            continue
        item = targets.setdefault(target["name"], {"name": target["name"], "gene_aro_ids": [],
                                                   "pdb_ids": []})
        item["gene_aro_ids"].append(row["aro_id"])

    mechanisms = [{k: v for k, v in m.items() if k != "evidence_ids"}
                  for m in _rollup(calls, rows, "mechanisms")]

    contract = {
        "contract_version": CONTRACT_VERSION,
        "profile_id": _profile_id(release, parsed.kind, parsed.requested, reference.supplement_release),
        "input": {
            "kind": parsed.kind,
            "species": parsed.species.as_dict() if parsed.species else None,
            "requested": list(parsed.requested),
        },
        "unresolved_inputs": unresolved,
        "releases": releases,
        "genes": rows,
        "mechanisms": mechanisms,
        "defeated_classes": _rollup(calls, rows, "defeated_classes", class_evidence),
        "affected_targets": [targets[k] for k in sorted(targets)],
        "evidence": evidence,
        "confidence": _confidence(parsed, calls),
        "caveats": _caveats(parsed, reference, calls, rows, unresolved, nameless, bool(curated_genes)),
    }
    return Profile(contract=contract, calls=calls,
                   status="ok" if not unresolved else "partial")


def _caveats(parsed: Parsed, reference: Reference, calls, rows, unresolved,
             nameless: int = 0, curated: bool = False) -> list:
    caveats = [PRESENCE_CAVEAT, VOCABULARY_CAVEAT]
    caveats.extend(parsed.notes)
    if curated:
        caveats.append("Some defeated classes come from a curated supplement, not from CARD's download. Each is "
                       "marked in the evidence (source: curated) with its citations.")
    if nameless:
        caveats.append(f"{nameless} input row(s) carried no gene symbol and were skipped.")
    if parsed.kind == SPECIES_PRESET:
        caveats.append(f"The preset is {parsed.preset_status!r}: its gene list is not a cited "
                       "typical profile yet, so treat this profile as a draft.")
    if unresolved:
        n = len(unresolved)
        caveats.append(f"{n} input entr{'y was' if n == 1 else 'ies were'} not profiled and "
                       "excluded; see unresolved_inputs.")
    if any(row["affected_target"] for row in rows):
        caveats.append(TARGET_CAVEAT)
    loose = [c.requested_as for c in calls
             if c.match in ("case_insensitive", "bla_prefix_stripped")]
    if loose:
        caveats.append(f"{', '.join(loose)} matched only after case folding or dropping a leading "
                       "'bla', which is a guess about spelling rather than CARD data.")
    bridged = [f"{c.requested_as} ({c.match})" for c in calls
               if c.match.split(":", 1)[0] in _BRIDGED]
    if bridged:
        caveats.append(f"{', '.join(bridged)} was matched by a bridging rule (normalised spelling or "
                       "a species variant model), not by CARD's own name; a homolog_species_model "
                       "match borrows the model of a related species. These are rule-based matches, "
                       "not curated.")
    unlisted = [f"{c.mutation} in {c.short_name}" for c in calls if not c.mutation_in_card]
    if unlisted:
        caveats.append(f"{', '.join(unlisted)} is not among CARD's known resistance variants for "
                       "that model, so the mutation is recorded but unsupported.")
    if parsed.kind == AMRFINDERPLUS:
        weak = [c.requested_as for c in calls
                if not c.source_method.split(":", 1)[1].startswith(_HIGH_METHODS)]
        if weak:
            caveats.append(f"{', '.join(weak)} rests on a BLAST, HMM or partial hit, so the gene "
                           "may be truncated or non-functional.")
    if reference.problems:
        n = len(reference.problems)
        caveats.append(f"{n} CARD entr{'y' if n == 1 else 'ies'} in this release "
                       f"{'was' if n == 1 else 'were'} left out of the reference because the ARO "
                       "id was not the kind of term its field means, for example an obsolete "
                       "determinant. They cannot appear in any profile.")
    return caveats


def _describe(unresolved) -> str:
    return "Unresolved entries: " + "; ".join(
        f"'{u['text']}': {u['reason']}" for u in unresolved)
