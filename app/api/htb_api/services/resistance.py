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
    ProfileRequest,
    ResistanceProfile,
)


class ProfilingUnavailable(Exception):
    """Profiling needs a built CARD release, and this process has none.

    Raised rather than answered with invented data: only CARD can say whether a
    determinant name is one it knows.
    """


class ProfilingRefused(Exception):
    """The request was read but cannot be profiled, e.g. an unknown species preset."""


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

    def build(self, request: ProfileRequest) -> ResistanceProfile: ...


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

    def build(self, request: ProfileRequest) -> ResistanceProfile:
        """Always unavailable: a fixture cannot resolve a name against CARD."""
        raise ProfilingUnavailable(
            "This API serves fixture profiles only and cannot resolve determinant names. "
            "Build a CARD release to profile typed names."
        )


class CardResistance(FixtureResistance):
    """Profiles real input against a built CARD release, and serves the fixtures otherwise.

    The release is loaded on the first request and kept, so starting the API needs no
    data: a process without a release answers `build` with `ProfilingUnavailable` and
    still serves the fixture profile and ranking. Reading, not writing, so the loaded
    reference is shared safely between requests.
    """

    def __init__(self, fixtures_dir: Path, data_dir: Path) -> None:
        super().__init__(fixtures_dir)
        self._data_dir = data_dir
        self._reference: object | None = None

    def _load(self) -> object:
        if self._reference is not None:
            return self._reference
        try:
            from htb_resistance import Reference
            from htb_resistance.reference import latest_release

            self._reference = Reference.from_release(latest_release(self._data_dir))
        except Exception as exc:  # no release, or one that no longer matches its manifest
            raise ProfilingUnavailable(
                f"No usable CARD release under {self._data_dir}: {exc}"
            ) from exc
        return self._reference

    def build(self, request: ProfileRequest) -> ResistanceProfile:
        from htb_resistance import (
            InputError,
            Species,
            build_profile,
            parse_gene_text,
            parse_preset,
        )
        from htb_resistance.cli import DEFAULT_PRESETS

        reference = self._load()
        species = Species(request.species) if request.species else None
        try:
            if request.kind == "species_preset":
                assert request.species is not None  # the schema refuses a preset without one
                parsed = parse_preset(request.species, DEFAULT_PRESETS)
            else:
                assert request.genes is not None  # the schema refuses a gene list without them
                parsed = parse_gene_text(request.genes, species=species)
            profile = build_profile(parsed, reference)  # type: ignore[arg-type]
        except InputError as exc:
            raise ProfilingRefused(str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise ProfilingRefused(f"This input could not be profiled: {exc}") from exc
        # Validated on the way out, so a contract break shows here and not in the browser.
        return ResistanceProfile.model_validate(profile.to_dict())


class SavedResistance(CardResistance):
    """Replay the checksummed #34 outputs without source downloads or recomputation.

    Explicitly selected: invalid/missing saved data fails startup instead of silently
    falling back to made-up rankings. Typed-input profiling keeps the CARD seam.
    """

    def __init__(self, fixtures_dir: Path, data_dir: Path, results_dir: Path) -> None:
        import hashlib
        import json

        super().__init__(fixtures_dir, data_dir)
        summary = json.loads((results_dir / "summary.json").read_bytes())

        def read(name: str) -> bytes:
            content = (results_dir / name).read_bytes()
            if hashlib.sha256(content).hexdigest() != summary["outputs"][name]:
                raise ValueError(f"Saved resistance checksum mismatch: {name}")
            return content

        self._profiles: dict[UUID, ResistanceProfile] = {}
        self._rankings: dict[UUID, AntibioticCandidateResult] = {}
        for stem in ("staphylococcus-aureus", "klebsiella-pneumoniae", "acinetobacter-baumannii"):
            profile = ResistanceProfile.model_validate_json(read(f"{stem}.profile.json"))
            ranking = AntibioticCandidateResult.model_validate_json(read(f"{stem}.ranking.json"))
            if (
                ranking.profile_id != profile.profile_id
                or ranking.pathogen != profile.input.species
            ):
                raise ValueError(f"Saved profile/ranking mismatch: {stem}")
            evidence = {item.id for item in profile.evidence}
            if any(
                not set(candidate.evasion.profile_evidence_ids) <= evidence
                for candidate in ranking.candidates
            ):
                raise ValueError(f"Saved ranking cites missing profile evidence: {stem}")
            profile = profile.model_copy(
                update={
                    "caveats": [
                        *profile.caveats,
                        "Saved CARD/ChEMBL integration run, not a fresh ranking. "
                        "Efficacy is unvalidated; Lean was not run.",
                    ]
                }
            )
            self._profiles[profile.profile_id] = profile
            self._rankings[profile.profile_id] = ranking

    def presets(self) -> list[PathogenPreset]:
        return [
            PathogenPreset(
                id=preset_id,
                label=label,
                pathogen=profile.input.species,
                profile_id=profile.profile_id,
                note=(
                    "Saved CARD/ChEMBL ranking of a draft preset, not a measured isolate. "
                    "Integration evidence only; efficacy is unvalidated. Lean was not run."
                ),
            )
            for preset_id, label, _, taxid in PRESETS
            for profile in self._profiles.values()
            if profile.input.species.ncbi_taxid == taxid
        ]

    def profiles(self) -> list[ResistanceProfile]:
        return list(self._profiles.values())

    def profile(self, profile_id: UUID) -> ResistanceProfile | None:
        return self._profiles.get(profile_id)

    def candidates(self, profile_id: UUID) -> AntibioticCandidateResult | None:
        return self._rankings.get(profile_id)

    def certificates(self) -> CertificateList:
        # Never attach a fixture proof to a real result merely because InChIKeys match.
        return CertificateList(contract_version="1", certificates=[])
