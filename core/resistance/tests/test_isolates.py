"""WS2 isolate fixtures: a CTX-M producer, an MRSA with mecA, and one case per pathogen,
each checked against the drug classes it should and should not defeat.

The cases live in fixtures/isolates.json. They are checked in two layers, because the two
answer different questions:

**Pipeline layer** (always runs). A synthetic CARD release is generated from each case, then
profiled. This proves the machinery holds: the classes aggregate across genes, the
must-not-defeat classes stay absent, mutations are recorded against the right determinant,
and the contract comes out valid. It does *not* prove the biology. The synthetic release is
built from the same expectations the test then asserts, so a wrong expectation would pass
here. To keep it from being purely circular each gene is also given a decoy class the
expectation forbids, and a decoy determinant is added that no case asks for.

**Biology layer** (skipped without data). The same cases against a real CARD release, which
is where "checked against expected defeated classes" actually means something. Build one
with ``uv run python -m htb_resistance build`` and these run; CI without CARD data skips
them. Expectations are names, not ARO ids, and are "must include" rather than exact, since
CARD lists more classes per gene than the few that matter clinically.

ARO ids are asserted only from ``verified_aro_ids``, which holds ids already confirmed
elsewhere in this repo (tests/fixtures/resistance_profile.json, type-checked in
docs/ontology-check.md). No id here was written from memory.
"""

import io
import json
import tarfile
from pathlib import Path

import pytest

from htb_resistance.card import DEFAULT_DIR, build
from htb_resistance.inputs import Species, parse_gene_text
from htb_resistance.profile import build_profile
from htb_resistance.reference import Reference
from htb_resistance.typecheck import DETERMINANT

FIX = Path(__file__).parent / "fixtures"
ISOLATES = json.loads((FIX / "isolates.json").read_text(encoding="utf-8"))["isolates"]
BY_ID = {case["id"]: case for case in ISOLATES}
IDS = [case["id"] for case in ISOLATES]

# Classes a case forbids are also planted in the synthetic release as decoys, so the
# pipeline layer can fail rather than merely agreeing with itself.
DECOY_CLASS = "decoy antibiotic"
DECOY_GENE = "TESTDECOY-1"


def case_ids(*wanted):
    return [i for i in IDS if i in wanted]


# ----------------------------------------------------------------- the fixtures themselves

def test_the_two_named_cases_are_present():
    """The task names a CTX-M producer and an MRSA with mecA specifically."""
    assert "ctx-m-producer" in BY_ID
    assert "mrsa-meca" in BY_ID
    assert BY_ID["mrsa-meca"]["genes"] == ["mecA"]
    assert "CTX-M-15" in BY_ID["ctx-m-producer"]["genes"]


def test_every_chosen_pathogen_has_a_case():
    """tasks.md picks three ESKAPE species; each needs at least one isolate."""
    covered = {case["species"]["name"] for case in ISOLATES}
    assert covered == {"Staphylococcus aureus", "Klebsiella pneumoniae", "Acinetobacter baumannii"}


def test_every_case_carries_a_type_checked_taxid():
    from htb_resistance.typecheck import PATHOGENS

    for case in ISOLATES:
        species = case["species"]
        assert PATHOGENS.get(species["ncbi_taxid"]) == species["name"], case["id"]


@pytest.mark.parametrize("case", ISOLATES, ids=IDS)
def test_every_case_states_why_it_expects_what_it_expects(case):
    assert case["expectation_basis"], case["id"]
    assert case["expect"]["defeated_classes"], "a case with no expectation proves nothing"
    assert case["expect"]["mechanisms"], case["id"]


@pytest.mark.parametrize("case", ISOLATES, ids=IDS)
def test_no_case_both_expects_and_forbids_a_class(case):
    expect = case["expect"]
    assert not set(expect["defeated_classes"]) & set(expect["not_defeated_classes"])


def test_at_least_one_case_is_falsifiable_by_a_forbidden_class():
    """Without a must-not-defeat class a case cannot catch an over-broad profile."""
    assert [c for c in ISOLATES if c["expect"]["not_defeated_classes"]]


def test_the_esbl_and_carbapenemase_cases_differ_on_carbapenem():
    """The contrast that makes both cases worth having."""
    esbl = BY_ID["ctx-m-producer"]["expect"]
    kpc = BY_ID["kpc-klebsiella"]["expect"]
    assert "carbapenem" in esbl["not_defeated_classes"]
    assert "carbapenem" in kpc["defeated_classes"]


# ----------------------------------------------------------------- pipeline layer

def _determinant_name(case, gene: str) -> str:
    """The CARD name a case's gene string refers to, with any trailing mutation removed."""
    for name in case["expect"]["variants"]:
        if gene == name or gene.startswith(name + " "):
            return name
    return gene


def _synthetic_card(case) -> dict:
    """A CARD release holding exactly this case's genes, plus decoys.

    Placeholder ARO:94xxxxx accessions throughout: a synthetic release must not carry real
    CARD ids, or a reader could mistake generated content for curated data.
    """
    expect = case["expect"]
    classes = list(dict.fromkeys(expect["defeated_classes"]))
    mechanisms = list(dict.fromkeys(expect["mechanisms"]))
    forbidden = list(dict.fromkeys(expect["not_defeated_classes"]))

    terms: dict[str, tuple] = {}          # aro -> (name, category or None)
    def add(name, category=None):
        for aro, (existing, _) in terms.items():
            if existing == name:
                return aro
        aro = f"ARO:94{len(terms):05d}"
        terms[aro] = (name, category)
        return aro

    # The one real id a synthetic release has to use: typecheck.DETERMINANT hardcodes the
    # ontology root, so a determinant has to descend from this exact accession to be typed
    # as one. Everything else below gets a generated ARO:94xxxxx placeholder.
    determinant_root = DETERMINANT
    terms[determinant_root] = ("determinant of antibiotic resistance", None)
    # A case's gene string may carry a trailing mutation ("... gyrA ... S84L"), which the
    # parser strips before lookup. The release must therefore hold the name WITHOUT it,
    # and expect.variants is keyed by exactly that name.
    gene_names = {g: _determinant_name(case, g) for g in case["genes"]}
    gene_aros = {g: add(gene_names[g]) for g in case["genes"]}
    decoy_gene_aro = add(DECOY_GENE)
    class_aros = {c: add(c, "Drug Class") for c in classes}
    # The forbidden classes and a decoy exist in the ontology but are linked only to the
    # decoy determinant, so a profile that reported them would be wrong, not unlucky.
    decoy_class_aros = {c: add(c, "Drug Class") for c in forbidden + [DECOY_CLASS]}
    mech_aros = {m: add(m, "Resistance Mechanism") for m in mechanisms}

    def model(model_id, gene_name, gene_aro, class_map, mutation=None):
        entry = {
            "model_id": model_id,
            "model_name": gene_name,
            "model_type": "protein variant model" if mutation else "protein homolog model",
            "ARO_accession": gene_aro.split(":")[1],
            "CARD_short_name": gene_name,
            "ARO_category": {},
            "model_param": {},
        }
        for i, (name, aro) in enumerate(list(class_map.items())):
            entry["ARO_category"][f"c{i}"] = {
                "category_aro_accession": aro.split(":")[1],
                "category_aro_name": name,
                "category_aro_class_name": "Drug Class",
            }
        for i, (name, aro) in enumerate(mech_aros.items()):
            entry["ARO_category"][f"m{i}"] = {
                "category_aro_accession": aro.split(":")[1],
                "category_aro_name": name,
                "category_aro_class_name": "Resistance Mechanism",
            }
        if mutation:
            entry["model_param"] = {"snp": {"param_type": "single resistance variant",
                                            "param_value": {"1": mutation},
                                            "Curated-R": {"1": mutation}}}
        return entry

    card = {"_version": "9.4.0", "_timestamp": "2026-01-01T00:00:00+00:00"}
    for i, gene in enumerate(case["genes"], start=1):
        name = gene_names[gene]
        card[str(i)] = model(str(i), name, gene_aros[gene], class_aros,
                             mutation=expect["variants"].get(name))
    card["900"] = model("900", DECOY_GENE, decoy_gene_aro, decoy_class_aros)

    obo = ["format-version: 1.2", "date: 11:08:2026 08:59", "ontology: test_isolates", ""]
    for aro, (name, _) in terms.items():
        obo += ["[Term]", f"id: {aro}", f"name: {name}"]
        if aro in set(gene_aros.values()) | {decoy_gene_aro}:
            obo.append(f"is_a: {determinant_root} ! determinant of antibiotic resistance")
        obo.append("")
    aro_tsv = ("Accession\tName\tDescription\tID\tCARD Short Name\n"
               + "".join(f"{aro}\t{terms[aro][0]}\tfixture term.\t\t{terms[aro][0]}\n"
                         for aro in set(gene_aros.values()) | {decoy_gene_aro}))
    categories = ("ARO Category\tARO Accession\tARO Name\n"
                  + "".join(f"{cat}\t{aro}\t{name}\n"
                            for aro, (name, cat) in terms.items() if cat))
    return {"card": card, "obo": "\n".join(obo) + "\n",
            "aro_tsv": aro_tsv, "categories": categories}


def _tar(path: Path, members: dict) -> None:
    with tarfile.open(path, "w:bz2") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    """One built synthetic release per case, keyed by case id."""
    out = {}
    for case in ISOLATES:
        root = tmp_path_factory.mktemp(case["id"].replace("-", "_"))
        parts = _synthetic_card(case)
        data, ont = root / "card-data.tar.bz2", root / "card-ontology.tar.bz2"
        _tar(data, {"card.json": json.dumps(parts["card"]).encode(),
                    "aro_categories.tsv": parts["categories"].encode()})
        _tar(ont, {"aro.obo": parts["obo"].encode(), "aro.tsv": parts["aro_tsv"].encode()})
        out[case["id"]] = build(root / "data", data_archive=data, ontology_archive=ont,
                                log=lambda *_: None)
    return out


def _profile_for(case, release):
    reference = Reference.from_release(release)
    species = Species(case["species"]["name"], case["species"]["ncbi_taxid"])
    parsed = parse_gene_text(", ".join(case["genes"]), species=species)
    return build_profile(parsed, reference)


def _assert_expectations(case, profile):
    """The shared check both layers use."""
    contract = profile.contract
    expect = case["expect"]
    classes = {t["name"] for t in contract["defeated_classes"]}
    mechanisms = {t["name"] for t in contract["mechanisms"]}
    targets = {t["name"] for t in contract["affected_targets"]}

    missing = set(expect["defeated_classes"]) - classes
    assert not missing, f"{case['id']}: expected to defeat {sorted(missing)}, got {sorted(classes)}"
    forbidden = set(expect["not_defeated_classes"]) & classes
    assert not forbidden, f"{case['id']}: must not defeat {sorted(forbidden)}"
    assert set(expect["mechanisms"]) <= mechanisms, case["id"]
    assert set(expect["targets_affected"]) <= targets, case["id"]

    for gene, mutation in expect["variants"].items():
        row = next((g for g in contract["genes"] if g["name"] == gene
                    or gene.startswith(g["name"])), None)
        assert row is not None, f"{case['id']}: {gene} is not in the profile"
        assert mutation in [v["mutation"] for v in row["variants"]], \
            f"{case['id']}: {mutation} not recorded against {gene}"

    unresolved = {u["text"] for u in contract["unresolved_inputs"]}
    assert set(expect["unresolved"]) <= unresolved, case["id"]
    return contract


@pytest.mark.parametrize("case", ISOLATES, ids=IDS)
def test_pipeline_produces_the_expected_classes(case, synthetic):
    """Machinery, not biology: see this module's docstring."""
    profile = _profile_for(case, synthetic[case["id"]])
    contract = _assert_expectations(case, profile)
    assert contract["input"]["species"] == case["species"]
    assert len(contract["genes"]) == len(case["genes"])


@pytest.mark.parametrize("case", ISOLATES, ids=IDS)
def test_the_decoy_determinant_never_leaks_into_a_profile(case, synthetic):
    """A class the case forbids exists in the release but belongs to a gene nobody asked
    for, so its absence is a real result rather than an artefact of a thin fixture."""
    profile = _profile_for(case, synthetic[case["id"]])
    classes = {t["name"] for t in profile.contract["defeated_classes"]}
    genes = {g["name"] for g in profile.contract["genes"]}
    assert DECOY_CLASS not in classes
    assert DECOY_GENE not in genes


def test_the_decoy_would_be_caught_if_it_did_leak(synthetic):
    """Prove the forbidden-class assertion can fail, so a green run means something."""
    case = BY_ID["mrsa-meca"]
    profile = _profile_for(case, synthetic[case["id"]])
    tampered = json.loads(json.dumps(profile.contract))
    tampered["defeated_classes"].append(
        {"aro_id": "ARO:9400099", "name": case["expect"]["not_defeated_classes"][0],
         "gene_aro_ids": [], "evidence_ids": []})
    profile.contract = tampered
    with pytest.raises(AssertionError, match="must not defeat"):
        _assert_expectations(case, profile)


@pytest.mark.parametrize("case", ISOLATES, ids=IDS)
def test_each_case_yields_a_valid_contract(case, synthetic):
    from tests.test_profile import check_contract  # noqa: PLC0415

    check_contract(_profile_for(case, synthetic[case["id"]]))


# ----------------------------------------------------------------- biology layer

def _real_release():
    root = DEFAULT_DIR / "releases"
    found = sorted(root.glob("*/manifest.json")) if root.exists() else []
    return found[-1].parent if found else None


real = pytest.mark.skipif(
    _real_release() is None,
    reason="build a release first: uv run python -m htb_resistance build")


@real
@pytest.mark.parametrize("case", ISOLATES, ids=IDS)
def test_real_card_gives_each_isolate_its_expected_classes(case):
    """This is the check that means something: expectations against curated CARD data."""
    profile = _profile_for(case, _real_release())
    assert profile.contract["unresolved_inputs"] == [], \
        f"{case['id']}: {profile.contract['unresolved_inputs']}"
    _assert_expectations(case, profile)


@real
@pytest.mark.parametrize("case", [c for c in ISOLATES if c["verified_aro_ids"]],
                         ids=lambda c: c["id"])
def test_real_card_matches_the_ids_confirmed_elsewhere_in_this_repo(case):
    """The ids in tests/fixtures/resistance_profile.json must be what CARD actually says."""
    contract = _profile_for(case, _real_release()).contract
    actual = {g["name"]: g["aro_id"] for g in contract["genes"]}
    for term in contract["genes"]:
        for item in term["mechanisms"] + term["defeated_classes"]:
            actual[item["name"]] = item["aro_id"]
    for name, aro_id in case["verified_aro_ids"].items():
        assert actual.get(name) == aro_id, f"{case['id']}: {name} is {actual.get(name)}, not {aro_id}"


@real
def test_real_card_separates_the_esbl_from_the_carbapenemase():
    """The clinically important contrast, on real data: an ESBL must not defeat carbapenems."""
    esbl = _profile_for(BY_ID["ctx-m-producer"], _real_release()).contract
    kpc = _profile_for(BY_ID["kpc-klebsiella"], _real_release()).contract
    assert "carbapenem" not in {t["name"] for t in esbl["defeated_classes"]}
    assert "carbapenem" in {t["name"] for t in kpc["defeated_classes"]}
