"""Resistance profiles and antibiotic rankings (docs/contracts.md).

The API serves the frozen contract fixtures from `fixtures/resistance/`, which
are copies of the reference files in `tests/fixtures/`; `tests/test_resistance.py`
fails if the two drift. This is the seam the real pipeline plugs into: Lane A's
profiling (`core/resistance/`) and Lane B's ranking (`core/ranking/`) replace
`FixtureResistance` with a backend of their own, so the web app never waits on
real data.

Nothing here claims a candidate works. The profile says which drug classes CARD
links to the determinants given, and the ranking says which candidates no known
mechanism is linked to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from ..schemas import (
    AntibioticCandidateResult,
    CertificateList,
    Pathogen,
    PathogenPreset,
    ResistanceProfile,
)

FIXTURE_NOTE = (
    "Fixture data. The scores, MICs and ranks are made up; the descriptors, rule "
    "outcomes and Lean results are real output of core/verify."
)

PRESETS: tuple[tuple[str, str, str, int], ...] = (
    ("s_aureus_mrsa", "MRSA (S. aureus)", "Staphylococcus aureus", 1280),
    (
        "k_pneumoniae_esbl",
        "ESBL/KPC K. pneumoniae",
        "Klebsiella pneumoniae",
        573,
    ),
    (
        "a_baumannii_carbapenem",
        "Carbapenem-resistant A. baumannii",
        "Acinetobacter baumannii",
        470,
    ),
)
"""The three pathogens chosen in issue #4, as the input screen offers them."""


class ResistanceSource(Protocol):
    """Where profiles and rankings come from. Fixtures today, the pipeline later."""

    def presets(self) -> list[PathogenPreset]: ...

    def profiles(self) -> list[ResistanceProfile]: ...

    def profile(self, profile_id: UUID) -> ResistanceProfile | None: ...

    def candidates(self, profile_id: UUID) -> AntibioticCandidateResult | None: ...

    def certificates(self) -> CertificateList: ...


class FixtureResistance:
    """Implements `ResistanceSource` from `fixtures/resistance/`.

    Only the pathogen the fixture covers has a profile; the other two presets
    carry `profile_id: null` until Lane A's profiling fills them in, so the app
    can show them as not yet available rather than invent data.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = fixtures_dir / "resistance"

    def _profile(self) -> ResistanceProfile:
        path = self._dir / "resistance_profile.json"
        return ResistanceProfile.model_validate_json(path.read_bytes())

    def _result(self) -> AntibioticCandidateResult:
        path = self._dir / "antibiotic_candidates.json"
        result = AntibioticCandidateResult.model_validate_json(path.read_bytes())
        return result.model_copy(update={"fixture_note": FIXTURE_NOTE})

    def presets(self) -> list[PathogenPreset]:
        covered = self._profile()
        items: list[PathogenPreset] = []
        for preset_id, label, name, taxid in PRESETS:
            fixture = name == covered.input.species.name
            items.append(
                PathogenPreset(
                    id=preset_id,
                    label=label,
                    pathogen=Pathogen(name=name, ncbi_taxid=taxid),
                    profile_id=covered.profile_id if fixture else None,
                    note=FIXTURE_NOTE if fixture else "No profile built for this pathogen yet.",
                )
            )
        return items

    def profiles(self) -> list[ResistanceProfile]:
        return [self._profile()]

    def profile(self, profile_id: UUID) -> ResistanceProfile | None:
        profile = self._profile()
        return profile if profile.profile_id == profile_id else None

    def candidates(self, profile_id: UUID) -> AntibioticCandidateResult | None:
        result = self._result()
        return result if result.profile_id == profile_id else None

    def certificates(self) -> CertificateList:
        path = self._dir / "certificate.json"
        return CertificateList.model_validate_json(path.read_bytes())
