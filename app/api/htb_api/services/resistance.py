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

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from ..schemas import (
    AntibioticCandidateResult,
    Certificate,
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


def card_root(data_dir: Path) -> Path:
    """Where CARD releases live: `data_dir/card` (where `htb_resistance build` writes them)."""
    nested = data_dir / "card"
    return nested if (nested / "releases").is_dir() else data_dir


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

            self._reference = Reference.from_release(latest_release(card_root(self._data_dir)))
        except Exception as exc:  # no release, or one that no longer matches its manifest
            raise ProfilingUnavailable(
                f"No usable CARD release under {self._data_dir}: {exc}"
            ) from exc
        return self._reference

    def _resolver(self, reference: object, species: object) -> Any:
        """How names are resolved. CARD's own matching here; `LiveResistance` adds the bridge."""
        return None

    @staticmethod
    def _species(text: str | None) -> Any:
        """A supported pathogen from its name or an alias (`MRSA`), else None."""
        import json

        from htb_resistance import Species
        from htb_resistance.cli import DEFAULT_PRESETS

        wanted = (text or "").strip().lower()
        if not wanted:
            return None
        presets = json.loads(DEFAULT_PRESETS.read_text(encoding="utf-8"))["presets"]
        for name, entry in presets.items():
            aliases = {a.lower() for a in entry.get("aliases", [])}
            if wanted == name.lower() or wanted in aliases:
                return Species(name, int(entry["ncbi_taxid"]))
        return None

    def build(self, request: ProfileRequest) -> ResistanceProfile:
        from htb_resistance import (
            InputError,
            build_profile,
            parse_gene_text,
            parse_preset,
        )
        from htb_resistance.cli import DEFAULT_PRESETS

        reference = self._load()
        species = None
        if request.kind == "gene_list":
            # The response schema carries a taxid, so a typed list needs one of the known pathogens.
            species = self._species(request.species)
            if species is None:
                raise ProfilingRefused(
                    f"Name the species of the isolate: {request.species or 'none was given'} is not "
                    "one of Staphylococcus aureus, Klebsiella pneumoniae or "
                    "Acinetobacter baumannii."
                )
        try:
            if request.kind == "species_preset":
                assert request.species is not None  # the schema refuses a preset without one
                parsed = parse_preset(request.species, DEFAULT_PRESETS)
            else:
                assert request.genes is not None  # the schema refuses a gene list without them
                parsed = parse_gene_text(request.genes, species=species)
            profile = build_profile(  # type: ignore[arg-type]
                parsed, reference, resolver=self._resolver(reference, parsed.species)
            )
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
        # Recorded by the run that produced the bundle, so the wording follows the data.
        self._lean_ran: bool = bool(summary.get("lean_requested"))

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
                        f"Efficacy is unvalidated; {self._lean_note()}.",
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
                note=None,
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

    def _lean_note(self) -> str:
        if self._lean_ran:
            return (
                "Lean 4 checked the property rules for each molecule; "
                "that confirms the encoded limits only"
            )
        return "Lean was not run"

    def certificates(self) -> CertificateList:
        # Never attach a fixture proof to a real result merely because InChIKeys match.
        # Only certificates Lean produced inside the saved run, for these exact molecules,
        # are listed, once per molecule and rule set.
        seen: dict[tuple[str, str], Certificate] = {}
        for ranking in self._rankings.values():
            for candidate in ranking.candidates:
                cert = candidate.certificate
                if cert is not None and cert.ran:
                    seen.setdefault((cert.inchikey, cert.rule_set), cert)
        return CertificateList(
            contract_version="1", certificates=[seen[key] for key in sorted(seen)]
        )


LIVE_CAVEAT = (
    "Computed live by the evasion rule from the determinants given. The rule has been compared "
    "with measured susceptibility (results/ws5_phenotype_validation); it is not a susceptibility "
    "test and no output should inform treatment of a patient."
)
LIVE_PROFILE_LIMIT = 256
"""Profiles kept in memory. The oldest goes first; a rebuild restores one at the same id."""


class LiveResistance(CardResistance):
    """Profiles real input and ranks the approved antibiotics against it, on request.

    Replaces the fixture ranking: a profile built here has a ranking computed from that profile by
    `ranking.antibiotic.rank_candidates`, over the catalogue in `catalogue_dir`, with CARD's drug
    links from the same release as the profile. Typed names go through the bridge, so AMRFinderPlus
    spellings (`mph(A)`) and point mutations (`gyrA S84L` with a species) resolve where CARD's plain
    name matching would not.

    Nothing is stored beyond this process: profiles and rankings live in a bounded in-memory table
    and are rebuilt from the same input to the same id. Lean checks each molecule's property rules
    when `lean_cache` is given (a proof of the encoded limits, not of safety or activity), and
    activity (ChEMBL MICs) is included only when `chembl_db` is given.
    """

    def __init__(
        self,
        fixtures_dir: Path,
        data_dir: Path,
        catalogue_dir: Path,
        chembl_db: Path | None = None,
        lean_cache: Path | None = None,
    ) -> None:
        super().__init__(fixtures_dir, data_dir)
        self._catalogue_dir = catalogue_dir
        self._chembl_db = chembl_db
        self._lean_cache = lean_cache
        self._lock = threading.Lock()
        self._activity_by_taxon: dict[int, dict[str, Any]] = {}
        self._rank_lock = threading.Lock()  # Lean's cache is per process; one batch at a time
        self._bridge: Any = None
        self._ranking_inputs: tuple[Any, Any, str] | None = None
        self._profiles: OrderedDict[UUID, ResistanceProfile] = OrderedDict()
        self._results: dict[UUID, AntibioticCandidateResult] = {}

    def _resolver(self, reference: object, species: object) -> Any:
        from htb_resistance import Bridge

        with self._lock:
            if self._bridge is None:
                self._bridge = Bridge(reference)  # type: ignore[arg-type]
            bridge = self._bridge
        name = getattr(species, "name", None)
        return bridge.resolver_for(name)

    def _inputs(self) -> tuple[Any, Any, str]:
        """The approved pool, CARD's drug links and the catalogue release, loaded once."""
        with self._lock:
            if self._ranking_inputs is None:
                try:
                    from htb_resistance.reference import latest_release
                    from ranking.antibiotic import DrugLinks, catalogue_release, load_pool

                    drugs, _ = load_pool(self._catalogue_dir)
                    links = DrugLinks.from_card(latest_release(card_root(self._data_dir)))
                    release = catalogue_release(self._catalogue_dir)
                except Exception as exc:
                    raise ProfilingUnavailable(
                        f"No usable antibiotic catalogue under {self._catalogue_dir}: {exc}"
                    ) from exc
                if not drugs:
                    raise ProfilingUnavailable(
                        f"The catalogue under {self._catalogue_dir} holds no approved drugs."
                    )
                self._ranking_inputs = (drugs, links, release)
            return self._ranking_inputs

    def _certifier(self) -> Any:
        """Lean's batch checker, or None when `lean_cache` is unset or Lean's package is missing.

        A molecule's certificate depends on the molecule and the rule set, not on the profile, so
        the first build pays for Lean and the rest read its cache. When Lean itself is not
        installed the certificates come back `ran: false` and the candidates read `unavailable`.
        """
        if self._lean_cache is None:
            return None
        try:
            from htb_verify import certify_batch
        except ImportError:
            return None
        cache = self._lean_cache
        return lambda smokes: certify_batch(smokes, cache_path=cache)

    def _activity(self, profile: dict[str, Any], drugs: Any) -> dict[str, Any]:
        species = profile["input"]["species"]
        if self._chembl_db is None or not self._chembl_db.is_file():
            return {}
        if not species or species.get("ncbi_taxid") is None:
            return {}
        taxid = species["ncbi_taxid"]
        with self._lock:
            if taxid in self._activity_by_taxon:
                return self._activity_by_taxon[taxid]
        from ranking.antibiotic import load_activity

        # Median MIC depends on the species and the pool, never on the genes, so it is read once.
        activity, _ = load_activity(self._chembl_db, [d.chembl_id for d in drugs], species)
        with self._lock:
            self._activity_by_taxon[taxid] = activity
        return activity

    def build(self, request: ProfileRequest) -> ResistanceProfile:
        from ranking.antibiotic import rank_candidates

        profile = super().build(request)
        drugs, links, release = self._inputs()
        raw = profile.model_dump(mode="json")
        with self._rank_lock:
            result, _log = rank_candidates(
                raw,
                drugs,
                links,
                catalogue_release=release,
                activity=self._activity(raw, drugs),
                certifier=self._certifier(),
            )
        ranking = AntibioticCandidateResult.model_validate(result)
        stored = profile.model_copy(update={"caveats": [*profile.caveats, LIVE_CAVEAT]})
        with self._lock:
            self._profiles[stored.profile_id] = stored
            self._profiles.move_to_end(stored.profile_id)
            self._results[stored.profile_id] = ranking
            while len(self._profiles) > LIVE_PROFILE_LIMIT:
                dropped, _ = self._profiles.popitem(last=False)
                self._results.pop(dropped, None)
        return stored

    def presets(self) -> list[PathogenPreset]:
        items: list[PathogenPreset] = []
        for preset_id, label, name, taxid in PRESETS:
            profile = self.build(ProfileRequest(kind="species_preset", species=name))
            items.append(
                PathogenPreset(
                    id=preset_id,
                    label=label,
                    pathogen=Pathogen(name=name, ncbi_taxid=taxid),
                    profile_id=profile.profile_id,
                    note=None,
                )
            )
        return items

    def profiles(self) -> list[ResistanceProfile]:
        with self._lock:
            return list(self._profiles.values())

    def profile(self, profile_id: UUID) -> ResistanceProfile | None:
        with self._lock:
            return self._profiles.get(profile_id)

    def candidates(self, profile_id: UUID) -> AntibioticCandidateResult | None:
        with self._lock:
            return self._results.get(profile_id)

    def certificates(self) -> CertificateList:
        # Only certificates Lean produced for these results, once per molecule and rule set; a
        # fixture proof is never attached because an InChIKey happens to match.
        seen: dict[tuple[str, str], Certificate] = {}
        with self._lock:
            results = list(self._results.values())
        for ranking in results:
            for candidate in ranking.candidates:
                cert = candidate.certificate
                if cert is not None and cert.ran:
                    seen.setdefault((cert.inchikey, cert.rule_set), cert)
        return CertificateList(
            contract_version="1", certificates=[seen[key] for key in sorted(seen)]
        )
