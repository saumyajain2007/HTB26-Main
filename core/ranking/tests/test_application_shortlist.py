"""App-only defaults and complete path regeneration preserve frozen scoring."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import asdict
import io
import json
from pathlib import Path
import unittest

from ranking.artifacts import file_record, write_json
from ranking.integration import adapt_ranking, validate_api_candidates
from ranking.paths import explain_ranking
from ranking.scoring import RankingSettings, assign_ranks, make_shortlist
from ranking.shortlist import ShortlistSettings
from ranking.tests import test_paths
from ranking.application.shortlist import generate_shortlist, main


class ApplicationShortlistTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing artificial saved graph instead of another builder.
        self.fixture = test_paths.PathTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.graph = self.fixture.root, self.fixture.bundle
        p = self.fixture.payload()
        template = p["candidates"][3]  # gene 3 -> Disease gene 5, one hop
        p["candidates"] = []
        for i in range(1, 21):
            c = deepcopy(template)
            c.update(candidate_id=f"CHEMBL{i}", name=f"Synthetic {i}", selected_by=[], selection_reasons=[], shortlist_rank=None,
                     direct_evidence={"score": 0.8 if i <= 8 else 0, "breadth": 0.8 if i <= 8 else 0}, shared_target_count=0,
                     rwr={"physical": {"score": i/1000, "rank": 21-i, "status": "scored", "converged": True,
                                        "graph_kind": "human_physical_gene_undirected_unweighted"},
                          "functional": {"score": i/2000, "rank": 21-i}})
            c["network"]["degree_matched_z"] = i/10
            p["candidates"].append(c)
        assign_ranks(p["candidates"])
        p["shortlist"] = make_shortlist(p["candidates"], RankingSettings())
        p["provenance"]["settings"] = asdict(RankingSettings())
        p["rwr_provenance"] = {"physical": {"graph": {"manifest": file_record(self.graph/"manifest.json")}}}
        self.payload, complete = explain_ranking(adapt_ranking(p), self.fixture.artifacts)
        self.source = self.root/"source.json"
        write_json(self.source, self.payload)
        write_json(self.root/"all_paths.json", complete)

    def read_result(self, out):
        return json.loads((out/"application"/"ranking.json").read_text(encoding="utf-8"))

    def test_cli_default_rwr_explains_new_members_and_preserves_source_scores(self):
        source_record = file_record(self.source)
        out = self.root/"new-application"
        with redirect_stdout(io.StringIO()):
            main(["--ranking", str(self.source), "--artifacts", str(self.graph), "--out", str(out)])
        p = self.read_result(out)
        self.assertEqual(p["shortlist_selection"]["selection_method"], "physical_rwr")
        self.assertEqual(p["shortlist"][:10], [f"CHEMBL{i}" for i in range(20, 10, -1)])
        self.assertEqual(len(set(p["shortlist"])), 15)
        self.assertEqual(len(set(p["shortlist"]) - set(self.payload["shortlist"])), 5)
        original = {c["candidate_id"]: c for c in self.payload["candidates"]}
        for c in p["candidates"]:
            for key in ("network", "rwr", "direct_evidence", "direct_evidence_rank", "coverage", "targets"):
                self.assertEqual(c[key], original[c["candidate_id"]][key])
            if c["candidate_id"] in p["shortlist"]:
                self.assertEqual(c["network_paths"]["status"], "available")
                self.assertEqual(c["network_paths"]["paths"][0]["target_ids"], [test_paths.gene(3), test_paths.gene(5)])
                self.assertEqual(c["network_paths"]["paths"][0]["hops"], 1)
                self.assertEqual(c["network_paths"]["complete_paths_ref"]["sha256"], file_record(out/"application"/"all_paths.json")["sha256"])
        complete = json.loads((out/"application"/"all_paths.json").read_text())
        self.assertEqual({c["candidate_id"] for c in complete["candidates"]}, set(p["shortlist"]))
        short = json.loads((out/"application"/"shortlist.json").read_text())
        self.assertTrue(all(c["network_paths"]["status"] == "available" for c in short["candidates"]))
        validate_api_candidates(p["candidates"])
        self.assertEqual(file_record(self.source), source_record)
        self.assertEqual(ShortlistSettings().method, "zscore")  # sealed default remains frozen

    def test_zscore_remains_explicitly_selectable(self):
        out = self.root/"zscore"
        generate_shortlist(self.source, self.graph, out, method="zscore")
        p = self.read_result(out)
        self.assertEqual(p["shortlist"], self.payload["shortlist"])
        self.assertEqual(p["shortlist_selection"]["selection_method"], "zscore")
        self.assertTrue(all("network_paths" in c for c in p["candidates"] if c["candidate_id"] in p["shortlist"]))

    def test_unscorable_evidence_member_has_explicit_path_unavailability(self):
        p = deepcopy(self.payload)
        missing = self.fixture.payload()["candidates"][2]
        missing.update(candidate_id="CHEMBL99", direct_evidence={"score": 1, "breadth": 1}, shared_target_count=0,
                       selection_reasons=[], shortlist_rank=None,
                       rwr={"physical": {"score": None, "status": "not_scorable", "converged": True,
                                          "reason": "no_retained_drug_targets", "graph_kind": "human_physical_gene_undirected_unweighted"}})
        p["candidates"].append(missing)
        write_json(self.source, p)
        out = self.root/"missing-targets"
        generate_shortlist(self.source, self.graph, out)
        p = self.read_result(out)
        c = next(c for c in p["candidates"] if c["candidate_id"] == "CHEMBL99")
        self.assertIn(c["candidate_id"], p["shortlist"])
        self.assertEqual(c["network_paths"]["status"], "unavailable")
        self.assertEqual(c["network_paths"]["reason"], "no_retained_drug_targets")
        self.assertEqual(c["network_paths"]["paths"], [])

    def test_missing_rwr_and_wrong_graph_reject_before_writing(self):
        for metadata in (None, {"graph": {"manifest": {"sha256": "another-graph"}}}):
            p = deepcopy(self.payload)
            p["rwr_provenance"] = {} if metadata is None else {"physical": metadata}
            write_json(self.source, p)
            out = self.root/"rejected"
            with self.assertRaises(ValueError):
                generate_shortlist(self.source, self.graph, out)
            self.assertFalse(out.exists())

    def test_output_is_not_overwritten_and_is_reproducible(self):
        first, second = self.root/"first", self.root/"second"
        generate_shortlist(self.source, self.graph, first)
        generate_shortlist(self.source, self.graph, second)
        for name in ("ranking.json", "shortlist.json", "all_paths.json"):
            self.assertEqual(file_record(first/"application"/name), file_record(second/"application"/name))
        with self.assertRaises(FileExistsError):
            generate_shortlist(self.source, self.graph, first)


if __name__ == "__main__":
    unittest.main()
