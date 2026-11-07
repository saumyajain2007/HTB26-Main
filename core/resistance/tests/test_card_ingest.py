"""CARD ingest tests. They build a small synthetic CARD, so they need no network or downloads.

The last tests run against a real release if one was built (``uv run python -m
htb_resistance build``) and are skipped otherwise.
"""

import csv
import io
import json
import tarfile
from pathlib import Path

import pytest

from htb_resistance import TABLES, build, read_table, verify_release
from htb_resistance.card import CardError, DEFAULT_DIR, aro, build_tables, curie, parse_obo, read_member

OBO = '''format-version: 1.2
date: 11:08:2026 08:59
ontology: antibiotic_resistance

[Term]
id: ARO:0000032
name: cephalosporin
def: "Cephalosporins are \\"beta-lactam\\" antibiotics." [PMID:1]
is_a: ARO:1000001 ! beta-lactam antibiotic
is_a: NCIT:85540 ! external parent

[Term]
id: ARO:0000051
name: fluoroquinolone antibiotic
xref: ChEMBL:CHEMBL8

[Term]
id: ARO:0010002
name: antibiotic inactivation
synonym: "enzymatic inactivation" EXACT []

[Term]
id: ARO:3001878
name: CTX-M-15
relationship: confers_resistance_to_drug_class ARO:0000032 ! cephalosporin
synonym: "blaCTX-M-15" EXACT []
synonym: "CTX-M 15" RELATED []

[Term]
id: ARO:3003817
name: Acinetobacter baumannii gyrA conferring resistance to fluoroquinolones

[Term]
id: ARO:3004001
name: CTX-M beta-lactamase

[Term]
id: ARO:3004002
name: fluoroquinolone resistant gyrase
'''

ARO_TSV = (
    "Accession\tName\tDescription\tID\tCARD Short Name\n"
    "ARO:0000032\tcephalosporin\tA beta-lactam class.\t35951\t\n"
    "ARO:3001878\tCTX-M-15\tAn ESBL.\t38000\tCTX-M-15\n"
    "NCIT:85540\texternal parent\t\t\t\n"
)
CATEGORIES_TSV = (
    "ARO Category\tARO Accession\tARO Name\n"
    "Drug Class\tARO:0000032\tcephalosporin\n"
    "Drug Class\tARO:0000051\tfluoroquinolone antibiotic\n"
    "Resistance Mechanism\tARO:0010002\tantibiotic inactivation\n"
    "AMR Gene Family\tARO:3004001\tCTX-M beta-lactamase\n"
    "AMR Gene Family\tARO:3004002\tfluoroquinolone resistant gyrase\n"
)


def cat(acc, name, cls):
    return {"category_aro_accession": acc, "category_aro_name": name, "category_aro_class_name": cls}


CARD = {
    "_version": "9.9.9",
    "_timestamp": "2026-01-01T00:00:00+00:00",
    "1": {
        "model_id": "1", "model_name": "CTX-M-15", "model_type": "protein homolog model",
        "ARO_accession": "3001878", "CARD_short_name": "CTX-M-15",
        "model_param": {"blastp_bit_score": {"param_type": "BLASTP bit-score", "param_value": "600"}},
        "ARO_category": {
            "a": cat("0000032", "cephalosporin", "Drug Class"),
            "b": cat("0010002", "antibiotic inactivation", "Resistance Mechanism"),
            "c": cat("3004001", "CTX-M beta-lactamase", "AMR Gene Family"),
        },
        "model_sequences": {"sequence": {"10": {
            "protein_sequence": {"accession": "AAA1.1", "sequence": "MKT"},
            "dna_sequence": {"accession": "X1.1", "sequence": "ATG"},
            "NCBI_taxonomy": {"NCBI_taxonomy_id": "573", "NCBI_taxonomy_name": "Klebsiella pneumoniae"},
        }}},
    },
    "2": {
        "model_id": "2", "model_name": "gyrA", "model_type": "protein variant model",
        "ARO_accession": "3003817", "CARD_short_name": "Abau_gyrA_FLO",
        "model_param": {
            "snp": {
                "param_type": "single resistance variant",
                "param_value": {"1": "S81L", "2": "G79C"},
                "Curated-R": {"1": "S81L", "2": "G79C"},
                "clinical": {"1": "S81L"},
            },
            "blastp_bit_score": {"param_type": "BLASTP bit-score", "param_value": "1000"},
        },
        "ARO_category": {
            "a": cat("0000051", "fluoroquinolone antibiotic", "Drug Class"),
            "b": cat("3004002", "fluoroquinolone resistant gyrase", "AMR Gene Family"),
        },
        "model_sequences": {"sequence": {}},
    },
    "3": {
        "model_id": "3", "model_name": "pump", "model_type": "efflux pump system meta-model",
        "ARO_accession": "3004001", "CARD_short_name": "pump",
        "model_param": {"c": {"param_type": "efflux pump components", "param_value": {"7": "R:1,R:2"}}},
        "ARO_category": {"a": cat("0010002", "antibiotic inactivation", "Resistance Mechanism")},
    },
}


def tables():
    return build_tables(CARD, OBO, ARO_TSV, CATEGORIES_TSV)


# ------------------------------------------------------------------ parsing

def test_aro_normalises_and_rejects():
    assert aro("32") == "ARO:0000032"
    assert aro("ARO:3001878") == "ARO:3001878"
    assert aro(3001878) == "ARO:3001878"
    with pytest.raises(CardError):
        aro("NCIT:85540")
    with pytest.raises(CardError):
        aro("")


def test_curie_keeps_external_ids():
    assert curie("NCIT:85540") == "NCIT:85540"
    assert curie("ARO:32") == "ARO:0000032"
    with pytest.raises(CardError):
        curie("not an id")


def test_parse_obo_reads_terms_relations_synonyms_xrefs():
    date, terms = parse_obo(OBO)
    assert date == "11:08:2026 08:59"
    by = {t["id"]: t for t in terms}
    assert len(terms) == 7
    assert by["ARO:0000032"]["def"] == 'Cephalosporins are "beta-lactam" antibiotics.'
    assert ("is_a", "NCIT:85540") in by["ARO:0000032"]["relations"]
    assert by["ARO:3001878"]["relations"] == [("confers_resistance_to_drug_class", "ARO:0000032")]
    assert ("blaCTX-M-15", "EXACT") in by["ARO:3001878"]["synonyms"]
    assert by["ARO:0000051"]["xrefs"] == [("ChEMBL", "CHEMBL8")]


# ------------------------------------------------------------------ tables

def test_every_table_has_the_declared_columns():
    t, _ = tables()
    assert set(t) == set(TABLES)
    for name, cols in TABLES.items():
        assert all(len(r) == len(cols) for r in t[name]), name


def test_gene_to_class_and_mechanism_links():
    t, _ = tables()
    links = {(r[0], r[3]): r[2] for r in t["model_categories"]}
    assert links[("1", "Drug Class")] == "ARO:0000032"
    assert links[("1", "Resistance Mechanism")] == "ARO:0010002"
    assert links[("1", "AMR Gene Family")] == "ARO:3004001"


def test_external_parent_is_kept_not_dropped():
    t, _ = tables()
    assert ("ARO:0000032", "is_a", "NCIT:85540") in t["aro_relations"]
    assert any(r[0] == "NCIT:85540" for r in t["aro_terms"])  # in aro.tsv only


def test_point_mutations_carry_their_sources():
    t, _ = tables()
    v = {r[3]: r[4] for r in t["model_variants"]}
    assert v == {"S81L": "Curated-R;clinical", "G79C": "Curated-R"}
    assert all(r[0] == "2" and r[1] == "ARO:3003817" for r in t["model_variants"])


def test_non_mutation_parameters_are_skipped_and_counted():
    t, report = tables()
    assert not any(r[2] == "efflux pump components" for r in t["model_variants"])
    assert report["non_mutation_parameters_skipped"] == {"efflux pump components": 1}


def test_organism_comes_from_the_model_sequence():
    t, _ = tables()
    assert t["model_sequences"] == [("1", "10", "AAA1.1", "X1.1", "573", "Klebsiella pneumoniae")]


def test_integrity_report_flags_dangling_links():
    broken = json.loads(json.dumps(CARD))
    broken["1"]["ARO_category"]["z"] = cat("9999999", "ghost", "Drug Class")
    _, report = build_tables(broken, OBO, ARO_TSV, CATEGORIES_TSV)
    assert report["category_links_without_ontology_term"] == ["ARO:9999999"]


def test_duplicate_model_ids_are_an_error():
    dup = json.loads(json.dumps(CARD))
    dup["4"] = dict(dup["1"])
    with pytest.raises(CardError, match="duplicate model"):
        build_tables(dup, OBO, ARO_TSV, CATEGORIES_TSV)


def test_synonyms_support_gene_name_lookup():
    t, _ = tables()
    assert ("ARO:3001878", "blaCTX-M-15", "EXACT") in t["aro_synonyms"]


# ------------------------------------------------------------------ archive round trip

def _tar(path: Path, members: dict[str, bytes]):
    with tarfile.open(path, "w:bz2") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@pytest.fixture
def archives(tmp_path):
    data = tmp_path / "in" / "card-data.tar.bz2"
    ont = tmp_path / "in" / "card-ontology.tar.bz2"
    data.parent.mkdir()
    _tar(data, {"card.json": json.dumps(CARD).encode(), "aro_categories.tsv": CATEGORIES_TSV.encode()})
    _tar(ont, {"aro.obo": OBO.encode(), "aro.tsv": ARO_TSV.encode()})
    return data, ont


def test_build_writes_tables_manifest_and_is_reproducible(tmp_path, archives):
    data, ont = archives
    out = tmp_path / "out"
    rel = build(out, data_archive=data, ontology_archive=ont, log=lambda *_: None)
    assert rel == out / "releases" / "9.9.9"
    manifest = json.loads((rel / "manifest.json").read_text())
    assert manifest["card_data_version"] == "9.9.9"
    assert manifest["sources"]["data"]["sha256"] and manifest["licence"]["name"].startswith("CC-BY-4.0")
    assert set(manifest["tables"]) == set(TABLES)
    assert verify_release(rel) == []
    first = {n: i["sha256"] for n, i in manifest["tables"].items()}
    build(out, data_archive=data, ontology_archive=ont, log=lambda *_: None)
    second = {n: i["sha256"] for n, i in json.loads((rel / "manifest.json").read_text())["tables"].items()}
    assert first == second
    assert [r["name"] for r in read_table(rel, "models")][0] == "CTX-M-15"


def test_verify_detects_a_changed_table(tmp_path, archives):
    data, ont = archives
    rel = build(tmp_path / "out", data_archive=data, ontology_archive=ont, log=lambda *_: None)
    (rel / "tables" / "models.tsv").write_text("tampered\n")
    assert verify_release(rel) == ["models: checksum differs from manifest"]


def test_missing_version_is_an_error(tmp_path):
    data, ont = tmp_path / "d.tar.bz2", tmp_path / "o.tar.bz2"
    _tar(data, {"card.json": json.dumps({k: v for k, v in CARD.items() if k != "_version"}).encode(),
                "aro_categories.tsv": CATEGORIES_TSV.encode()})
    _tar(ont, {"aro.obo": OBO.encode(), "aro.tsv": ARO_TSV.encode()})
    with pytest.raises(CardError, match="_version"):
        build(tmp_path / "out", data_archive=data, ontology_archive=ont, log=lambda *_: None)


def test_archive_is_read_in_memory_and_traversal_names_are_harmless(tmp_path):
    arc = tmp_path / "evil.tar.bz2"
    _tar(arc, {"../../escape.txt": b"x", "card.json": b"{}"})
    assert read_member(arc, "card.json") == b"{}"
    assert not (tmp_path.parent / "escape.txt").exists()
    with pytest.raises(CardError, match="not found"):
        read_member(arc, "aro.obo")


def test_a_non_archive_is_an_error(tmp_path):
    bad = tmp_path / "bad.tar.bz2"
    bad.write_bytes(b"<html>not an archive</html>")
    with pytest.raises(CardError):
        read_member(bad, "card.json")


# ------------------------------------------------------------------ real release (skipped if absent)

def _real_release():
    found = sorted((DEFAULT_DIR / "releases").glob("*/manifest.json")) if (DEFAULT_DIR / "releases").exists() else []
    return found[-1].parent if found else None


real = pytest.mark.skipif(_real_release() is None, reason="build a release first: uv run python -m htb_resistance build")


@real
def test_real_release_matches_its_manifest_and_has_no_dangling_links():
    rel = _real_release()
    assert verify_release(rel) == []
    integrity = json.loads((rel / "manifest.json").read_text())["integrity"]
    assert integrity["models_without_ontology_term"] == []
    assert integrity["category_links_without_ontology_term"] == []
    assert integrity["models_without_categories"] == []


@real
def test_real_release_known_genes():
    rel = _real_release()
    terms = {r["aro_accession"]: r["name"] for r in read_table(rel, "aro_terms")}
    models = {r["name"]: r for r in read_table(rel, "models")}
    links = list(read_table(rel, "model_categories"))

    def classes(gene, kind):
        mid = models[gene]["model_id"]
        return {terms[r["category_aro_accession"]] for r in links if r["model_id"] == mid and r["category_class"] == kind}

    assert {"cephalosporin", "penicillin beta-lactam"} <= classes("CTX-M-15", "Drug Class")
    assert "antibiotic inactivation" in classes("CTX-M-15", "Resistance Mechanism")
    assert "carbapenem" in classes("NDM-1", "Drug Class")
    assert "antibiotic target replacement" in classes("mecA", "Resistance Mechanism")
    muts = {r["mutation"] for r in read_table(rel, "model_variants") if r["aro_accession"] == "ARO:3003817"}
    assert {"S81L", "G79C"} <= muts


def test_verify_detects_a_changed_row_count(tmp_path, archives):
    data, ont = archives
    rel = build(tmp_path / "out", data_archive=data, ontology_archive=ont, log=lambda *_: None)
    manifest = json.loads((rel / "manifest.json").read_text())
    manifest["tables"]["models"]["rows"] += 1
    (rel / "manifest.json").write_text(json.dumps(manifest))
    assert verify_release(rel) == ["models: row count differs from manifest"]


def test_verify_checks_the_raw_archives_when_present(tmp_path, archives):
    data, ont = archives
    rel = build(tmp_path / "out", data_archive=data, ontology_archive=ont, log=lambda *_: None)
    raw = tmp_path / "raw"
    for kind, src in (("data", data), ("ontology", ont)):
        (raw / kind).mkdir(parents=True)
        (raw / kind / src.name).write_bytes(src.read_bytes())
    assert verify_release(rel, raw) == []
    (raw / "ontology" / ont.name).write_bytes(b"swapped download")
    assert verify_release(rel, raw) == [f"source ontology ({ont.name}): checksum differs from manifest"]
    # A release kept without its downloads is not an error.
    assert verify_release(rel, tmp_path / "nowhere") == []
