"""The network ranking adapter (stream B) on a tiny artificial protein network.

The bundle is built with stream B's own `build_artifacts`, from a made-up STRING links
file and mapping, the same way `python -m oxhack_api.prepare` builds the real one:

    G1 - G2 - G3 - G4 - G5 - G6 - G7 - G8     (the largest component)
              |
              G9 - G10
    G11 - G12                                  (a separate component)
    G13                                        (mapped, no links)

Disease Targets: G1, G5, G8, G11 (outside the largest component) and G14 (not mapped).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from oxhack_api import stream_b
from oxhack_api.app import open_ranking
from oxhack_api.schemas import Candidate
from oxhack_api.services.ranking import (
    EvidenceRanking,
    NetworkRanking,
    Ranked,
    RankingInput,
    subgraph,
)
from oxhack_api.settings import Settings


def gene(i: int) -> str:
    return f"ENSG{i:011d}"


def protein(i: int) -> str:
    return f"9606.ENSP{i:011d}"


LINKS = [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (3, 9), (9, 10), (11, 12)]
WEAK = [(1, 8)]
"""A link below the experiments threshold: never in the graph."""
SCORES = {gene(1): 0.9, gene(5): 0.8, gene(11): 0.7, gene(14): 0.6, gene(8): 0.1}
RELEASE = "opentargets-26.09"


def drug(number: int, *targets: int, regulator: str = "FDA") -> dict[str, Any]:
    return {
        "drug_id": f"CHEMBL{number}",
        "name": f"DRUG {number}",
        "source_chembl_ids": [f"CHEMBL{number}"],
        "approval": {"sources": [regulator] if regulator else [], "disease_ids": []},
        "targets": [
            {"target_id": gene(t), "name": f"G{t}", "action_type": "INHIBITOR"} for t in targets
        ],
        "unmapped": [],
    }


DRUGS = [
    drug(1, 2),  # one step from G1
    drug(2, 5),  # acts on the Disease Target G5 itself
    drug(3, 10),  # four steps from G1 and G5
    drug(4, 11),  # only a Disease Target outside the largest component
    drug(5, 6, regulator=""),  # no regulator approval: stream B leaves it out
]


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("network")
    mapping: dict[str, Any] = {
        "releases": ["string-12.5", RELEASE],
        "coverage": {},
        "mappings": [
            {"string_id": protein(i), "target_id": gene(i), "status": "mapped", "reason": None}
            for i in range(1, 14)
        ],
    }
    (root / "string_id_map.json").write_text(json.dumps(mapping))
    header = (
        "protein1 protein2 homology experiments experiments_transferred database "
        "database_transferred textmining textmining_transferred combined_score\n"
    )
    rows = [
        f"{protein(a)} {protein(b)} 0 {experiments} 0 0 0 0 0 900\n"
        for pairs, experiments in ((LINKS, 500), (WEAK, 100))
        for x, y in pairs
        for a, b in ((x, y), (y, x))
    ]
    with gzip.open(root / "links.txt.gz", "wt") as links:
        links.write(header + "".join(rows))
    stream_b.build_bundle(
        root / "string_id_map.json", root / "links.txt.gz", root / "ranking" / "bundle"
    )
    (root / "drug_targets.json").write_text(
        json.dumps({"releases": [RELEASE, "chembl-37"], "rules": {}, "drugs": DRUGS})
    )
    return root


def request() -> RankingInput:
    selected = sorted(SCORES, key=lambda g: (-SCORES[g], g))
    return RankingInput(
        disease_id="MONDO_0000001",
        target_ids=selected,
        scores=SCORES,
        drugs=DRUGS,
        symbols={gene(i): f"G{i}" for i in range(1, 15)},
    )


def ranking(data: Path, **kwargs: Any) -> NetworkRanking:
    return NetworkRanking(data / "ranking" / "bundle", data / "drug_targets.json", **kwargs)


def by_id(shortlist: list[Ranked]) -> dict[str, Ranked]:
    return {r.candidate_id: r for r in shortlist}


def test_maps_stream_b_statuses_ranks_routes_and_reasons(data: Path) -> None:
    result = ranking(data, min_bin_size=1).rank(request(), frozenset())
    ranked = by_id(result.shortlist)
    # The unapproved drug never enters; the other four do (three by network, one by evidence).
    assert set(ranked) == {"CHEMBL1", "CHEMBL2", "CHEMBL3", "CHEMBL4"}

    overlap, near, far = ranked["CHEMBL2"], ranked["CHEMBL1"], ranked["CHEMBL3"]
    for placed in (overlap, near, far):
        assert placed.status == "scored"
        assert placed.network is not None
        assert placed.network.graph_version == "string-12.5"
        assert placed.network.degree_matched_z is not None
        assert placed.selected_by[0] == "network"
    assert overlap.network
    assert overlap.network.path == [gene(5)]
    assert overlap.network.mean_distance == 0
    assert near.network
    assert near.network.path == [gene(2), gene(1)]
    # Four steps to G1 or G5: the tie goes to the lower Ensembl ID, through the smaller IDs.
    assert far.network
    assert far.network.path == [gene(10), gene(9), gene(3), gene(2), gene(1)]
    assert far.network.mean_distance == 4
    assert [r.network.rank for r in (overlap, near, far) if r.network] == [1, 2, 3]

    outside = ranked["CHEMBL4"]
    assert outside.status == "not_scorable"
    assert outside.network is None
    assert outside.unscorable_reason == "no_retained_drug_targets"
    assert outside.selected_by == ["evidence"]
    assert outside.routes == []
    # Evidence ranks: G1 0.9 (drug 2 has G5 0.8, drug 4 G11 0.7); none for no direct support.
    assert outside.direct_evidence_rank == 2
    assert overlap.direct_evidence_rank == 1
    assert near.direct_evidence_rank is None
    assert far.direct_evidence_rank is None

    assert result.excluded_targets == {
        gene(11): "outside_largest_component",
        gene(14): "not_in_graph",
    }
    assert result.retained_target_ids == [gene(1), gene(5), gene(8)]
    assert result.graph
    assert result.graph["graph_version"] == "string-12.5"
    assert result.full
    assert result.full["summary"]["eligible_candidates"] == 4


def test_selection_reasons_follow_stream_b_quotas(data: Path) -> None:
    result = ranking(data, min_bin_size=1).rank(request(), frozenset())
    ranked = by_id(result.shortlist)
    assert ranked["CHEMBL2"].selected_by == ["network", "evidence"]
    assert ranked["CHEMBL2"].selection_reasons == [
        "initial_network_quota",
        "initial_evidence_quota",
    ]
    assert ranked["CHEMBL4"].selection_reasons == ["initial_evidence_quota"]
    assert [r.candidate_id for r in result.shortlist][:3] == ["CHEMBL2", "CHEMBL1", "CHEMBL3"]


def test_tiny_degree_groups_give_distance_only_never_a_zero(data: Path) -> None:
    """Stream B's default needs 100 proteins per degree group; ten can't support it."""
    result = ranking(data).rank(request(), frozenset())
    placed = [r for r in result.shortlist if r.network is not None]
    assert placed
    for r in placed:
        assert r.status == "distance_only"
        assert r.network is not None
        assert r.network.degree_matched_z is None
        assert r.network.warning == "insufficient_degree_matched_pool"
    assert ranking(data).settings().min_bin_size == 100


def test_excluding_a_drug_reranks_without_it_and_keeps_the_others_scores(data: Path) -> None:
    network = ranking(data, min_bin_size=1)
    full = by_id(network.rank(request(), frozenset()).shortlist)
    without = by_id(network.rank(request(), frozenset({"CHEMBL2"})).shortlist)
    assert "CHEMBL2" not in without
    near, far = without["CHEMBL1"].network, without["CHEMBL3"].network
    assert near
    assert far
    assert (near.rank, far.rank) == (1, 2)
    assert near.degree_matched_z == (full["CHEMBL1"].network or near).degree_matched_z
    assert without["CHEMBL4"].direct_evidence_rank == 1


def test_the_drawn_network_holds_every_route_with_roles(data: Path) -> None:
    result = ranking(data, min_bin_size=1).rank(request(), frozenset())
    graph = result.network
    assert graph is not None
    roles = {node.id: node.role for node in graph.nodes}
    assert roles[gene(1)] == "disease"
    assert roles[gene(5)] == "both"
    assert roles[gene(2)] == "drug"
    assert roles[gene(10)] == "drug"
    assert roles[gene(9)] == roles[gene(3)] == "link"
    # Disease Targets linked to a drawn protein join; G8's only link is to G7, not drawn.
    assert gene(8) not in roles
    assert {node.symbol for node in graph.nodes} >= {"G1", "G5", "G10"}
    edges = {(e.source, e.target) for e in graph.edges}
    assert (gene(1), gene(2)) in edges
    assert (gene(9), gene(10)) in edges
    assert all(a in roles and b in roles for a, b in edges)
    for ranked in result.shortlist:
        if ranked.network:
            assert set(ranked.network.path) <= set(roles)


def test_the_drawn_network_keeps_every_path_even_past_its_limit(data: Path) -> None:
    result = ranking(data, min_bin_size=1).rank(request(), frozenset())
    assert result.full is not None
    shortlisted = {r.candidate_id for r in result.shortlist}
    candidates = [c for c in result.full["candidates"] if c["candidate_id"] in shortlisted]
    bundle = stream_b.Bundle(data / "ranking" / "bundle")
    try:
        small = subgraph(
            bundle,
            result.shortlist,
            candidates,
            request().target_ids,
            set(result.retained_target_ids),
            request().symbols,
            limit=2,
        )
    finally:
        bundle.close()
    ids = {node.id for node in small.nodes}
    for ranked in result.shortlist:
        if ranked.network:
            assert set(ranked.network.path) <= ids
    assert len(ids) == 6


def test_candidates_built_from_the_ranking_validate(data: Path) -> None:
    """A not_scorable network Candidate needs its plain reason; a placed one its path."""
    from oxhack_api.services import plain

    result = ranking(data, min_bin_size=1).rank(request(), frozenset())
    for position, ranked in enumerate(result.shortlist, 1):
        Candidate(
            candidate_id=ranked.candidate_id,
            name="Drug",
            status=ranked.status,
            shortlist_rank=position,
            selected_by=ranked.selected_by,
            selection_reasons=ranked.selection_reasons,
            network=ranked.network,
            unscorable_reason=ranked.unscorable_reason,
            unscorable_detail=None
            if ranked.unscorable_reason is None
            else plain.unscorable(ranked.unscorable_reason, "Drug", "the disease"),
            direct_evidence_rank=ranked.direct_evidence_rank,
            shared_target_count=0,
            targets=[],
            evidence=[],
            warnings=[],
            safety_status="unknown",
            dockable=False,
            pubchem_cid=None,
            known_answer=False,
        )


def test_live_mode_picks_the_network_ranking_only_when_the_bundle_exists(
    data: Path, tmp_path: Path
) -> None:
    present = Settings(data_dir=data, network_dir=data / "ranking" / "bundle")
    chosen = open_ranking(present)
    assert isinstance(chosen, NetworkRanking)
    assert chosen.method == "network"
    assert chosen.releases == ["string-12.5"]
    absent = Settings(data_dir=tmp_path)
    assert absent.network_dir == tmp_path / "ranking" / "string-12.5-c700-e400"
    fallback = open_ranking(absent)
    assert isinstance(fallback, EvidenceRanking)
    assert fallback.method == "evidence_only"


def test_the_random_walk_fills_the_network_places_by_default(data: Path) -> None:
    network = ranking(data, min_bin_size=1)
    settings = network.settings()
    assert settings.shortlist_method == "physical_rwr"
    assert settings.restart_probability == 0.3
    result = network.rank(request(), frozenset())
    placed = [r for r in result.shortlist if r.network is not None]
    walks = [r.network.rwr for r in placed if r.network]
    assert all(walk is not None for walk in walks)
    # Ranked by mass, highest first: G5 is a restart Target, G2 sits next to G1, G10 is far.
    by_walk = sorted(placed, key=lambda r: r.network.rwr.rank if r.network and r.network.rwr else 0)
    assert [r.candidate_id for r in by_walk] == ["CHEMBL2", "CHEMBL1", "CHEMBL3"]
    masses = [r.network.rwr.mass for r in by_walk if r.network and r.network.rwr]
    assert masses == sorted(masses, reverse=True)
    assert masses[-1] > 0
    assert result.full is not None
    assert result.full["shortlist_selection"]["selection_method"] == "physical_rwr"


def test_the_network_places_follow_the_walk_not_closeness(data: Path) -> None:
    """With one network place, the drug the walk ranks first takes it, whatever its z-score."""
    network = ranking(data, min_bin_size=1)
    full = network.rank(request(), frozenset()).full
    assert full is not None
    swapped = json.loads(json.dumps(full))
    for candidate in swapped["candidates"]:
        walk = candidate["rwr"]["physical"]
        if candidate["candidate_id"] == "CHEMBL3":  # last by closeness
            walk["score"] = 1.0
    swapped.pop("shortlist_selection")
    swapped.pop("legacy_shortlist_selection")
    one = stream_b.Settings(network_slots=1, evidence_slots=0)
    assert stream_b.select(swapped, "physical_rwr", one)["shortlist"] == ["CHEMBL3"]
    assert stream_b.select(swapped, "zscore", one) is swapped


def test_zscore_keeps_the_original_closeness_shortlist(data: Path) -> None:
    network = ranking(data, min_bin_size=1, shortlist_method="zscore")
    settings = network.settings()
    assert (settings.shortlist_method, settings.restart_probability) == ("zscore", None)
    result = network.rank(request(), frozenset())
    assert [r.candidate_id for r in result.shortlist][:3] == ["CHEMBL2", "CHEMBL1", "CHEMBL3"]
    assert all(r.network.rwr is None for r in result.shortlist if r.network)
    assert result.full is not None
    assert "shortlist_selection" not in result.full


def test_excluding_a_drug_renumbers_the_walk_ranks(data: Path) -> None:
    network = ranking(data, min_bin_size=1)
    full = by_id(network.rank(request(), frozenset()).shortlist)
    without = by_id(network.rank(request(), frozenset({"CHEMBL2"})).shortlist)
    near, far = without["CHEMBL1"].network, without["CHEMBL3"].network
    before = full["CHEMBL1"].network
    walks = [n.rwr if n else None for n in (near, far, before)]
    assert all(walks)
    near_walk, far_walk, before_walk = [w for w in walks if w]
    assert (near_walk.rank, far_walk.rank) == (1, 2)
    assert near_walk.mass == before_walk.mass
