"""How easily a target mutates away, from the number and kind of known resistance mutations.

The output is an **ordinal band** — low, moderate, high, unknown — and deliberately not a
probability. The inputs are counts of mutations somebody has published, so a number like
"0.73 escape probability" would imply a calibration that nothing here supports. There is no
held-out set of targets that did or did not escape to calibrate against, so a band is the
strongest honest form.

Four rules do most of the work, and each exists because the obvious alternative is wrong.

**Positions are escape routes; substitutions are not.** Counting substitutions scores a single
well-studied hotspot the same as a genuinely plastic target. See :mod:`mutations`.

**No documented mutations means unknown, never low.** This is the rule that matters most. An
absence in CARD is an absence of publications, and for a target nobody has used as a drug
target there will be none. Scoring that as "low risk" would systematically favour exactly the
novel targets whose escape behaviour is least known — which is the opposite of what a risk
score is for.

**Acquiring a new protein is not the target mutating.** mecA gives *S. aureus* a PBP that
beta-lactams do not bind; PBP2a is not a mutant of the native PBP. So target replacement,
protection and overexpression are reported as separate routes and never counted as positions.
Mixing them in would score a target as highly mutable on the strength of an escape mechanism
that does not involve mutating it. The same asymmetry the WS3 structure work enforces.

**A SNP in a multi-copy target is recessive.** *E. coli* carries seven rRNA operons, so one
mutated copy still leaves six making drug-sensitive ribosomes. The band is downgraded one step
when the target is multi-copy, and the caveat says so.

Every result carries its caveats, because the score's main confound cannot be removed:
**the count tracks how much a target has been studied.** gyrA has many documented mutations
partly because it mutates and partly because it has been sequenced in tens of thousands of
isolates. Nothing in CARD separates those, so ``evidence_depth`` is reported beside the band
and the caveat is attached to every single result, including the confident-looking ones.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

LOW, MODERATE, HIGH, UNKNOWN = "low", "moderate", "high", "unknown"
ORDER = (UNKNOWN, LOW, MODERATE, HIGH)

BANDS_FILE = Path(__file__).with_name("bands.json")

LITERATURE_BIAS = "literature_bias"
ABSENCE_NOT_ROBUSTNESS = "absence_is_not_robustness"
FITNESS_COST_UNKNOWN = "fitness_cost_unknown"
SINGLE_SOURCE = "single_source"
AMBIGUOUS_NOTATION = "ambiguous_notation"
MULTI_COPY_RECESSIVE = "multi_copy_recessive"
NON_MUTATIONAL_ROUTE = "non_mutational_route_present"
HOTSPOT_CONCENTRATED = "hotspot_concentrated"
UNPARSED_MUTATIONS = "unparsed_mutations"
COPY_NUMBER_UNKNOWN = "copy_number_unknown"


class RiskError(RuntimeError):
    """The band could not be computed. Never a default band."""


def load_rule(path=BANDS_FILE) -> dict:
    rule = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("rule_version", "escape_route_bands", "counted_mechanisms"):
        if key not in rule:
            raise RiskError(f"{path}: the band rule is missing {key!r}")
    return rule


def _band_for(positions: int, rule: dict) -> str:
    for entry in rule["escape_route_bands"]:
        high = entry["max_positions"]
        if positions >= entry["min_positions"] and (high is None or positions <= high):
            return entry["band"]
    return UNKNOWN


def _downgrade(band: str) -> str:
    index = ORDER.index(band)
    return ORDER[max(index - 1, 0)]


@dataclass(frozen=True)
class Caveat:
    code: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TargetRisk:
    """One target's escape-risk band, with everything needed to argue with it."""

    target_aro_id: str
    name: str
    band: str
    band_before_adjustment: str
    ordinal: bool = True                  # never a probability; see the module docstring
    escape_routes: int = 0                # distinct positions, counted mechanisms only
    substitutions: int = 0
    hotspot_concentration: float = 0.0    # share of substitutions at the busiest position
    mechanisms_counted: dict = field(default_factory=dict)
    non_mutational_routes: list = field(default_factory=list)
    cross_class_breadth: int = 0
    drug_classes: list = field(default_factory=list)
    evidence_depth: int = 0               # distinct sources behind the counted mutations
    copy_number: int | None = None
    caveats: list = field(default_factory=list)
    rule_version: str = "1"
    positions: list = field(default_factory=list)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["caveats"] = [c.as_dict() if isinstance(c, Caveat) else c for c in self.caveats]
        out["hotspot_concentration"] = round(self.hotspot_concentration, 4)
        return out

    @property
    def caveat_codes(self) -> list:
        return [c.code if isinstance(c, Caveat) else c["code"] for c in self.caveats]

    def sentence(self) -> str:
        """The band with its caveats attached, because the band alone overstates itself."""
        if self.band == UNKNOWN:
            head = f"{self.name}: escape risk unknown"
        else:
            head = (f"{self.name}: {self.band} escape risk — {self.escape_routes} documented "
                    f"escape route(s) across {self.substitutions} substitution(s)")
        notes = "; ".join(c.message if isinstance(c, Caveat) else c["message"]
                          for c in self.caveats)
        return f"{head}. {notes}" if notes else head


def score_target(record, *, rule: dict | None = None, rejected: list | None = None
                 ) -> TargetRisk:
    """Band one target. Caveats are part of the result, not an optional extra."""
    rule = rule or load_rule()
    counted_mechanisms = set(rule["counted_mechanisms"])
    recorded_only = set(rule.get("recorded_not_counted_mechanisms", ()))

    counted, other = [], []
    for mutation in record.mutations:
        mechanism = (mutation.mechanism or "").strip().lower()
        if mechanism in counted_mechanisms or (not mechanism and not recorded_only):
            counted.append(mutation)
        elif mechanism in recorded_only:
            other.append(mutation)
        elif mechanism:
            other.append(mutation)
        else:
            counted.append(mutation)

    positions = sorted({m.position for m in counted})
    per_position = Counter(m.position for m in counted)
    concentration = (max(per_position.values()) / len(counted)) if counted else 0.0
    classes = sorted({c for m in counted for c in m.drug_classes})
    sources = sorted({m.source for m in counted if m.source})

    non_mutational = sorted({(m.mechanism or "").strip() for m in other
                             if (m.mechanism or "").strip()})
    non_mutational += [m for m in record.non_mutational_mechanisms
                       if m and m not in non_mutational]

    caveats = [Caveat(LITERATURE_BIAS,
                      "the count reflects how much this target has been studied as well as "
                      "how readily it mutates; CARD does not separate the two"),
               Caveat(FITNESS_COST_UNKNOWN,
                      "no fitness cost is accounted for: a mutation that confers resistance "
                      "and cripples the organism is counted the same as one that does not")]

    if not counted:
        band = raw_band = UNKNOWN
        caveats.append(Caveat(
            ABSENCE_NOT_ROBUSTNESS,
            "no documented resistance mutations, which is an absence of publications rather "
            "than evidence of robustness; this is reported as unknown and never as low risk"))
    else:
        raw_band = _band_for(len(positions), rule)
        band = raw_band
        if record.multi_copy:
            band = _downgrade(band)
            caveats.append(Caveat(
                MULTI_COPY_RECESSIVE,
                f"the target has {record.copy_number} copies, so a single resistance SNP is "
                f"recessive: wild-type copies still make drug-sensitive product. Band "
                f"downgraded from {raw_band} to {band}"))
        elif record.copy_number is None:
            caveats.append(Caveat(
                COPY_NUMBER_UNKNOWN,
                "copy number is unknown, so no recessiveness adjustment was applied; a "
                "multi-copy target would band lower"))

    if counted and len(sources) < rule.get("min_sources_before_single_source_caveat", 2):
        caveats.append(Caveat(
            SINGLE_SOURCE,
            f"all counted mutations trace to {len(sources) or 'no recorded'} source(s), so "
            f"the count is one group's observations rather than a consensus"))
    if counted and concentration >= 0.75 and len(positions) > 1:
        caveats.append(Caveat(
            HOTSPOT_CONCENTRATED,
            f"{concentration:.0%} of substitutions sit at one position, so the routes are "
            f"less independent than the count suggests"))
    ambiguous = [m.raw for m in record.mutations if m.kind == "ambiguous"]
    if ambiguous:
        caveats.append(Caveat(
            AMBIGUOUS_NOTATION,
            f"{len(ambiguous)} variant(s) could be read as either a protein or a nucleotide "
            f"change ({', '.join(ambiguous[:3])}); the target's molecule type was not given, "
            f"so no copy-number adjustment could be justified"))
    if non_mutational:
        caveats.append(Caveat(
            NON_MUTATIONAL_ROUTE,
            f"escape is also documented without mutating this target "
            f"({', '.join(non_mutational)}); those routes are listed separately and are not "
            f"counted toward the band, because acquiring or overproducing a protein is not "
            f"the target mutating"))
    if rejected:
        caveats.append(Caveat(
            UNPARSED_MUTATIONS,
            f"{len(rejected)} row(s) had unreadable variant notation and are not counted, so "
            f"the route count is a floor rather than a total"))
    if counted and len(classes) >= rule.get("cross_class_breadth_note_at", 3):
        caveats.append(Caveat(
            "cross_class_breadth",
            f"the documented mutations span {len(classes)} drug classes, so escape here "
            f"costs more than one option"))

    return TargetRisk(
        target_aro_id=record.target_aro_id, name=record.name, band=band,
        band_before_adjustment=raw_band, escape_routes=len(positions),
        substitutions=len(counted), hotspot_concentration=concentration,
        mechanisms_counted=dict(Counter((m.mechanism or "unspecified") for m in counted)),
        non_mutational_routes=non_mutational, cross_class_breadth=len(classes),
        drug_classes=classes, evidence_depth=len(sources), copy_number=record.copy_number,
        caveats=caveats, rule_version=rule["rule_version"], positions=positions)


def score_all(records, *, rule: dict | None = None) -> list:
    rule = rule or load_rule()
    return [score_target(record, rule=rule) for record in records]


def table(risks) -> str:
    """Per-target bands. Caveat codes are in the table, not in a footnote."""
    lines = [f"{'target':28} {'band':10} {'routes':>6} {'subs':>5} {'hotspot':>8} "
             f"{'sources':>7} {'copies':>6}  caveats",
             "-" * 128]
    for risk in risks:
        lines.append(
            f"{risk.name[:28]:28} {risk.band:10} {risk.escape_routes:>6} "
            f"{risk.substitutions:>5} {risk.hotspot_concentration:>7.0%} "
            f"{risk.evidence_depth:>7} "
            f"{('?' if risk.copy_number is None else risk.copy_number):>6}  "
            f"{','.join(risk.caveat_codes)}")
    lines.append("-" * 128)
    lines.append("bands are ordinal, not probabilities. routes are distinct positions with a "
                 "documented resistance substitution.")
    lines.append(f"every row carries {LITERATURE_BIAS}: the count tracks study effort as "
                 f"well as mutability, and CARD cannot separate them.")
    return "\n".join(lines)
