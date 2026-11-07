"""Offline tests use projected, recorded OT 26.09 / ChEMBL 37 source rows."""

from tests.conftest import FIXTURES
from copy import deepcopy
import json
from pathlib import Path
import re

import httpx
import pytest

from pipeline.drugs import (
    APPROVAL_SOURCES, Cache, CHEMBL_URL, OT_RELEASE, approval_rows,
    build_universe, is_disease_id, load_approval_overrides, parent_groups, run,
)


DATA = Path(__file__).parent / "data" / "drugs"


@pytest.fixture
def recorded():
    sample = json.loads((DATA / "recorded.json").read_text())
    sample.pop("provenance")
    for name in ("clinical_indication", "clinical_report"):
        sample["tables"][name] = json.loads((DATA / f"{name}.json").read_text())["rows"]
    return sample


def by_id(result):
    return {row["drug_id"]: row for row in result["drugs"]}


def test_regulator_universe_and_contract(recorded):
    result = build_universe(**recorded)
    drugs = by_id(result)
    assert set(drugs) == {
        "CHEMBL1201580", "CHEMBL1789941", "CHEMBL2105759",
        "CHEMBL3137309", "CHEMBL4594381", "CHEMBL852",
    }
    navitoclax = next(row for row in recorded["tables"]["drug_molecule"]
                      if row["id"] == "CHEMBL443684")
    assert navitoclax["name"] == "NAVITOCLAX"
    assert "CHEMBL443684" not in drugs
    assert any(row["drugId"] == "CHEMBL443684" and row["maxClinicalStage"] == "APPROVAL"
               for row in recorded["tables"]["clinical_indication"])
    fixture = json.loads((FIXTURES / "drug_targets.json").read_text())
    assert result.keys() == fixture.keys()
    assert result["rules"] == fixture["rules"]
    assert result["releases"] == fixture["releases"]
    target_keys = fixture["drugs"][0]["targets"][0].keys()
    for drug in drugs.values():
        assert drug.keys() == fixture["drugs"][0].keys()
        assert drug["approval"].keys() == fixture["drugs"][0]["approval"].keys()
        assert drug["approval"]["sources"]
        assert set(drug["approval"]["sources"]) <= set(APPROVAL_SOURCES)
        assert re.fullmatch(r"CHEMBL[0-9]+", drug["drug_id"])
        assert all(is_disease_id(value)
                   for value in drug["approval"]["disease_ids"])
        for target in drug["targets"]:
            assert target.keys() == target_keys
            assert re.fullmatch(r"ENSG[0-9]{11}", target["target_id"])
            assert target["support"] and set(target["support"]) <= {"mechanism", "bioactivity"}
            assert target["median_pchembl"] is None or isinstance(target["median_pchembl"], (int, float))
            assert target["n_activities"] is None or isinstance(target["n_activities"], int)
        for item in drug["unmapped"]:
            assert item.keys() == {"source", "item", "reason"}
            assert all(isinstance(value, str) and value for value in item.values())
    assert result["coverage"] == {
        "drugs": 6, "drugs_with_targets": 5, "unmapped_items": 5,
        "approval_overrides": 0, "unmapped_approval_overrides": [],
        "unmapped_by_reason": {"missing_uniprot_mapping": 1,
                               "non_protein_target": 1, "non_single_protein_target": 3},
    }


def test_salts_and_bad_parent_do_not_inherit_mechanisms(recorded):
    drugs = by_id(build_universe(**recorded))
    ruxolitinib, deuruxolitinib = drugs["CHEMBL1789941"], drugs["CHEMBL4594381"]
    assert ruxolitinib["source_chembl_ids"] == ["CHEMBL1789941", "CHEMBL1795071"]
    assert deuruxolitinib["source_chembl_ids"] == ["CHEMBL4594381", "CHEMBL4594382"]
    assert {row["target_id"] for row in ruxolitinib["targets"]} == {
        "ENSG00000162434", "ENSG00000096968",
    }
    assert {row["target_id"] for row in deuruxolitinib["targets"]} == {
        "ENSG00000162434", "ENSG00000096968", "ENSG00000105639", "ENSG00000105397",
    }
    # The bad salt's FDA report must not become a ruxolitinib approval either.
    assert "FDA" not in ruxolitinib["approval"]["sources"]
    assert deuruxolitinib["approval"] == {"sources": ["FDA"], "disease_ids": ["MONDO_0005340"]}


def test_approval_diseases_are_complete_parent_and_salt_union(recorded):
    ruxolitinib = by_id(build_universe(**recorded))["CHEMBL1789941"]
    assert ruxolitinib["approval"]["disease_ids"] == [
        "EFO_0004251", "MONDO_0008661", "MONDO_0009692", "MONDO_0009891",
        "MONDO_0013730", "MONDO_0044903",
    ]


def test_dna_is_one_unmapped_item_not_a_guessed_gene(recorded):
    drug = by_id(build_universe(**recorded))["CHEMBL852"]
    assert set(drug["source_chembl_ids"]) == {"CHEMBL852", "CHEMBL1200863"}
    assert drug["targets"] == []
    assert drug["unmapped"] == [{"source": "mechanism", "item": "DNA", "reason": "non_protein_target"}]


def test_baricitinib_tyk2_is_real_bioactivity_not_fixture_statistics(recorded):
    drug = by_id(build_universe(**recorded))["CHEMBL2105759"]
    targets = {row["target_id"]: row for row in drug["targets"]}
    assert targets["ENSG00000105397"] == {
        "target_id": "ENSG00000105397", "name": "TYK2", "support": ["bioactivity"],
        "action_type": None, "target_type": "single protein",
        "median_pchembl": 7.28, "n_activities": 13,
    }
    assert targets["ENSG00000162434"]["support"] == ["mechanism", "bioactivity"]
    assert targets["ENSG00000162434"]["median_pchembl"] == 8.23
    assert targets["ENSG00000162434"]["n_activities"] == 26


def test_approval_requires_stage_and_attached_regulator_report():
    reports = [{"id": "r1", "source": "FDA"}, {"id": "r2", "source": "ATC"}]
    base = {"drugId": "CHEMBL1", "diseaseId": "MONDO:0005340", "maxClinicalStage": "APPROVAL"}
    assert not approval_rows([{**base, "clinicalReportIds": ["r2"]}], reports)
    assert not approval_rows([{**base, "clinicalReportIds": ["missing"]}], reports)
    assert not approval_rows([{**base, "maxClinicalStage": "PHASE_3", "clinicalReportIds": ["r1"]}], reports)
    result = approval_rows([{**base, "clinicalReportIds": ["r1"]}], reports)
    assert result["CHEMBL1"]["disease_ids"] == {"MONDO_0005340"}
    missing = approval_rows([{**base, "diseaseId": None, "clinicalReportIds": ["r1"]}], reports)
    assert missing["CHEMBL1"]["unmapped"][0]["reason"] == "missing_disease_mapping"


def test_distinct_parents_and_conflicting_hierarchies_never_merge():
    molecules = [
        {"id": "CHEMBL1", "parentId": None}, {"id": "CHEMBL2", "parentId": None},
        {"id": "CHEMBL3", "parentId": "CHEMBL1"},
    ]
    cb = [{"molecule_chembl_id": "CHEMBL3", "molecule_hierarchy": {"parent_chembl_id": "CHEMBL2"}}]
    groups, problems = parent_groups(molecules, cb)
    assert groups == {"CHEMBL1": ["CHEMBL1"], "CHEMBL2": ["CHEMBL2"], "CHEMBL3": ["CHEMBL3"]}
    assert problems == {"CHEMBL3": "ambiguous_parent"}
    groups, problems = parent_groups([{"id": "CHEMBL4", "parentId": "CHEMBL5"}], [])
    assert groups == {"CHEMBL4": ["CHEMBL4"]}
    assert problems == {"CHEMBL4": "missing_parent"}


@pytest.mark.parametrize("values,expected", [([5, 6, 8], None), ([6, 8], 7), ([7, 7, 8], 7)])
def test_a7_median_threshold_uses_all_qualifying_rows(recorded, values, expected):
    recorded["activities"] = {"CHEMBL2105759": [
        {"target_chembl_id": "CHEMBL3553", "pchembl_value": str(value)} for value in values
    ]}
    drug = by_id(build_universe(**recorded))["CHEMBL2105759"]
    tyk2 = next((row for row in drug["targets"] if row["target_id"] == "ENSG00000105397"), None)
    if expected is None:
        assert tyk2 is None
    else:
        assert tyk2["median_pchembl"] == expected
        assert tyk2["n_activities"] == len(values)


def test_biologics_keep_mechanisms_without_bioactivity_expansion(recorded):
    recorded["activities"]["CHEMBL1201580"] = [
        {"target_chembl_id": "CHEMBL3553", "pchembl_value": "9"},
    ]
    drug = by_id(build_universe(**recorded))["CHEMBL1201580"]
    assert [(target["target_id"], target["support"]) for target in drug["targets"]] == [
        ("ENSG00000232810", ["mechanism"]),
    ]


@pytest.mark.parametrize("change,reason", [
    ("missing", "missing_uniprot_mapping"),
    ("ambiguous", "ambiguous_uniprot_mapping"),
    ("non_human", "non_human_target"),
])
def test_uniprot_mapping_never_falls_back_to_symbols(recorded, change, reason):
    recorded["activities"] = {"CHEMBL2105759": [{"target_chembl_id": "CHEMBL3553", "pchembl_value": "8"}]}
    if change == "non_human":
        next(t for t in recorded["chembl_targets"] if t["target_chembl_id"] == "CHEMBL3553")["organism"] = "Mus musculus"
    else:
        tyk2 = next(t for t in recorded["tables"]["target"] if t["id"] == "ENSG00000105397")
        if change == "missing":
            tyk2["proteinIds"] = []
        else:
            duplicate = deepcopy(tyk2)
            duplicate["id"] = "ENSG99999999999"
            recorded["tables"]["target"].append(duplicate)
    drug = by_id(build_universe(**recorded))["CHEMBL2105759"]
    assert "ENSG00000105397" not in {t["target_id"] for t in drug["targets"]}
    assert {"source": "bioactivity", "item": "CHEMBL3553", "reason": reason} in drug["unmapped"]


def test_multiple_chembl_targets_for_one_gene_are_not_guessed(recorded):
    original = next(t for t in recorded["chembl_targets"] if t["target_chembl_id"] == "CHEMBL3553")
    duplicate = {**deepcopy(original), "target_chembl_id": "CHEMBL9999999"}
    recorded["chembl_targets"].append(duplicate)
    recorded["activities"] = {"CHEMBL2105759": [
        {"target_chembl_id": "CHEMBL3553", "pchembl_value": "8"},
        {"target_chembl_id": "CHEMBL9999999", "pchembl_value": "9"},
    ]}
    drug = by_id(build_universe(**recorded))["CHEMBL2105759"]
    assert "ENSG00000105397" not in {t["target_id"] for t in drug["targets"]}
    assert sum(item["reason"] == "ambiguous_target_mapping" for item in drug["unmapped"]) == 2


@pytest.fixture
def mechanism_regressions():
    sample = json.loads((DATA / "mechanism_regressions.json").read_text())
    sample.pop("provenance")
    return sample


@pytest.mark.parametrize("path", ["opentargets", "chembl", "both"])
@pytest.mark.parametrize("target_type", ["single protein", "protein complex"])
def test_tagraxofusp_ambiguous_uniprot_is_dropped_once(mechanism_regressions, path, target_type):
    sample = mechanism_regressions
    # Also exercise the complex-constituent path with this recorded ambiguity.
    for row in sample["tables"]["drug_mechanism_of_action"]:
        if "ENSG00000185291" in row["targets"]:
            row["targetType"] = target_type
    next(row for row in sample["chembl_targets"] if row["target_chembl_id"] == "CHEMBL3712987")["target_type"] = target_type.upper()
    if path == "opentargets":
        sample["mechanisms"] = []
    elif path == "chembl":
        sample["tables"]["drug_mechanism_of_action"] = []
    result = build_universe(**sample)
    drug = by_id(result)["CHEMBL4297573"]
    assert {target["target_id"] for target in drug["targets"]} == {"ENSG00000167658"}
    assert drug["unmapped"] == [{
        "source": "mechanism", "item": "P26951", "reason": "ambiguous_uniprot_mapping",
    }]
    assert result["coverage"]["unmapped_by_reason"]["ambiguous_uniprot_mapping"] == 1


@pytest.mark.parametrize("path", ["opentargets", "chembl", "both"])
def test_risdiplam_rna_mechanism_never_becomes_protein_target(mechanism_regressions, path):
    sample = mechanism_regressions
    if path == "opentargets":
        sample["mechanisms"] = []
    elif path == "chembl":
        sample["tables"]["drug_mechanism_of_action"] = []
    drug = by_id(build_universe(**sample))["CHEMBL4297528"]
    assert drug["targets"] == []
    assert drug["unmapped"] == [{
        "source": "mechanism", "item": "SMN2 pre-mRNA", "reason": "non_protein_target",
    }]


def test_cache_follows_pages_and_replays_offline(tmp_path):
    seen = []

    def respond(request):
        seen.append(str(request.url))
        if request.url.path.endswith("status.json"):
            return httpx.Response(200, json={"chembl_db_version": "ChEMBL_37"})
        offset = int(request.url.params.get("offset", 0))
        return httpx.Response(200, json={
            "activities": [{"target_chembl_id": "CHEMBL3553", "pchembl_value": str(7 + offset)}],
            "page_meta": {"total_count": 2, "next": "/chembl/api/data/activity.json?offset=1" if offset == 0 else None},
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = Cache(tmp_path, client).pages("activity")
    assert len(result) == 2 and len(seen) == 3
    for path in tmp_path.rglob("*.json"):
        assert json.loads(path.read_text())["release"] == "chembl-37"

    def offline(request):
        pytest.fail("A cached replay must not use the network")

    with httpx.Client(transport=httpx.MockTransport(offline)) as client:
        assert Cache(tmp_path, client).pages("activity") == result


def test_incomplete_pagination_fails_instead_of_emitting_partial_universe(tmp_path):
    def respond(request):
        if request.url.path.endswith("status.json"):
            return httpx.Response(200, json={"chembl_db_version": "ChEMBL_37"})
        return httpx.Response(200, json={"targets": [], "page_meta": {"total_count": 1, "next": None}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="Incomplete target"):
            Cache(tmp_path, client).pages("target")


def test_new_requests_refuse_a_different_chembl_release(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"chembl_db_version": "ChEMBL_38"},
    ))) as client:
        with pytest.raises(ValueError, match="no longer release 37"):
            Cache(tmp_path, client).pages("target")
    assert not list(tmp_path.rglob("*.json"))


def test_retry_connection_reset_and_gateway_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.drugs.time.sleep", lambda _: None)
    attempts = []

    def respond(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ReadError("connection reset", request=request)
        return httpx.Response(503 if len(attempts) == 2 else 200, json={})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert Cache(tmp_path, client).request(CHEMBL_URL + "status.json").status_code == 200
    assert len(attempts) == 3


def test_http_404_is_not_retried(tmp_path):
    attempts = []

    def respond(request):
        attempts.append(request)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            Cache(tmp_path, client).request(CHEMBL_URL + "missing.json")
    assert len(attempts) == 1


def test_recorded_files_are_small_and_release_labelled():
    for path in DATA.glob("*.json"):
        assert path.stat().st_size < 200_000
        assert json.loads(path.read_text())["provenance"]["releases"] == [OT_RELEASE, "chembl-37"]


@pytest.mark.network
def test_live_full_universe_from_cache():
    """Explicit opt-in: may populate data/ and fetch the complete A7 universe."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        result = run(Cache(Path("data"), client))
    assert result["coverage"]["drugs"] > 1000
    drugs = by_id(result)
    assert "CHEMBL443684" not in drugs
    assert "CHEMBL4594382" not in drugs["CHEMBL1789941"]["source_chembl_ids"]
    assert any(t["target_id"] == "ENSG00000105397" and "bioactivity" in t["support"]
               for t in drugs["CHEMBL2105759"]["targets"])
    tagraxofusp = drugs["CHEMBL4297573"]
    assert not {"ENSG00000185291", "ENSG00000292332"} & {
        target["target_id"] for target in tagraxofusp["targets"]
    }
    assert [item for item in tagraxofusp["unmapped"] if item["reason"] == "ambiguous_uniprot_mapping"] == [
        {"source": "mechanism", "item": "P26951", "reason": "ambiguous_uniprot_mapping"},
    ]
    assert drugs["CHEMBL4297528"]["targets"] == []
    assert drugs["CHEMBL4297528"]["unmapped"] == [
        {"source": "mechanism", "item": "SMN2 pre-mRNA", "reason": "non_protein_target"},
    ]


def test_offline_cache_miss_never_uses_network(tmp_path):
    cache = Cache(tmp_path, None, offline=True)
    with pytest.raises(FileNotFoundError, match='Missing offline ChEMBL cache'):
        cache.get(CHEMBL_URL + 'status.json')


def test_covid_approval_gap_is_in_pinned_source_records():
    sample = json.loads((DATA.parent / 'covid_approvals.json').read_text())
    assert {r['drugId'] for r in sample['indications']} == {'CHEMBL2105759', 'CHEMBL1237022'}
    assert all(r['maxClinicalStage'] == 'PHASE_3' for r in sample['indications'])
    toci = next(r for r in sample['reports'] if r['id'] == 'emea/h/c/000955')
    assert {'diseaseFromSource': 'covid-19 virus infection', 'diseaseId': None} in toci['diseases']
    # Regulator reports on other indications or an unmapped source phrase cannot
    # supply a COVID-19 approval through an ID join.
    assert approval_rows(sample['indications'], sample['reports']) == {}


def test_verified_overrides_add_only_missing_indications(recorded):
    row = load_approval_overrides()[0]
    before = by_id(build_universe(**recorded))[row['drug_id']]
    result = build_universe(**recorded, overrides=[row])
    after = by_id(result)[row['drug_id']]
    assert after['approval']['disease_ids'] == sorted(
        before['approval']['disease_ids'] + [row['disease_id']])
    assert after['approval']['overrides'] == [{'disease_id': row['disease_id'], 'url': row['url']}]
    assert after['targets'] == before['targets']
    assert result['coverage']['approval_overrides'] == 1
    assert result['coverage']['unmapped_approval_overrides'] == []
    # An OT approval on any included salt remains OT data, not an override.
    recorded['tables']['clinical_indication'].append({
        'drugId': row['drug_id'], 'diseaseId': row['disease_id'],
        'maxClinicalStage': 'APPROVAL', 'clinicalReportIds': ['override-regression'],
    })
    recorded['tables']['clinical_report'].append({'id': 'override-regression', 'source': 'FDA'})
    result = build_universe(**recorded, overrides=[row])
    assert 'overrides' not in by_id(result)[row['drug_id']]['approval']
    assert result['coverage']['approval_overrides'] == 0


def test_override_only_drug_keeps_its_targets(recorded):
    row = load_approval_overrides()[0]
    before = by_id(build_universe(**recorded))[row['drug_id']]
    recorded['tables']['clinical_indication'] = [r for r in recorded['tables']['clinical_indication']
                                                if r['drugId'] != row['drug_id']]
    assert row['drug_id'] not in by_id(build_universe(**recorded))
    drug = by_id(build_universe(**recorded, overrides=[row]))[row['drug_id']]
    assert drug['approval'] == {'sources': ['FDA'], 'disease_ids': [row['disease_id']],
                               'overrides': [{'disease_id': row['disease_id'], 'url': row['url']}]}
    assert drug['targets'] == before['targets']


@pytest.mark.parametrize('mapping,reason', [
    ('absent', 'missing_parent_mapping'), ('missing', 'missing_parent_mapping'),
    ('ambiguous', 'ambiguous_parent'), ('salt', 'ambiguous_parent'),
])
def test_override_parent_is_never_guessed(recorded, mapping, reason):
    row = load_approval_overrides()[0]
    if mapping == 'absent':
        row['drug_id'] = 'CHEMBL999999999'
    elif mapping == 'salt':
        row['drug_id'] = 'CHEMBL1795071'
    else:
        molecule = next(r for r in recorded['chembl_molecules']
                        if r['molecule_chembl_id'] == row['drug_id'])
        molecule['molecule_hierarchy']['parent_chembl_id'] = (
            None if mapping == 'missing' else 'CHEMBL1789941')
    result = build_universe(**recorded, overrides=[row])
    assert result['coverage']['approval_overrides'] == 0
    assert result['coverage']['unmapped_approval_overrides'] == [{
        'drug_id': row['drug_id'], 'disease_id': row['disease_id'], 'reason': reason}]
    assert result['coverage']['unmapped_by_reason'][reason] >= 1
    assert result['coverage']['unmapped_items'] == sum(result['coverage']['unmapped_by_reason'].values())
    assert all('overrides' not in d['approval'] for d in result['drugs'])


def test_curated_overrides_match_recorded_fda_records():
    sample = json.loads((DATA.parent / 'fda_covid_approvals.json').read_text())
    assert load_approval_overrides() == sample['records']
    assert sample['provenance']['checked_on'] == '2026-10-25'


@pytest.mark.parametrize('change', [
    {'regulator': 'ATC'}, {'drug_id': 'baricitinib'}, {'disease_id': 'MONDO:0100096'},
    {'url': 'https://www.accessdata.fda.gov.evil.example/label.pdf'},
    {'url': 'http://www.accessdata.fda.gov/label.pdf'},
    {'approval_url': 'https://example.com/approval'}, {'label_text': ''},
    {'approval_date': '2022-05-11', 'checked_on': '2022-05-10'},
    {'checked_on': '9999-01-01'}, {'application_number': None},
])
def test_invalid_override_provenance_fails_closed(tmp_path, change):
    path = tmp_path / 'overrides.json'
    path.write_text(json.dumps([{**load_approval_overrides()[0], **change}]))
    with pytest.raises(ValueError):
        load_approval_overrides(path)


def test_duplicate_override_rejected(tmp_path):
    path = tmp_path / 'overrides.json'
    row = load_approval_overrides()[0]
    path.write_text(json.dumps([row, row]))
    with pytest.raises(ValueError, match='Duplicate'):
        load_approval_overrides(path)


@pytest.mark.parametrize('disease_id', ['NCIT_C74532', 'EFO_0001378', 'MONDO_0009693'])
def test_regulator_approval_preserves_alphanumeric_disease_ids(disease_id):
    row = {'drugId': 'CHEMBL1', 'diseaseId': disease_id, 'maxClinicalStage': 'APPROVAL',
           'clinicalReportIds': ['r1']}
    approval = approval_rows([row], [{'id': 'r1', 'source': 'FDA'}])['CHEMBL1']
    assert approval['disease_ids'] == {disease_id}
    assert approval['sources'] == {'FDA'}
    assert approval['unmapped'] == []
