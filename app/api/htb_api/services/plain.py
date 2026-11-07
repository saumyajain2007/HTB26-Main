"""Plain-language summaries of evidence, for students.

Each EvidenceItem keeps its precise, source-naming `statement` (the jury and
audits use it). `summary` says the same fact in words a student can read at a
glance: no database names, no score names, no units they haven't met. Both
the fixtures and the live pipeline build summaries with these functions, so
the wording stays the same everywhere.
"""

from __future__ import annotations

import re

# ChEMBL action types, as verbs.
_ACTIONS: dict[str, str] = {
    "inhibitor": "Blocks",
    "antagonist": "Blocks",
    "negative allosteric modulator": "Dampens",
    "blocker": "Blocks",
    "agonist": "Activates",
    "partial agonist": "Partly activates",
    "positive allosteric modulator": "Boosts",
    "activator": "Activates",
    "modulator": "Changes the activity of",
    "binding agent": "Binds",
    "degrader": "Breaks down",
}

# Open Targets toxicity classes on drug labels, in everyday words.
_TOXICITY: dict[str, str] = {
    "infectious disease": "serious infections",
    "vascular toxicity": "blood clots and blood vessel problems",
    "carcinogenicity": "cancer",
    "teratogenicity": "harm to an unborn baby",
    "respiratory toxicity": "lung problems",
    "gastrointestinal toxicity": "gut problems",
    "hepatotoxicity": "liver damage",
    "cardiotoxicity": "heart problems",
    "nephrotoxicity": "kidney damage",
    "neurotoxicity": "nerve damage",
    "hematological toxicity": "blood problems",
    "dermatological toxicity": "serious skin reactions",
    "psychiatric toxicity": "mood or behaviour changes",
    "immune system toxicity": "immune system problems",
    "metabolic toxicity": "metabolic problems",
    "musculoskeletal toxicity": "muscle or bone problems",
}

_REGULATORS: dict[str, str] = {
    "FDA": "the US regulator (FDA)",
    "EMA": "the European regulator (EMA)",
    "EMA Human Drugs": "the European regulator (EMA)",
    "PMDA": "Japan's regulator (PMDA)",
    "DailyMed": "the US regulator (FDA)",
}


def join(names: list[str], limit: int = 4) -> str:
    """'A', 'A and B', 'A, B and C'; past `limit` names, a count with two examples."""
    if len(names) > limit:
        return f"{len(names)} proteins, including {names[0]} and {names[1]}"
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def target_association(target: str, disease: str, score: float) -> str:
    return f"{target} is linked to {disease} (link strength {score:.2f})."


def mechanism(target: str, action_type: str | None) -> str:
    verb = _ACTIONS.get((action_type or "").lower(), "Acts on")
    return f"{verb} {target}."


def mechanism_non_human(description: str, action_type: str | None) -> str:
    """A drug whose only target isn't a human protein, e.g. a viral enzyme."""
    verb = _ACTIONS.get((action_type or "").lower(), "Acts on")
    return f"{verb} {description}, which is not a human protein."


def bioactivity(target: str, median_pchembl: float, n_activities: int) -> str:
    # pChEMBL is -log10(molar potency): 8 is about 10 nM, 7 about 100 nM, 6 about 1 uM.
    if median_pchembl >= 8:
        strength = "very strongly"
    elif median_pchembl >= 7:
        strength = "strongly"
    elif median_pchembl >= 6:
        strength = "moderately"
    else:
        strength = "weakly"
    tests = "test" if n_activities == 1 else "tests"
    return f"Binds {target} {strength} in lab tests ({n_activities} {tests})."


def approval(regulator: str) -> str:
    return f"Approved by {_REGULATORS.get(regulator, regulator)}."


def warning(toxicity_class: str | None) -> str:
    """One label risk, lower case, to be joined into the warning sentence."""
    if not toxicity_class:
        return "serious risks listed on the label"
    return _TOXICITY.get(toxicity_class.lower(), toxicity_class.lower())


def warning_summary(toxicity_class: str | None) -> str:
    """A warning evidence item's summary: its one label risk, as a sentence."""
    risk = warning(toxicity_class)
    return risk[0].upper() + risk[1:] + "."


def network_unavailable(drug: str, disease: str) -> str:
    """Why a Candidate has no network result when no network ranking ran."""
    return (
        f"No protein network was available, so {drug} was ranked only by how strongly its "
        f"own Targets are linked to {disease}."
    )


def unscorable(reason: str, drug: str, disease: str) -> str:
    """Why one Candidate has no place in the protein network, by the ranking's reason code."""
    if reason == "network_unavailable":
        return network_unavailable(drug, disease)
    if reason == "no_retained_drug_targets":
        return (
            f"None of {drug}'s targets are in the main protein network, so it has no place "
            f"in it. It was chosen for its direct links to {disease}."
        )
    if reason == "no_retained_disease_targets":
        return (
            f"None of {disease}'s proteins are in the main protein network, so {drug} can't "
            "be placed near them."
        )
    raise ValueError(f"unknown reason {reason}")


def network_path(symbols: list[str]) -> str:
    """One route in the protein network, from a drug's Target to a Disease protein, by the
    proteins' symbols in order. A single protein is a Target that is a Disease protein."""
    if not symbols:
        raise ValueError("a route names at least one protein")
    first, last, through = symbols[0], symbols[-1], symbols[1:-1]
    if len(symbols) == 1:
        return f"{first} is itself a disease protein, so the drug acts on it directly."
    steps = "1 step" if len(symbols) == 2 else f"{len(symbols) - 1} steps"
    text = f"{first} connects to {last} in {steps} in the protein network"
    return f"{text}, through {join(through)}." if through else f"{text}."


# A gene, protein or complex name keeps its capitals: IL-6, STAT5, (ERK2), PI3K/AKT, C3.
_NAME_WORD = re.compile(r"\W*(?:.[^\sa-z]*[A-Z]|[A-Z][0-9])")


def pathway_name(name: str) -> str:
    """A pathway's name as words in a sentence: 'Signaling by Erythropoietin' becomes
    'signalling by erythropoietin pathway'. Gene and protein names keep their capitals."""
    words = [
        word if _NAME_WORD.match(word) else word.lower()
        for word in name.replace("ignaling", "ignalling").split()
    ]
    text = " ".join(words)
    return text if text.endswith("pathway") else f"{text} pathway"


def pathway(disease_proteins: list[str], name: str) -> str:
    """A pathway one of the drug's Targets shares with Disease proteins, by their symbols.

    One pathway record is one evidence item, shared by every Candidate with a Target in
    it, so the summary names the Disease proteins in it and not a drug's own Target."""
    if not disease_proteins:
        raise ValueError("a shared pathway includes at least one disease protein")
    if len(disease_proteins) == 1:
        members = f"the disease protein {disease_proteins[0]}"
    elif len(disease_proteins) <= 3:
        members = f"the disease proteins {join(disease_proteins)}"
    else:
        first, second = disease_proteins[:2]
        members = f"{len(disease_proteins)} disease proteins, among them {first} and {second}"
    return f"Targets a protein in the {pathway_name(name)}, which also includes {members}."
