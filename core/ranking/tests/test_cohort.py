"""Offline checks for cohort collection; synthetic labels never enter real data."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from ranking.artifacts import file_record, write_json
from ranking.cohort import (
    alias_index, case_exclusions, check_version, extract_labels, map_candidate,
    mechanism_scope, resolve_name, verify_bundle,
)
from ranking.data import Drug, normalise_targets
from ranking.references import parse_references
from ranking.cohort_report import interpret_mechanism


def indication(identifier="i1", drug="CHEMBL1", disease="MONDO_1"):
    return {"id": identifier, "drugId": drug, "diseaseId": disease,
            "maxClinicalStage": "APPROVAL", "clinicalReportIds": ["r1"]}


def report(**updates):
    return {"id": "r1", "source": "FDA", "clinicalStage": "APPROVAL", "type": "INDICATION",
            "origin": "DRUG_LABEL", "url": "https://example.org/regulatory/r1", "year": 2020,
            "drugs": [{"drugId": "CHEMBL1"}], "diseases": [{"diseaseId": "MONDO_1"}], **updates}


def extract(rows=None, reports=None, eligible=None, aliases=None, parents=None):
    return extract_labels(rows or [indication()], reports or {"r1": report()},
                          {"CHEMBL1"} if eligible is None else eligible, aliases or {}, parents or {}, "26.09")


class LabelIngestionTests(unittest.TestCase):
    def test_exact_regulatory_record_preserves_provenance_and_eligibility(self):
        accepted, rejected = extract()
        self.assertFalse(rejected)
        row = accepted[0]
        self.assertEqual(row["source_release"], "opentargets-26.09")
        self.assertEqual(row["indication_record_id"], "i1")
        self.assertEqual(row["evidence_type"], "regulatory_indication_approval")
        self.assertTrue(row["eligible"])
        self.assertEqual(row["reports"][0]["url"], "https://example.org/regulatory/r1")
        self.assertEqual(row["reports"][0]["year"], 2020)

    def test_approval_stage_alone_and_trials_are_not_regulatory_labels(self):
        for updates in ({"source": "ClinicalTrials.gov"}, {"source": "TTD"},
                        {"clinicalStage": "PHASE_3"}, {"type": "ADVERSE_EVENT"}, {"url": None}):
            with self.subTest(updates=updates):
                accepted, rejected = extract(reports={"r1": report(**updates)})
                self.assertFalse(accepted)
                self.assertEqual(rejected[0]["reason"], "no_exact_pair_regulatory_approval_report_with_url")

    def test_trial_indication_does_not_gain_approval_from_drug_global_status(self):
        row = indication()
        row["maxClinicalStage"] = "PHASE_3"
        accepted, rejected = extract([row])
        self.assertFalse(accepted)
        self.assertEqual(rejected[0]["reason"], "indication_not_approval")

    def test_report_membership_must_match_both_entities(self):
        for updates in ({"drugs": [{"drugId": "CHEMBL9"}]}, {"diseases": [{"diseaseId": "MONDO_9"}]}):
            self.assertFalse(extract(reports={"r1": report(**updates)})[0])

    def test_missing_link_and_regulatory_withdrawal_are_explicit(self):
        row = indication()
        row["clinicalReportIds"].append("r2")
        accepted, rejected = extract([row])
        self.assertFalse(accepted)
        self.assertEqual(rejected[0]["missing_report_ids"], ["r2"])
        accepted, rejected = extract([row], {"r1": report(), "r2": report(id="r2", clinicalStage="WITHDRAWAL")})
        self.assertFalse(accepted)
        self.assertEqual(rejected[0]["reason"], "regulator_withdrawal")

    def test_outside_eligible_labels_are_preserved_not_silently_dropped(self):
        accepted, rejected = extract(eligible=set())
        self.assertFalse(rejected)
        self.assertFalse(accepted[0]["eligible"])
        self.assertEqual(accepted[0]["candidate_id"], "CHEMBL1")
        self.assertEqual(accepted[0]["eligibility_reason"], "outside_fixed_candidate_universe")

    def test_duplicate_indications_rejected_duplicate_report_links_deduplicated(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            extract([indication(), indication()])
        row = indication()
        row["clinicalReportIds"].append("r1")
        self.assertEqual(len(extract([row])[0][0]["reports"]), 1)

    def test_extraction_is_order_independent_and_does_not_require_scores(self):
        rows = [indication(), indication("i2")]
        reports = {"r1": report(), "r2": report(id="r2", source="PMDA")}
        for row in rows:
            row["clinicalReportIds"] = ["r2", "r1"]
        before = deepcopy((rows, reports))
        first = extract(rows, reports)
        for row in rows:
            row["clinicalReportIds"].reverse()
        self.assertEqual(first, extract(list(reversed(rows)), dict(reversed(list(reports.items())))))
        self.assertEqual(before[1], reports)


class IdentityAndSuitabilityTests(unittest.TestCase):
    def test_unique_exact_names_precede_synonyms_and_ambiguity_fails(self):
        diseases = [{"id": "MONDO_1", "name": "asthma", "exactSynonyms": []},
                    {"id": "MONDO_2", "name": "other", "exactSynonyms": ["asthma", "alias"]}]
        self.assertEqual(resolve_name("Asthma", diseases)["id"], "MONDO_1")
        self.assertEqual(resolve_name("alias", diseases)["id"], "MONDO_2")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            resolve_name("alias", diseases + [{"id": "MONDO_3", "name": "third", "exactSynonyms": ["alias"]}])
        with self.assertRaisesRegex(ValueError, "missing"):
            resolve_name("unrecorded", diseases)

    def test_alias_requires_unique_ownership_and_verified_parent(self):
        eligible = {"CHEMBL1"}
        aliases = {"CHEMBL2": {"CHEMBL1"}}
        self.assertEqual(map_candidate("CHEMBL1", eligible, aliases, {})[2], "exact_candidate_id")
        self.assertFalse(map_candidate("CHEMBL2", eligible, aliases, {})[1])
        self.assertTrue(map_candidate("CHEMBL2", eligible, aliases, {"CHEMBL2": "CHEMBL1"})[1])
        self.assertFalse(map_candidate("CHEMBL2", eligible, {"CHEMBL2": {"CHEMBL1", "CHEMBL3"}}, {"CHEMBL2": "CHEMBL1"})[1])
        with self.assertRaises(ValueError):
            map_candidate("drug name", eligible, aliases, {})

    def test_human_mechanism_pathogen_nonprotein_and_unknown_are_distinct(self):
        def drug(targets, unmapped):
            return Drug("CHEMBL1", "test", normalise_targets(targets), ["FDA"], ["CHEMBL1"], unmapped)
        human = drug([{"target_id": "ENSG00000000001", "support": ["mechanism"]}], [{"reason": "non_human_target"}])
        self.assertEqual(mechanism_scope(human)["classification"], "human_mechanism_supplied")
        self.assertEqual(mechanism_scope(human)["nonhuman_items"], 1)
        for reason, expected in (("non_human_target", "nonhuman_mechanism_without_human_mechanism"),
                                 ("non_protein_target", "nonprotein_mechanism_without_human_mechanism")):
            self.assertEqual(mechanism_scope(drug([], [{"reason": reason}]))["classification"], expected)
        self.assertEqual(mechanism_scope(drug([], []))["classification"], "mechanism_or_mapping_unresolved")
        self.assertEqual(mechanism_scope(None)["classification"], "outside_candidate_source")

    def test_case_exclusion_depends_on_declared_coverage_not_ranking_performance(self):
        protocol = {"minimum_positive_evidence_targets": 25, "minimum_lcc_disease_targets": 20,
                    "minimum_eligible_human_mechanism_references": 1}
        case = {"positive_evidence_targets": 50, "retained_targets": 40, "eligible_human_mechanism_references": 2}
        self.assertFalse(case_exclusions(case, protocol))
        case.update(retained_targets=0, eligible_human_mechanism_references=0)
        self.assertEqual(case_exclusions(case, protocol), ["insufficient_lcc_disease_targets", "no_eligible_human_mechanism_reference"])

    def test_api_version_must_be_exactly_pinned(self):
        check_version({"meta": {"dataVersion": {"year": "26", "month": "09"}}}, "26.09")
        for payload in ({}, {"meta": {"dataVersion": {"year": "26", "month": "12"}}}):
            with self.assertRaisesRegex(ValueError, "release mismatch"):
                check_version(payload, "26.09")

    def test_alias_ownership_is_recorded_without_name_matching(self):
        a = Drug("CHEMBL1", "same", normalise_targets([]), ["FDA"], ["CHEMBL2"], [])
        b = Drug("CHEMBL3", "same", normalise_targets([]), ["FDA"], ["CHEMBL2"], [])
        self.assertEqual(alias_index([a, b])["CHEMBL2"], {"CHEMBL1", "CHEMBL3"})

    def test_null_organism_metal_is_not_interpreted_as_pathogen(self):
        scope = {"human_mechanism_targets": [], "classification": "nonhuman_mechanism_without_human_mechanism"}
        self.assertEqual(interpret_mechanism(scope, [{"target_type": "METAL", "organism": None}]),
                         "nonprotein_metal_entity_in_supplied_mechanism")
        self.assertEqual(interpret_mechanism(scope, [{"target_type": "PROTEIN NUCLEIC-ACID COMPLEX", "organism": "Bacteria"}]),
                         "nonhuman_organism_target_in_supplied_mechanism")
        self.assertEqual(interpret_mechanism(scope, []), scope["classification"])


class FreezeTests(unittest.TestCase):
    def test_sealed_inputs_and_code_detect_tampering_and_accept_reference_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refs = root / "references.json"
            write_json(refs, {"format_version": 1, "definition": "Synthetic approval records", "cases": [
                {"disease_id": "MONDO_1", "known_candidate_ids": ["CHEMBL1"]}]})
            code = root / "collector.py"
            code.write_text("pass\n")
            write_json(root / "freeze.json", {"files": {"references.json": file_record(refs)},
                                             "external_files": {str(code): file_record(code)}, "included_case_ids": ["MONDO_1"]})
            self.assertEqual(verify_bundle(root)["included_case_ids"], ["MONDO_1"])
            self.assertEqual(parse_references(__import__("json").loads(refs.read_text())), {"MONDO_1": {"CHEMBL1"}})
            code.write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "external"):
                verify_bundle(root)
            code.write_text("pass\n")
            refs.write_text("{}")
            with self.assertRaisesRegex(ValueError, "Frozen file"):
                verify_bundle(root)


if __name__ == "__main__":
    unittest.main()
