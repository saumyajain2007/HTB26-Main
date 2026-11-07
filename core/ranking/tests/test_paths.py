"""Synthetic graph, score-preservation and path integration checks, offline."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.sparse import csr_matrix, save_npz
from scipy.sparse.csgraph import shortest_path

from ranking.artifacts import file_record, load_artifacts, write_json
from ranking.integration import adapt_ranking, validate_api_candidates
from ranking.paths import PathReconstructor, explain_files, explain_ranking, representatives


def gene(i):
    return f"ENSG{i:011d}"


class PathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "graph"
        self.bundle.mkdir()
        # Gene 1 is isolated: full-graph and distance indexes are different.
        # A diamond 2--3--5 / 2--4--5 has equal shortest paths; 5--6--7--8 is a tail.
        pairs = [(2, 3), (2, 4), (3, 5), (4, 5), (5, 6), (6, 7), (7, 8)]
        rows, cols = zip(*[(a - 1, b - 1) for a, b in pairs])
        graph = csr_matrix((np.ones(len(pairs), dtype=np.uint8), (rows, cols)), shape=(8, 8))
        graph = graph + graph.T
        save_npz(self.bundle / "graph.npz", graph)
        matrix = shortest_path(graph[1:, 1:], directed=False, unweighted=True).astype(np.uint8)
        np.save(self.bundle / "distances.npy", matrix)
        write_json(self.bundle / "index.json", {"graph_gene_ids": [gene(i) for i in range(1, 9)],
                   "distance_gene_ids": [gene(i) for i in range(2, 9)], "component_labels": [1] + [0] * 7})
        write_json(self.bundle / "mapping_exclusions.json", {})
        self.manifest = {"format_version": 1, "releases": ["string-12.5", "opentargets-test"],
                         "filters": {"combined_score_min": 700, "experiments_min": 400},
                         "distances": {"shape": [7, 7], "dtype": "uint8", "unreachable_sentinel": 255},
                         "files": {name: file_record(self.bundle / name) for name in ("graph.npz", "index.json", "mapping_exclusions.json", "distances.npy")}}
        write_json(self.bundle / "manifest.json", self.manifest)
        self.artifacts = load_artifacts(self.bundle)
        self.addCleanup(self.artifacts.close)

    def payload(self):
        def candidate(i, targets, rank, mean):
            return {"candidate_id": f"CHEMBL{i}", "name": f"Synthetic {i}", "status": "scored" if mean is not None else "not_scorable",
                    "selected_by": ["evidence"], "direct_evidence_rank": i,
                    "network": None if mean is None else {"rank": rank, "mean_distance": mean, "degree_matched_z": -1 / i, "graph_version": "string-12.5"},
                    "unscorable_reason": "no_retained_drug_targets" if mean is None else None,
                    "coverage": {"retained": len(targets), "retained_target_ids": [gene(t) for t in targets], "excluded_targets": []},
                    "targets": [{"id": gene(t), "name": f"G{t}", "mechanism": "unknown"} for t in targets]}
        return {"format_version": 2, "disease": {"id": "TEST_7", "coverage": {"retained": 1, "retained_target_ids": [gene(5)]}},
                "shortlist": ["CHEMBL1", "CHEMBL2", "CHEMBL3"],
                "candidates": [candidate(1, list(range(2, 9)), 1, 10 / 7), candidate(2, [5], 2, 0),
                               candidate(3, [], None, None), candidate(4, [3], 3, 1)],
                "provenance": {"stage1_files": self.manifest["files"], "stage1_manifest": file_record(self.bundle / "manifest.json")},
                "other_metadata": {"preserve": [1, 2, 3]}}

    def test_direct_overlap_is_one_target_and_zero_hops(self):
        engine = PathReconstructor(self.artifacts, [gene(5)])
        path = engine.nearest_path(gene(5))
        self.assertEqual(path["target_ids"], [gene(5)])
        self.assertEqual(path["hops"], 0)
        self.assertEqual(path["graph_version"], "string-12.5")
        engine.validate_path(path)

    def test_equal_routes_use_lexicographic_intermediate_ids(self):
        engine = PathReconstructor(self.artifacts, [gene(5)])
        self.assertEqual(engine.nearest_path(gene(2))["target_ids"], [gene(2), gene(3), gene(5)])
        graph = self.artifacts.graph.copy()
        for i in range(graph.shape[0]):
            start, end = graph.indptr[i:i + 2]
            graph.indices[start:end] = graph.indices[start:end][::-1]
        graph.has_sorted_indices = False
        with patch.object(self.artifacts, "graph", graph):
            self.assertEqual(PathReconstructor(self.artifacts, [gene(5)]).nearest_path(gene(2)), engine.nearest_path(gene(2)))

    def test_equal_nearest_disease_targets_use_endpoint_id_and_deduplicate(self):
        engine = PathReconstructor(self.artifacts, [gene(4), gene(3), gene(3)])
        self.assertEqual(engine.disease_targets, [gene(3), gene(4)])
        path = engine.nearest_path(gene(2))
        self.assertEqual(path["target_ids"], [gene(2), gene(3)])
        self.assertEqual(path["hops"], 1)

    def test_complete_tail_path_and_separate_graph_distance_indexes(self):
        engine = PathReconstructor(self.artifacts, [gene(5)])
        path = engine.nearest_path(gene(8))
        self.assertEqual(path["target_ids"], [gene(8), gene(7), gene(6), gene(5)])
        self.assertEqual(path["hops"], 3)
        engine.validate_path(path)

    def test_disconnected_missing_and_invalid_targets_have_explicit_reasons(self):
        engine = PathReconstructor(self.artifacts, [gene(5), gene(1), gene(99)])
        self.assertEqual(len(engine.excluded_disease_targets), 2)
        for identifier, reason in ((gene(1), "outside_largest_component"), (gene(99), "not_in_graph"), ("TP53", "invalid_target_id")):
            with self.subTest(identifier=identifier):
                record = engine.nearest_path(identifier)
                self.assertEqual(record["reason"], reason)
                self.assertIsNone(record["hops"])
                self.assertEqual(record["target_ids"], [])

    def test_no_valid_disease_targets_and_unreachable_sentinel(self):
        engine = PathReconstructor(self.artifacts, [gene(1), gene(99)])
        self.assertEqual(engine.nearest_path(gene(2))["reason"], "no_retained_disease_targets")
        distances = self.artifacts.distances.copy()
        distances[0, 3] = 255
        with patch.object(self.artifacts, "distances", distances):
            path = PathReconstructor(self.artifacts, [gene(5)]).nearest_path(gene(2))
            self.assertEqual(path["reason"], "unreachable_disease_targets")
            self.assertIsNone(path["hops"])

    def test_invalid_edge_wrong_hops_and_wrong_saved_distance_are_rejected(self):
        engine = PathReconstructor(self.artifacts, [gene(5)])
        record = engine.nearest_path(gene(2))
        broken = {**record, "target_ids": [gene(2), gene(6), gene(5)]}
        with self.assertRaisesRegex(ValueError, "absent graph edge"):
            engine.validate_path(broken)
        with self.assertRaisesRegex(ValueError, "hop count"):
            engine.validate_path({**record, "hops": 1})
        matrix = self.artifacts.distances.copy()
        matrix[0, 3] = 1
        with patch.object(self.artifacts, "distances", matrix):
            with self.assertRaisesRegex(ValueError, "inconsistency"):
                PathReconstructor(self.artifacts, [gene(5)]).nearest_path(gene(2))

    def test_cached_paths_cannot_be_mutated_by_callers(self):
        engine = PathReconstructor(self.artifacts, [gene(5)])
        first = engine.nearest_path(gene(2))
        first["target_ids"].clear()
        self.assertEqual(len(engine.nearest_path(gene(2))["target_ids"]), 3)

    def test_all_target_paths_reproduce_mean_and_representatives_cover_range(self):
        enriched, complete = explain_ranking(self.payload(), self.artifacts)
        paths = complete["candidates"][0]["paths"]
        self.assertEqual(len(paths), 7)
        self.assertEqual(sum(p["hops"] for p in paths) / len(paths), 10 / 7)
        explanation = enriched["candidates"][0]["network_paths"]
        self.assertEqual(explanation["score_contributing_target_count"], 7)
        self.assertEqual([p["drug_target_id"] for p in explanation["paths"]], [gene(5), gene(6), gene(8)])
        self.assertEqual(representatives(list(reversed(paths))), explanation["paths"])
        self.assertEqual(len(enriched["candidates"][1]["network_paths"]["paths"]), 1)
        self.assertEqual(enriched["candidates"][2]["network_paths"]["status"], "unavailable")

    def test_extension_preserves_every_original_field_and_shared_api_adapter(self):
        payload = adapt_ranking(self.payload())
        before = deepcopy(payload)
        enriched, _ = explain_ranking(payload, self.artifacts)
        validate_api_candidates(enriched["candidates"])
        self.assertEqual(adapt_ranking(enriched)["candidates"][0]["network_paths"], enriched["candidates"][0]["network_paths"])
        self.assertEqual(payload, before)
        restored = deepcopy(enriched)
        restored.pop("network_paths_provenance")
        for candidate in restored["candidates"]:
            candidate.pop("network_paths", None)
        self.assertEqual(restored, before)
        self.assertNotIn("network_paths", enriched["candidates"][3])

    def test_mismatched_mean_graph_and_retained_target_claims_fail_closed(self):
        payload = self.payload()
        variants = []
        wrong = deepcopy(payload)
        wrong["candidates"][0]["network"]["mean_distance"] = 99
        variants.append(wrong)
        wrong = deepcopy(payload)
        wrong["provenance"]["stage1_files"] = {}
        variants.append(wrong)
        wrong = deepcopy(payload)
        wrong["candidates"][0]["coverage"]["retained_target_ids"][0] = gene(1)
        variants.append(wrong)
        wrong = deepcopy(payload)
        wrong["disease"]["coverage"]["retained_target_ids"] = [gene(1)]
        variants.append(wrong)
        for wrong in variants:
            with self.assertRaises(ValueError):
                explain_ranking(wrong, self.artifacts)

    def test_json_bundle_is_reproducible_preserves_inputs_and_never_overwrites(self):
        source = self.root / "ranking.json"
        write_json(source, self.payload())
        before = file_record(source)
        first = explain_files(self.bundle, source, self.root / "first")
        second = explain_files(self.bundle, source, self.root / "second")
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(first["complete_verified_paths"], 8)
        self.assertEqual(first["representative_paths"], 4)
        self.assertEqual(file_record(source), before)
        shortlist = json.loads((self.root / "first/shortlist.json").read_text())
        self.assertEqual([c["candidate_id"] for c in shortlist["candidates"]], self.payload()["shortlist"])
        for candidate in shortlist["candidates"]:
            ref = candidate["network_paths"]["complete_paths_ref"]
            self.assertEqual({key: ref[key] for key in ("bytes", "sha256")}, first["files"]["all_paths.json"])
            self.assertLessEqual(len(candidate["network_paths"]["paths"]), 3)
        with self.assertRaises(FileExistsError):
            explain_files(self.bundle, source, self.root / "first")
        enriched = json.loads((self.root / "first/ranking.json").read_text())
        with self.assertRaisesRegex(ValueError, "already contains"):
            explain_ranking(enriched, self.artifacts)


if __name__ == "__main__":
    unittest.main()
