"""Stage 2 arithmetic, missing-data, determinism and integration checks."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.sparse import csr_matrix, save_npz

from ranking.__main__ import main
from ranking.artifacts import Artifacts, file_record, write_json
from ranking.data import load_disease, load_drugs
from ranking.proximity import ConditionalNull, degree_bins, degree_matched_samples, nearest_distances
from ranking.scoring import RankingEngine, RankingSettings, assign_ranks, make_shortlist, rank_files


def gene(i):
    return f"ENSG{i:011d}"


def target(i, score=None):
    row = {"target_id": gene(i), "name": f"G{i}", "support": ["mechanism"], "action_type": "INHIBITOR"}
    if score is not None:
        row["evidence_only_score"] = score
    return row


def drug(i, targets):
    return {"drug_id": f"CHEMBL{i}", "name": f"Drug {i}", "targets": targets, "unmapped": [],
            "approval": {"sources": ["FDA"], "disease_ids": ["TEST_42"]}, "source_chembl_ids": [f"CHEMBL{i}"]}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "stage1"
        self.bundle.mkdir()
        # Eight-gene path plus one isolated mapped gene. Distances are known
        # exactly, saved once and reused; Stage 2 never runs shortest_path.
        row = np.arange(7)
        graph = csr_matrix((np.ones(7, dtype=np.uint8), (row, row + 1)), shape=(9, 9))
        graph = graph + graph.T
        np.save(self.bundle / "distances.npy", np.abs(np.arange(8)[:, None] - np.arange(8)).astype(np.uint8))
        save_npz(self.bundle / "graph.npz", graph)
        write_json(self.bundle / "index.json", {"graph_gene_ids": [gene(i) for i in range(1, 10)],
                   "distance_gene_ids": [gene(i) for i in range(1, 9)], "component_labels": [0] * 8 + [1]})
        write_json(self.bundle / "mapping_exclusions.json", {})
        self.manifest = {"format_version": 1, "releases": ["string-12.5", "opentargets-test"],
                         "distances": {"shape": [8, 8], "dtype": "uint8", "unreachable_sentinel": 255},
                         "files": {name: file_record(self.bundle / name) for name in ("graph.npz", "index.json", "mapping_exclusions.json", "distances.npy")}}
        write_json(self.bundle / "manifest.json", self.manifest)
        saved = np.load(self.bundle / "distances.npy", mmap_mode="r")
        self.artifacts = Artifacts(graph, tuple(gene(i) for i in range(1, 10)), tuple(gene(i) for i in range(1, 9)), np.array([0] * 8 + [1]), saved, self.manifest)
        self.addCleanup(self.artifacts.close)
        self.disease_path = self.root / "disease_targets_TEST_42.json"
        self.drugs_path = self.root / "drug_targets.json"
        self.disease_payload = {"disease_id": "TEST_42", "disease_name": "Synthetic Disease", "release": "opentargets-test",
                                "rule": {"score": "evidence_only", "top_n": 50, "excluded_datasources": ["clinical_precedence", "cancer_biomarkers"]},
                                "targets": [target(1, 0.8)]}
        self.drug_payload = {"releases": ["opentargets-test", "chembl-test"], "rules": {},
                             "drugs": [drug(1, [target(1)]), drug(2, [target(2)]), drug(3, [target(7)])]}
        self.settings = RankingSettings(min_bin_size=1, seed=27)

    def inputs(self):
        write_json(self.disease_path, self.disease_payload)
        write_json(self.drugs_path, self.drug_payload)
        return load_disease(self.disease_path, "TEST_42"), load_drugs(self.drugs_path)

    def rank(self, settings=None):
        disease, drugs = self.inputs()
        return RankingEngine(self.artifacts, settings or self.settings).rank(disease, drugs)

    def test_raw_distance_direct_overlap_and_multi_target_mean(self):
        self.disease_payload["targets"].append(target(8, 0.4))
        self.drug_payload["drugs"].append(drug(4, [target(2), target(4)]))
        result = self.rank()
        candidates = {c["candidate_id"]: c for c in result["candidates"]}
        self.assertEqual(candidates["CHEMBL1"]["network"]["mean_distance"], 0)
        self.assertEqual(candidates["CHEMBL1"]["network"]["direct_overlap_count"], 1)
        self.assertEqual(candidates["CHEMBL4"]["network"]["mean_distance"], 2)
        self.assertEqual(candidates["CHEMBL1"]["shared_target_count"], 1)
        self.assertEqual(candidates["CHEMBL1"]["direct_evidence"]["score"], 0.8)

    def test_top_50_is_chosen_before_network_filtering_and_evidence_can_fallback(self):
        self.disease_payload["targets"] = [target(i, 1 - (i - 100) / 100) for i in range(100, 150)] + [target(1, 0.1)]
        result = self.rank()
        self.assertEqual(len(result["disease"]["selected_target_ids"]), 50)
        self.assertNotIn(gene(1), result["disease"]["selected_target_ids"])
        self.assertEqual(result["disease"]["coverage"]["retained"], 0)
        self.assertEqual(result["disease"]["coverage"]["total"], 51)
        self.assertTrue(all(c["status"] == "not_scorable" and c["network"] is None for c in result["candidates"]))
        self.assertIn("CHEMBL1", result["shortlist"])
        self.assertEqual(result["candidates"][0]["selected_by"], ["evidence"])

    def test_duplicate_missing_invalid_and_disconnected_target_coverage(self):
        self.drug_payload["drugs"][0]["targets"] = [target(2), target(2), target(9), target(99), {"target_id": "TP53"}]
        self.drug_payload["drugs"][0]["unmapped"] = [{"source": "mechanism", "item": "DNA", "reason": "non_protein_target"}]
        coverage = self.rank()["candidates"][0]["coverage"]
        self.assertEqual([coverage[k] for k in ("total", "mapped", "retained", "excluded")], [4, 2, 1, 3])
        self.assertEqual(coverage["duplicates_removed"], 1)
        self.assertEqual(coverage["upstream_unmapped_items"], 1)
        self.assertEqual(coverage["excluded_by_reason"], {"invalid_target_id": 1, "not_in_graph": 1, "outside_largest_component": 1})

    def test_no_drug_targets_returns_not_scorable(self):
        self.drug_payload["drugs"][0]["targets"] = []
        candidate = self.rank()["candidates"][0]
        self.assertEqual(candidate["status"], "not_scorable")
        self.assertIsNone(candidate["network"])
        self.assertEqual(candidate["unscorable_reason"], "no_retained_drug_targets")

    def test_missing_disease_scores_do_not_produce_rankings(self):
        self.disease_payload["targets"] = [target(1), target(2, float("nan"))]
        # JSON nonfinite input is deliberately tested independently of writer.
        self.disease_payload["targets"][1]["evidence_only_score"] = "missing"
        result = self.rank()
        self.assertEqual(result["shortlist"], [])
        self.assertTrue(all(c["direct_evidence_rank"] is None and c["direct_evidence"]["score"] is None for c in result["candidates"]))
        self.assertEqual(result["summary"]["statuses"], {"not_scorable": 3})

    def test_lower_z_scores_rank_first(self):
        result = self.rank()
        near, far = result["candidates"][1:3]
        self.assertLess(near["network"]["degree_matched_z"], far["network"]["degree_matched_z"])
        self.assertLess(near["network"]["rank"], far["network"]["rank"])
        self.assertEqual(near["network"]["randomisation_mean"], far["network"]["randomisation_mean"])

    def test_zero_variance_preserves_distance_with_no_fabricated_z(self):
        self.drug_payload["drugs"] = [drug(1, [target(i) for i in range(1, 9)])]
        candidate = self.rank()["candidates"][0]
        self.assertEqual(candidate["status"], "distance_only")
        self.assertEqual(candidate["network"]["mean_distance"], 3.5)
        self.assertEqual(candidate["network"]["randomisation_std"], 0)
        self.assertIsNone(candidate["network"]["degree_matched_z"])
        self.assertEqual(candidate["network"]["warning"], "zero_null_variance")

    def test_insufficient_degree_pool_retains_raw_distance_and_evidence(self):
        result = self.rank(RankingSettings(min_bin_size=100))
        self.assertTrue(all(c["status"] == "distance_only" for c in result["candidates"]))
        self.assertEqual(result["candidates"][0]["network"]["warning"], "insufficient_degree_matched_pool")
        self.assertIsNone(result["candidates"][0]["network"]["degree_matched_z"])
        self.assertEqual(result["shortlist"], ["CHEMBL1"])

    def test_ties_input_order_and_candidate_universe_do_not_change_scores(self):
        self.drug_payload["drugs"].append(drug(10, [target(2), target(2)]))
        first = self.rank()
        self.drug_payload["drugs"].reverse()
        self.disease_payload["targets"].reverse()
        second = self.rank()
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual(first["shortlist"], second["shortlist"])
        by_id = {c["candidate_id"]: c for c in first["candidates"]}
        self.assertLess(by_id["CHEMBL10"]["network"]["rank"], by_id["CHEMBL2"]["network"]["rank"])
        previous = by_id["CHEMBL2"]["network"]
        self.drug_payload["drugs"].append(drug(99, [target(3), target(5)]))
        current = next(c for c in self.rank()["candidates"] if c["candidate_id"] == "CHEMBL2")["network"]
        self.assertEqual({k: v for k, v in previous.items() if k != "rank"}, {k: v for k, v in current.items() if k != "rank"})

    def test_approval_scope_and_treatment_docking_label_invariance(self):
        before = self.rank()["candidates"]
        for row in self.drug_payload["drugs"]:
            row["approval"]["disease_ids"] = ["OTHER_123"]
            row["docking_score"] = -999
            row["known_treatment"] = True
        self.assertEqual(before, self.rank()["candidates"])
        self.drug_payload["drugs"].append(drug(999, [target(1)]))
        self.drug_payload["drugs"][-1]["approval"]["sources"] = ["ATC"]
        result = self.rank()
        self.assertEqual(result["summary"]["eligible_candidates"], 3)
        self.assertEqual(result["excluded_candidates"][0]["reason"], "no_regulator_backed_approval")

    def test_baseline_breadth_shared_counts_and_duplicate_disease_scores(self):
        self.disease_payload["targets"] = [target(1, 0.8), target(8, 0.4), target(1, 0.2)]
        self.drug_payload["drugs"] = [drug(1, [target(1)]), drug(2, [target(1), target(8)])]
        result = self.rank()
        a, b = result["candidates"]
        self.assertEqual(a["direct_evidence"]["score"], b["direct_evidence"]["score"])
        self.assertLess(b["direct_evidence_rank"], a["direct_evidence_rank"])
        self.assertEqual(b["shared_target_count"], 2)
        self.assertEqual(result["disease"]["coverage"]["duplicates_removed"], 1)
        self.assertEqual(result["disease"]["coverage"]["total"], 2)

    def test_release_id_schema_and_missing_file_failures(self):
        disease, drugs = self.inputs()
        disease.release = "opentargets-mismatch"
        with self.assertRaisesRegex(ValueError, "releases"):
            RankingEngine(self.artifacts).rank(disease, drugs)
        with self.assertRaisesRegex(ValueError, "not 'TEST_43'"):
            load_disease(self.disease_path, "TEST_43")
        with self.assertRaisesRegex(FileNotFoundError, "missing"):
            load_disease(self.root / "absent.json", "TEST_43")
        self.disease_payload["rule"]["score"] = "default"
        with self.assertRaisesRegex(ValueError, "evidence_only"):
            self.inputs()

    def test_saved_artifact_integration_and_cli_roundtrip(self):
        self.inputs()
        with patch("ranking.network.precompute_distances", side_effect=AssertionError("Stage 1 must not run")):
            result = rank_files(self.bundle, self.drugs_path, self.disease_path, "TEST_42", self.settings)
        self.assertEqual(result["provenance"]["method"], "conditional_degree_matched_drug_targets_v1")
        output = self.root / "rank.json"
        argv = ["ranking", "rank", "--artifacts", str(self.bundle), "--data-dir", str(self.root), "--disease-id", "TEST_42", "--min-bin-size", "1", "--seed", "27", "--output", str(output)]
        with patch("sys.argv", argv), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["candidates"], result["candidates"])
        self.assertEqual(saved["shortlist"], result["shortlist"])


class NullAndShortlistTests(unittest.TestCase):
    def test_degree_bins_merge_tail_and_preserve_whole_degree_groups(self):
        degrees = np.repeat([1, 2, 3], [100, 100, 5])
        bins, membership = degree_bins(degrees, 100)
        self.assertEqual([len(b) for b in bins], [100, 105])
        self.assertTrue(np.all(membership >= 0))
        self.assertEqual(len(set(membership[degrees == 2])), 1)

    def test_samples_match_size_bins_and_use_distinct_nodes(self):
        bins = [np.arange(4), np.arange(4, 8)]
        samples = degree_matched_samples(2.0 ** np.arange(8), bins, ((0, 2), (1, 1)), 200, np.random.default_rng(7))
        for sample in samples:
            mask = int(round(sample * 3))
            self.assertEqual(mask.bit_count(), 3)
            self.assertEqual((mask & 15).bit_count(), 2)
            self.assertEqual((mask >> 4).bit_count(), 1)
        self.assertIsNone(degree_matched_samples(np.arange(8), bins, ((0, 5),), 200, np.random.default_rng(7)))

    def test_null_mean_std_z_and_fixed_disease_distribution(self):
        null = ConditionalNull(np.ones(8), np.arange(8), "TEST_42", minimum_size=1, randomisations=4, seed=1)
        with patch("ranking.proximity.degree_matched_samples", return_value=np.array([0., 1., 2., 3.])):
            low = null.score([0], 0)
            high = null.score([7], 3)
        self.assertEqual(low["randomisation_mean"], 1.5)
        self.assertAlmostEqual(low["randomisation_std"], np.sqrt(1.25))
        self.assertAlmostEqual(low["degree_matched_z"], -1.5 / np.sqrt(1.25))
        self.assertGreater(high["degree_matched_z"], low["degree_matched_z"])
        self.assertEqual(low["profile_seed_hex"], high["profile_seed_hex"])

    def test_unreachable_sentinel_is_never_averaged(self):
        with self.assertRaisesRegex(ValueError, "Unreachable"):
            nearest_distances(np.array([[0, 255], [255, 0]], dtype=np.uint8), [0], 255)

    def test_shortlist_deduplication_fill_and_unscorable_evidence_selection(self):
        candidates = []
        for i in range(1, 21):
            candidates.append({"candidate_id": f"CHEMBL{i}", "status": "scored" if i <= 10 else "not_scorable",
                               "network": {"rank": i} if i <= 10 else None, "direct_evidence": {"score": 1.0},
                               "direct_evidence_rank": i, "selected_by": [], "selection_reasons": [], "shortlist_rank": None})
        ids = make_shortlist(candidates, RankingSettings())
        self.assertEqual(len(ids), 15)
        self.assertEqual(len(set(ids)), 15)
        self.assertEqual(candidates[0]["selected_by"], ["network", "evidence"])
        self.assertIn("CHEMBL15", ids)
        self.assertEqual(candidates[14]["selection_reasons"], ["evidence_fill_after_deduplication"])

    def test_settings_reject_invalid_randomisations_seed_and_sizes(self):
        for kwargs in ({"randomisations": 1}, {"min_bin_size": 0}, {"seed": -1}, {"top_targets": True}):
            with self.assertRaises(ValueError):
                RankingSettings(**kwargs)

    def test_network_ties_use_raw_distance_then_id_and_distance_only_follows(self):
        candidates = []
        for identifier, status, distance in (("CHEMBL1", "scored", 2), ("CHEMBL2", "scored", 1), ("CHEMBL3", "scored", 1), ("CHEMBL4", "distance_only", 0)):
            candidates.append({"candidate_id": identifier, "status": status, "network": {"degree_matched_z": 0 if status == "scored" else None, "mean_distance": distance},
                               "direct_evidence": {"score": 0, "breadth": 0}, "shared_target_count": 0})
        assign_ranks(candidates)
        self.assertEqual([c["candidate_id"] for c in sorted(candidates, key=lambda c: c["network"]["rank"])], ["CHEMBL2", "CHEMBL3", "CHEMBL1", "CHEMBL4"])


if __name__ == "__main__":
    unittest.main()
