"""Offline RWR arithmetic, graph provenance and comparison regression tests."""

from copy import deepcopy
from dataclasses import replace
import gzip
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from numpy.testing import assert_allclose
from scipy.sparse import csr_matrix

from ranking.artifacts import write_json
from ranking.data import Disease, Drug, Drugs, normalise_targets
from ranking.evaluation import EvaluationSettings
from ranking.functional_graph import RWRGraph, build_functional_graph, load_rwr_graph
from ranking.rwr import RWRSettings, RWREngine, enrich_ranking, row_normalized_transition, stationary_distribution
from ranking.rwr_evaluation import evaluate_methods


def gene(i):
    return f"ENSG{i:011d}"


def graph_bundle(kind="physical", connected=False):
    # Isolated gene 3 lies outside the physical LCC; functional adds edge 2--3.
    rows, cols = ([0, 1, 1, 2], [1, 0, 2, 1]) if connected else ([0, 1], [1, 0])
    graph = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(3, 3))
    manifest = {"network_kind": "human_physical_gene_undirected_unweighted" if kind == "physical" else "human_functional_association_gene_undirected_unweighted",
                "releases": ["string-12.5", "opentargets-test"], "filters": {"combined_score_min": 700}}
    return RWRGraph(graph, tuple(gene(i) for i in (1, 2, 3)), np.asarray([0, 1, 2] if connected else [0, 1]), manifest,
                    {"bytes": 1, "sha256": kind})


def inputs():
    disease = Disease("TEST_1", "Synthetic", "opentargets-test", {}, normalise_targets([
        {"target_id": gene(1), "evidence_only_score": 0.8},
        {"target_id": gene(3), "evidence_only_score": 0.9},
        {"target_id": gene(2), "evidence_only_score": 0.7}], disease=True), {})
    def drug(identifier, genes):
        return Drug(identifier, identifier, normalise_targets([{"target_id": g} for g in genes]), ["FDA"], [identifier], [])
    drugs = Drugs([drug("CHEMBL2", [gene(2)]), drug("CHEMBL10", [gene(2)]), drug("CHEMBL3", [gene(3)]),
                   drug("CHEMBL4", []), drug("CHEMBL5", [gene(99)])], [], ["opentargets-test"], {}, {})
    return disease, drugs


class SolverTests(unittest.TestCase):
    def test_transition_is_row_normalized_sparse_and_dangling_self_loop(self):
        graph = csr_matrix(np.asarray([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 0]]))
        original = graph.copy()
        transition = row_normalized_transition(graph)
        self.assertIsInstance(transition, csr_matrix)
        assert_allclose(transition.sum(axis=1), np.ones((4, 1)))
        self.assertEqual(transition[1, 0], 0.5)
        self.assertEqual(transition[1, 2], 0.5)
        self.assertEqual(transition[3, 3], 1)
        self.assertEqual((graph != original).nnz, 0)

    def test_stationary_two_node_solution_and_probability_mass(self):
        transition = row_normalized_transition(csr_matrix([[0, 1], [1, 0]]))
        mass, info = stationary_distribution(transition, [0])
        assert_allclose(mass, [1 / 1.7, 0.7 / 1.7], atol=2e-12)
        self.assertTrue(info["converged"])
        self.assertAlmostEqual(mass.sum(), 1)
        self.assertLessEqual(info["residual_l1"], 1e-12)
        self.assertLessEqual(info["fixed_point_residual_l1"], 1e-12)

    def test_column_vector_iteration_matches_direct_linear_solution(self):
        transition = row_normalized_transition(csr_matrix([[0, 1, 0], [1, 0, 1], [0, 1, 0]]))
        mass, _ = stationary_distribution(transition, [0])
        expected = np.linalg.solve(np.eye(3) - 0.7 * transition.T.toarray(), np.asarray([0.3, 0, 0]))
        assert_allclose(mass, expected, atol=2e-12)

    def test_uniform_restarts_reproducibility_and_duplicate_seed_ids(self):
        transition = row_normalized_transition(csr_matrix([[0, 1, 0], [1, 0, 1], [0, 1, 0]]))
        first, info = stationary_distribution(transition, [2, 0, 2])
        second, repeated = stationary_distribution(transition, [0, 2])
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(info, repeated)
        self.assertAlmostEqual(first[0], first[2])

    def test_disconnected_components_and_isolated_restart_mass(self):
        transition = row_normalized_transition(csr_matrix([[0, 1, 0], [1, 0, 0], [0, 0, 0]]))
        mass, _ = stationary_distribution(transition, [0])
        self.assertEqual(mass[2], 0)
        isolated, info = stationary_distribution(transition, [2])
        assert_allclose(isolated, [0, 0, 1])
        self.assertEqual(info["iterations"], 1)

    def test_missing_restarts_and_nonconvergence_never_supply_scores(self):
        transition = row_normalized_transition(csr_matrix([[0, 1], [1, 0]]))
        mass, info = stationary_distribution(transition, [])
        self.assertIsNone(mass)
        self.assertEqual(info["status"], "no_retained_disease_targets")
        mass, info = stationary_distribution(transition, [0], RWRSettings(max_iterations=1))
        self.assertIsNone(mass)
        self.assertFalse(info["converged"])
        self.assertEqual(info["status"], "non_converged")

    def test_numerical_and_configuration_errors_are_explicit(self):
        for graph in (csr_matrix([[0, np.nan], [1, 0]]), csr_matrix([[0, -1], [1, 0]]), csr_matrix((0, 0))):
            with self.assertRaises(ValueError):
                row_normalized_transition(graph)
        for kwargs in ({"restart_probability": 0}, {"restart_probability": float("nan")}, {"tolerance": 0}, {"max_iterations": True}):
            with self.assertRaises(ValueError):
                RWRSettings(**kwargs)
        with self.assertRaises(ValueError):
            stationary_distribution(csr_matrix([[0, 2], [1, 0]]), [0])


class RankingAndIntegrationTests(unittest.TestCase):
    def test_top_targets_selected_before_filtering_and_missing_data(self):
        disease, drugs = inputs()
        result = RWREngine(graph_bundle(), RWRSettings(top_targets=1)).rank(disease, drugs)
        self.assertEqual(result["disease"]["selected_target_ids"], [gene(3)])
        self.assertEqual(result["disease"]["coverage"]["retained"], 0)
        self.assertTrue(all(c["score"] is None for c in result["candidates"]))
        self.assertTrue(all(c["rank"] is None for c in result["candidates"]))

    def test_mean_mass_rank_direction_and_stable_identifier_ties(self):
        disease, drugs = inputs()
        disease.targets = normalise_targets([{"target_id": gene(1), "evidence_only_score": 0.8}], disease=True)
        result = RWREngine(graph_bundle()).rank(disease, drugs)
        candidates = {c["candidate_id"]: c for c in result["candidates"]}
        self.assertEqual(candidates["CHEMBL10"]["rank"], 1)
        self.assertEqual(candidates["CHEMBL2"]["rank"], 2)
        self.assertAlmostEqual(candidates["CHEMBL2"]["score"], 0.7 / 1.7, places=11)
        for cid in ("CHEMBL3", "CHEMBL4", "CHEMBL5"):
            self.assertIsNone(candidates[cid]["score"])
            self.assertEqual(candidates[cid]["reason"], "no_retained_drug_targets")
        reversed_drugs = replace(drugs, drugs=list(reversed(drugs.drugs)))
        repeated = RWREngine(graph_bundle()).rank(disease, reversed_drugs)
        self.assertEqual(result["candidates"], repeated["candidates"])

    def test_mean_uses_all_retained_targets_and_failed_solver_has_no_scores(self):
        disease, drugs = inputs()
        disease.targets = normalise_targets([{"target_id": gene(1), "evidence_only_score": 1}], disease=True)
        drugs.drugs[0].targets = normalise_targets([{"target_id": gene(1)}, {"target_id": gene(2)}])
        result = RWREngine(graph_bundle()).rank(disease, drugs)
        record = next(c for c in result["candidates"] if c["candidate_id"] == "CHEMBL2")
        self.assertAlmostEqual(record["score"], 0.5)
        self.assertAlmostEqual(sum(t["mean_score_contribution"] for t in record["highest_contributing_targets"]), record["score"])
        failed = RWREngine(graph_bundle(), RWRSettings(max_iterations=1)).rank(disease, drugs)
        self.assertTrue(all(c["score"] is None and c["reason"] == "rwr_non_converged" for c in failed["candidates"]))

    def test_graph_switch_changes_coverage_and_preserves_original_paths_and_scores(self):
        disease, drugs = inputs()
        physical = RWREngine(graph_bundle()).rank(disease, drugs)
        functional = RWREngine(graph_bundle("functional", True)).rank(disease, drugs)
        self.assertEqual(physical["disease"]["coverage"]["retained"], 2)
        self.assertEqual(functional["disease"]["coverage"]["retained"], 3)
        self.assertEqual(next(c for c in functional["candidates"] if c["candidate_id"] == "CHEMBL3")["status"], "scored")
        original = {"format_version": 2, "disease": {"id": "TEST_1"}, "shortlist": ["CHEMBL2"],
                    "candidates": [{"candidate_id": d.id, "network": {"mean_distance": 1, "degree_matched_z": -2},
                                    "network_paths": {"paths": [{"hops": 1}]}} for d in drugs.drugs]}
        before = deepcopy(original)
        enriched = enrich_ranking(enrich_ranking(original, physical, "physical"), functional, "functional")
        self.assertFalse(enriched["candidates"][0]["rwr"]["functional"]["shortest_paths_explain_this_score"])
        enriched.pop("rwr_provenance")
        for candidate in enriched["candidates"]:
            candidate.pop("rwr")
        self.assertEqual(enriched, before)
        self.assertEqual(original, before)
        with self.assertRaises(ValueError):
            enrich_ranking(original, functional, "physical")


class FunctionalAndEvaluationTests(unittest.TestCase):
    def test_functional_ingestion_mapping_deduplication_and_separate_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping = root / "mapping.json"
            write_json(mapping, {"releases": ["string-12.5", "opentargets-test"], "mappings": [
                {"string_id": f"9606.ENSP{i:011d}", "target_id": gene(i), "status": "mapped", "reason": None} for i in (1, 2, 3)]})
            links = root / "9606.protein.links.v12.5.txt.gz"
            with gzip.open(links, "wt") as handle:
                handle.write("protein1 protein2 combined_score\n")
                for a, b, score in ((1, 2, 700), (2, 1, 800), (2, 3, 699), (3, 3, 900), (2, 99, 900)):
                    handle.write(f"9606.ENSP{a:011d} 9606.ENSP{b:011d} {score}\n")
            manifest = build_functional_graph(mapping, links, root / "functional")
            self.assertEqual(manifest["graph"]["edges"], 1)
            self.assertEqual(manifest["graph"]["components"], 2)
            self.assertEqual(manifest["graph"]["duplicate_edge_rows"], 1)
            self.assertIsNone(manifest["filters"]["experiments_min"])
            loaded = load_rwr_graph(root / "functional")
            self.assertIn("functional_association", loaded.kind)
            self.assertEqual(loaded.graph.nnz, 2)
            with self.assertRaises(FileExistsError):
                build_functional_graph(mapping, links, root / "functional")
            with self.assertRaises(FileNotFoundError):
                build_functional_graph(mapping, root / "missing.gz", root / "other")
            wrong = root / "9606.protein.physical.links.full.v12.5.txt.gz"
            wrong.write_bytes(links.read_bytes())
            with self.assertRaisesRegex(ValueError, "no substitution"):
                build_functional_graph(mapping, wrong, root / "other")

    def test_comparison_scopes_missing_scores_multiple_labels_and_paired_intervals(self):
        methods = ["direct_evidence", "rwr_physical", "rwr_functional"]
        cases = [{"disease_id": "TEST_1", "eligible_ids": ["CHEMBL1", "CHEMBL2", "CHEMBL3"],
                  "rankings": {"direct_evidence": ["CHEMBL2", "CHEMBL1", "CHEMBL3"], "rwr_physical": ["CHEMBL1"], "rwr_functional": ["CHEMBL2", "CHEMBL1"]}}]
        result = evaluate_methods(cases, {"TEST_1": {"CHEMBL1", "CHEMBL2"}}, methods, EvaluationSettings())
        self.assertEqual(result["coverage"][0]["common_scorable"], 1)
        physical = next(r for r in result["metrics"] if r["scope"] == "full_eligible" and r["method"] == "rwr_physical")
        self.assertEqual(physical["recall_at_5"], 0.5)
        self.assertEqual(physical["missing_positive_count"], 1)
        self.assertEqual(physical["mrr"], 1)
        self.assertEqual(result, evaluate_methods(list(reversed(cases)), {"TEST_1": {"CHEMBL2", "CHEMBL1"}}, methods, EvaluationSettings()))
        self.assertEqual(len(result["paired_comparisons"]), 6)
        cases[0]["method_status"] = {"rwr_physical": "non_converged"}
        failed = evaluate_methods(cases, {"TEST_1": {"CHEMBL1"}}, methods, EvaluationSettings())
        self.assertTrue(all(r["mrr"] is None for r in failed["metrics"] if r["method"] == "rwr_physical"))


if __name__ == "__main__":
    unittest.main()
