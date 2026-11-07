"""Tiny artificial release: no network access or large downloaded files needed."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from numpy.testing import assert_array_equal
from scipy.sparse import csr_matrix

from ranking.artifacts import build_artifacts, load_artifacts, sha256
from ranking.network import build_network, encode_distances, load_mapping, precompute_distances


HEADER = "protein1 protein2 homology experiments experiments_transferred database database_transferred textmining textmining_transferred combined_score"


def protein(i: int) -> str:
    return f"9606.ENSP{i:011d}"


def gene(i: int) -> str:
    return f"ENSG{i:011d}"


def mapped(p: int, g: int) -> dict:
    return {"string_id": protein(p), "target_id": gene(g), "status": "mapped", "reason": None}


def link(a: int, b: int, direct: int = 500, combined: int = 800, transferred: int = 0) -> str:
    return f"{protein(a)} {protein(b)} 0 {direct} {transferred} 0 0 0 0 {combined}"


class NetworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.mapping_path = self.root / "mapping.json"
        self.links_path = self.root / "physical.txt.gz"
        rows = [mapped(1, 1), mapped(2, 2), mapped(3, 3), mapped(4, 1),
                mapped(5, 4), mapped(6, 5), mapped(10, 6), mapped(1, 1),
                mapped(7, 7), mapped(7, 8),
                {"string_id": protein(8), "target_id": "TP53", "status": "mapped", "reason": None},
                {"string_id": protein(9), "target_id": None, "status": "unmapped", "reason": "no match"},
                {"string_id": "10090.ENSP00000000001", "target_id": gene(1), "status": "mapped", "reason": None}]
        self.payload = {"releases": ["string-12.5", "opentargets-26.09"], "mappings": rows}
        self.mapping_path.write_text(json.dumps(self.payload), encoding="utf-8")
        links = [link(1, 2, 400, 700), link(2, 1), link(4, 2), link(2, 3), link(5, 6),
                 link(1, 4), link(3, 5, 0, 1000, 1000), link(3, 5, 399, 900),
                 link(3, 5, 500, 699), link(1, 7), link(1, 8), link(1, 9), link(1, 999), link(1, 1)]
        self.write_links(HEADER, links)

    def write_links(self, header: str, rows: list[str]) -> None:
        with gzip.open(self.links_path, "wt", encoding="utf-8") as handle:
            handle.write(header + "\n" + "\n".join(rows) + "\n")

    def network(self, **kwargs):
        return build_network(self.links_path, load_mapping(self.mapping_path), **kwargs)

    def test_mapping_deduplicates_and_excludes_conflicts_and_bad_ids(self):
        mapping = load_mapping(self.mapping_path)
        self.assertEqual(len(mapping.protein_to_gene), 7)
        self.assertEqual(mapping.protein_to_gene[protein(4)], gene(1))
        self.assertEqual(mapping.report["mapped_genes"], 6)
        self.assertEqual(mapping.report["duplicate_source_rows"], 2)
        self.assertEqual(mapping.report["invalid_string_id_rows"], 1)
        self.assertEqual(mapping.excluded, {protein(7): "ambiguous", protein(8): "invalid_target_id", protein(9): "unmapped"})

    def test_conflicting_status_and_explicit_ambiguity_are_not_rescued(self):
        self.payload["mappings"].extend([
            {"string_id": protein(1), "target_id": None, "status": "unmapped"},
            {"string_id": protein(2), "target_id": gene(2), "status": "ambiguous"},
        ])
        self.mapping_path.write_text(json.dumps(self.payload), encoding="utf-8")
        mapping = load_mapping(self.mapping_path)
        self.assertEqual(mapping.excluded[protein(1)], "conflicting_status")
        self.assertEqual(mapping.excluded[protein(2)], "ambiguous")

    def test_wrong_release_schema_is_rejected(self):
        self.mapping_path.write_text('{"9606.ENSP00000000001": "ENSG00000000001"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mappings"):
            load_mapping(self.mapping_path)

    def test_gene_graph_filters_direct_support_and_removes_duplicate_loops(self):
        network = self.network()
        self.assertEqual(network.gene_ids, tuple(gene(i) for i in range(1, 7)))
        self.assertEqual(network.report["edges"], 3)
        self.assertEqual(network.report["duplicate_edge_rows"], 2)
        self.assertEqual(network.report["self_loop_rows"], 2)
        self.assertEqual(network.report["excluded_mapping_rows"], 4)
        self.assertEqual(network.report["filtered_by_score_rows"], 3)
        self.assertEqual(network.report["components"], 3)
        self.assertEqual(network.report["component_sizes_descending"], [3, 2, 1])
        self.assertEqual(network.report["isolated_nodes"], 1)
        self.assertEqual(network.report["largest_component_nodes"], 3)
        self.assertEqual(network.graph[2, 3], 0)  # transferred-only link never connects components
        self.assertEqual(network.graph.nnz, 6)
        self.assertEqual((network.graph != network.graph.T).nnz, 0)

    def test_thresholds_are_configurable_and_validated(self):
        self.assertEqual(self.network(min_combined_score=699).report["edges"], 4)
        self.assertEqual(self.network(min_experiments=399).report["edges"], 4)
        with self.assertRaisesRegex(ValueError, "0..1000"):
            self.network(min_experiments=-1)

    def test_header_does_not_substitute_transferred_experiments(self):
        self.write_links("protein1 protein2 experiments_transferred combined_score", [])
        with self.assertRaisesRegex(ValueError, "experiments"):
            self.network()

    def test_malformed_rows_fail_clearly(self):
        self.write_links(HEADER, ["too few columns"])
        with self.assertRaisesRegex(ValueError, "row 2"):
            self.network()

    def test_disconnected_shortest_paths_diagonal_and_sentinel(self):
        path = self.root / "all_distances.npy"
        report = precompute_distances(self.network().graph, path, chunk_size=2)
        expected = np.full((6, 6), 255, dtype=np.uint8)
        expected[:3, :3] = [[0, 1, 2], [1, 0, 1], [2, 1, 0]]
        expected[3:5, 3:5] = [[0, 1], [1, 0]]
        expected[5, 5] = 0
        assert_array_equal(np.load(path), expected)
        self.assertEqual(report["unreachable_pairs"], 22)
        self.assertEqual(report["max_finite_distance"], 2)

    def test_encoding_rejects_overflow_nan_negative_and_fractional_values(self):
        assert_array_equal(encode_distances(np.array([0, 254, np.inf])), [0, 254, 255])
        with self.assertRaises(OverflowError):
            encode_distances(np.array([255.0]))
        assert_array_equal(encode_distances(np.array([255.0, np.inf]), "uint16"), [255, 65535])
        for invalid in (np.nan, -1.0, -np.inf, 0.5):
            with self.assertRaises(ValueError):
                encode_distances(np.array([invalid]))

    def test_real_shortest_path_overflow_cannot_wrap_to_zero(self):
        n = 256
        rows = np.arange(n - 1)
        graph = csr_matrix((np.ones(n - 1), (rows, rows + 1)), shape=(n, n))
        graph = graph + graph.T
        with self.assertRaises(OverflowError):
            precompute_distances(graph, self.root / "overflow.npy", chunk_size=1)
        precompute_distances(graph, self.root / "wide.npy", dtype="uint16", chunk_size=64)
        self.assertEqual(np.load(self.root / "wide.npy")[0, -1], 255)

    def test_artifact_roundtrip_provenance_and_tampering(self):
        output = self.root / "artifacts"
        manifest = build_artifacts(self.mapping_path, self.links_path, output, chunk_size=2)
        self.assertEqual(manifest["inputs"]["mapping"]["sha256"], sha256(self.mapping_path))
        self.assertEqual(manifest["filters"]["experiments_min"], 400)
        # Reloading is independent of the original downloaded files.
        self.mapping_path.unlink()
        self.links_path.unlink()
        with load_artifacts(output) as artifacts:
            self.assertEqual(artifacts.graph_gene_ids, tuple(gene(i) for i in range(1, 7)))
            self.assertEqual(artifacts.distance_gene_ids, tuple(gene(i) for i in range(1, 4)))
            self.assertEqual(artifacts.distances[0, 2], 2)
            self.assertIsInstance(artifacts.distances, np.memmap)
            self.assertFalse(artifacts.distances.flags.writeable)
            self.assertEqual(artifacts.graph.nnz, 6)
        with (output / "distances.npy").open("ab") as handle:
            handle.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum/size"):
            load_artifacts(output)

    def test_failed_build_does_not_publish_and_missing_inputs_are_explicit(self):
        output = self.root / "failed"
        with self.assertRaisesRegex(ValueError, "chunk_size"):
            build_artifacts(self.mapping_path, self.links_path, output, chunk_size=0)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".stage1-*")))
        with self.assertRaisesRegex(FileNotFoundError, "missing"):
            build_artifacts(self.root / "absent.json", self.links_path, output)


if __name__ == "__main__":
    unittest.main()
