"""The AMRFinderPlus bridge: mechanical matching rules, labelled, never silent about ambiguity.

Built from hand-made Entry objects, so no CARD download is needed.
"""
from htb_resistance import Bridge, Species, parse_ncbi_genotypes
from htb_resistance.reference import Entry, Reference, Variant


def entry(aro, name, *, names=(), variants=(), model_type="protein homolog model"):
    return Entry(aro=aro, name=name, short_name=name, model_type=model_type, model_ids=(1,),
                 drug_classes=(), mechanisms=(), gene_families=(),
                 variants=tuple(Variant(m, None) for m in variants), names=tuple([name, *names]))


def reference():
    return Reference([
        entry("ARO:9000001", "mphA"),
        entry("ARO:9000002", "ErmA", names=("ermA",)),
        entry("ARO:9000003", "aadA", names=("aadA, aadA1, aad(3'')(9)",)),
        entry("ARO:9000004", "Staphylococcus aureus gyrA conferring resistance to fluoroquinolones",
              variants=("S84L",)),
        entry("ARO:9000005", "Escherichia coli gyrA conferring resistance to fluoroquinolones",
              variants=("S83L",)),
        entry("ARO:9000006", "Escherichia coli gyrA with mutation conferring resistance to triclosan",
              variants=("G81D",)),
        entry("ARO:9000007", "Escherichia coli parC conferring resistance to fluoroquinolones"),
        entry("ARO:9000008", "CTX-M-15"),
        entry("ARO:9000009", "TEM-1"),
        entry("ARO:9000010", "TEM-2"),
    ], release="card-test")


def test_punctuation_and_case_are_ignored():
    bridge = Bridge(reference())
    assert bridge.resolve("mph(A)").entry.aro == "ARO:9000001"
    assert bridge.resolve("erm(A)").entry.aro == "ARO:9000002"
    assert bridge.resolve("mph(A)").how == "normalised_name"


def test_multi_name_synonyms_are_split():
    assert Bridge(reference()).resolve("aadA1").entry.aro == "ARO:9000003"


def test_plain_matches_are_untouched():
    res = Bridge(reference()).resolve("CTX-M-15")
    assert (res.status, res.how) == ("resolved", "exact")
    assert Bridge(reference()).resolve("blaCTX-M-15").how == "bla_prefix_stripped"


def test_unknown_stays_unknown():
    assert Bridge(reference()).resolve("blaZ").status == "unknown"


def test_allele_family_is_not_guessed():
    # "blaTEM" names no single determinant; TEM-1 and TEM-2 are not picked between.
    assert Bridge(reference()).resolve("blaTEM").status == "unknown"


def test_point_mutation_uses_the_species_model():
    res = Bridge(reference()).resolve("gyrA", "Staphylococcus aureus", "S84L")
    assert (res.status, res.how, res.entry.aro) == ("resolved", "species_variant_model", "ARO:9000004")


def test_point_mutation_without_a_species_does_not_use_a_model():
    assert Bridge(reference()).resolve("gyrA", None, "S84L").status == "unknown"


def test_homolog_species_is_labelled_and_used_only_as_a_fallback():
    res = Bridge(reference()).resolve("gyrA", "Klebsiella pneumoniae", "S83L")
    assert res.how == "homolog_species_model:escherichia coli"
    assert res.entry.aro == "ARO:9000005"  # the listed mutation separates the two E. coli models
    assert Bridge(reference()).resolve("parC", "Klebsiella pneumoniae", "S80I").entry.aro == "ARO:9000007"


def test_species_model_beats_homolog():
    res = Bridge(reference()).resolve("gyrA", "Staphylococcus aureus", "S84L")
    assert "homolog" not in res.how


def test_ambiguous_models_are_reported_not_picked():
    res = Bridge(reference()).resolve("gyrA", "Klebsiella pneumoniae", "S83Y")  # listed in neither
    assert res.status == "ambiguous" and len(res.candidates) == 2


def test_parse_ncbi_genotypes_splits_point_and_methods():
    parsed = parse_ncbi_genotypes("gyrA_S83Y=POINT,blaSHV-12,mecA=PARTIAL,ompK35_K292QfsTer17=POINT",
                                  Species("Klebsiella pneumoniae"))
    by_raw = {t.raw: t for t in parsed.tokens}
    assert (by_raw["gyrA_S83Y=POINT"].lookup, by_raw["gyrA_S83Y=POINT"].mutation) == ("gyrA", "S83Y")
    assert by_raw["blaSHV-12"].mutation is None and by_raw["mecA=PARTIAL"].method == "amrfinder:PARTIAL"
    assert by_raw["ompK35_K292QfsTer17=POINT"].mutation == "K292QfsTer17"


def test_parse_ncbi_genotypes_reports_what_it_drops():
    parsed = parse_ncbi_genotypes("mecA=PARTIAL,blaZ,blaZ", exclude_methods=("PARTIAL",))
    assert [t.raw for t in parsed.tokens] == ["blaZ"]
    assert {r.raw for r in parsed.rejected} == {"mecA=PARTIAL", "blaZ"}
    assert parsed.requested == ["mecA=PARTIAL", "blaZ", "blaZ"]
