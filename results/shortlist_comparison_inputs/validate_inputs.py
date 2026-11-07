"""Offline input checks only; imports Zaid's loaders without scoring anything."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
PUBLISHED = ROOT / "results/experiment_b_replication"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ranking-venv", type=Path, default=os.environ.get("RANKING_VENV"),
                    help="Zaid's ranking/.venv directory (or set RANKING_VENV)")
args, test_args = parser.parse_known_args()
if args.ranking_venv is None:
    parser.error("pass --ranking-venv or set RANKING_VENV")
ranking_venv = args.ranking_venv.resolve()
ZAID = ranking_venv.parent.parent
if not any((ranking_venv / name).is_file() for name in ("bin/python", "Scripts/python.exe")) or not (ZAID / "ranking/data.py").is_file():
    parser.error("--ranking-venv must point to Zaid's ranking/.venv directory")
sys.dont_write_bytecode = True
sys.path.insert(0, str(ZAID))

from ranking.data import APPROVAL_SOURCES, DISEASE_ID, load_disease, load_drugs
from ranking.references import parse_references


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InputTests(unittest.TestCase):
    def test_cases(self):
        cases = read(BUNDLE / "cases.json")
        published = read(ROOT / "results/experiment_b_replication/results.json")
        ids = [c["disease_id"] for c in cases["cases"]]
        self.assertEqual(cases["format_version"], 1)
        self.assertTrue(cases["cohort_id"])
        self.assertEqual(len(ids), 14)
        self.assertEqual(len(set(ids)), 14)
        self.assertEqual(ids, [p["disease"]["id"] for p in published["panels"]])
        self.assertEqual(ids, [r[0] for r in published["selection"]["selected"]])
        for case in cases["cases"]:
            self.assertIsNotNone(DISEASE_ID.fullmatch(case["disease_id"]))
            relative = Path(case["targets_file"])
            self.assertFalse(relative.is_absolute())
            self.assertTrue((BUNDLE / "targets" / relative).resolve().is_relative_to(BUNDLE / "targets"))

    def test_targets_with_zaid_loader(self):
        frozen = read(PUBLISHED / "preregistered.json")["declaration"]["inputs_sha256"]
        fixture = read(ROOT / "fixtures/disease_targets.json")
        for case in read(BUNDLE / "cases.json")["cases"]:
            with self.subTest(disease=case["disease_id"]):
                path = BUNDLE / "targets" / case["targets_file"]
                original = ROOT / "data/experiment_b_replication" / path.name
                self.assertEqual(path.read_bytes(), original.read_bytes())
                self.assertEqual(sha(path), frozen[str(original.relative_to(ROOT))])
                payload = read(path)
                self.assertEqual(set(payload), set(fixture))
                self.assertTrue(all(set(t) == set(fixture["targets"][0]) for t in payload["targets"]))
                disease = load_disease(path, case["disease_id"])
                self.assertEqual(disease.release, "opentargets-26.09")
                self.assertEqual(len(disease.targets.rows), 50)
                self.assertEqual(disease.targets.exclusions, [])

    def test_drugs_with_zaid_loader(self):
        path = ROOT / "data/drug_targets.json"
        frozen = read(PUBLISHED / "preregistered.json")["declaration"]["inputs_sha256"]
        self.assertEqual(sha(path), frozen["data/drug_targets.json"])
        pool = load_drugs(path)
        self.assertEqual(len(pool.drugs), len(read(path)["drugs"]))
        self.assertEqual(pool.excluded, [])
        self.assertEqual(pool.releases, ["opentargets-26.09", "chembl-37"])

    def test_references_with_zaid_loader(self):
        refs = read(BUNDLE / "references.json")
        known = parse_references(refs)
        source = ROOT / "data/drug_targets.json"
        drugs = read(source)
        self.assertEqual(refs["releases"], drugs["releases"])
        self.assertEqual(refs["source_files"][0]["sha256"], sha(source))
        self.assertEqual(list(known), [c["disease_id"] for c in read(BUNDLE / "cases.json")["cases"]])
        for case in refs["cases"]:
            identifier = case["disease_id"]
            expected = {d["drug_id"] for d in drugs["drugs"]
                        if identifier in d["approval"]["disease_ids"]
                        and APPROVAL_SOURCES.intersection(d["approval"]["sources"])}
            self.assertEqual(known[identifier], expected)
            self.assertEqual(len(case["known_candidate_ids"]), len(expected))
            self.assertEqual({d["candidate_id"] for d in case["approved_drugs"]}, expected)
        expected_overrides = [
            {"candidate_id": d["drug_id"], **o, "regulator": "FDA", "in_cohort": o["disease_id"] in known}
            for d in drugs["drugs"] for o in d["approval"].get("overrides", [])]
        self.assertEqual(refs["override_inventory"], expected_overrides)
        self.assertEqual(refs["unmapped_count"], 0)

    def test_protocol_and_freeze(self):
        for name in ("protocol.md", "protocol_frozen.json"):
            self.assertEqual((BUNDLE / name).read_bytes(), (PUBLISHED / name).read_bytes())
        record = next(r for r in read(BUNDLE / "manifest.json")["source_files"]
                      if r["path"] == "results/experiment_b_replication/preregistered.json")
        self.assertEqual(sha(PUBLISHED / "preregistered.json"), record["sha256"])
        self.assertEqual(sha(BUNDLE / "protocol.md"), read(BUNDLE / "protocol_frozen.json")["protocol_sha256"])

    def test_ranking_loader_environment(self):
        self.assertEqual(Path(sys.modules["ranking"].__file__).resolve(), ZAID / "ranking/__init__.py")

    def test_manifest_and_pinned_graph(self):
        manifest = read(BUNDLE / "manifest.json")
        self.assertEqual(set(manifest["files"]),
                         {str(p.relative_to(BUNDLE)) for p in BUNDLE.rglob("*")
                          if p.is_file() and p.name != "manifest.json"})
        for record in manifest["source_files"]:
            self.assertEqual(sha(ROOT / record["path"]), record["sha256"])
        for name, record in manifest["files"].items():
            self.assertEqual(sha(BUNDLE / name), record["sha256"])
            self.assertEqual((BUNDLE / name).stat().st_size, record["bytes"])
        frozen = read(PUBLISHED / "preregistered.json")["declaration"]["inputs_sha256"]
        for name, record in manifest["artifacts"]["files"].items():
            self.assertEqual(sha(ROOT / name), frozen[name])
            self.assertEqual(record["sha256"], frozen[name])
        self.assertEqual(manifest["reference_pairs"], sum(len(s) for s in parse_references(read(BUNDLE / "references.json")).values()))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *test_args], verbosity=2)
