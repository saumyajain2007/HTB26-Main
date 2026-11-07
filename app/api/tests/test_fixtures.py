"""The fixture files parse against the contract and keep its invariants."""

from __future__ import annotations

import itertools
import json
from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from conftest import BARICITINIB, COVID, REMDESIVIR
from pydantic import ValidationError

from oxhack_api.schemas import (
    REDOCK_SUCCESS_ANGSTROM,
    SHORTLIST_MAX,
    Candidate,
    Evaluation,
    Experiment,
    StructureList,
)
from oxhack_api.services.docking import FixtureDocking, unsupported_reason
from oxhack_api.services.jury import FixtureJury, JuryFixture, check_against
from oxhack_api.services.source import ExperimentFixture, FixtureSource
from oxhack_api.settings import FIXTURES_DIR


@pytest.fixture(scope="module")
def fixture() -> ExperimentFixture:
    return FixtureSource(FIXTURES_DIR).load(COVID)


@pytest.fixture(scope="module")
def experiment(fixture: ExperimentFixture) -> Experiment:
    """The fixture as a ready Experiment, so the Experiment-level checks run too."""
    return Experiment(
        id=uuid4(),
        status="ready",
        stage=None,
        error=None,
        disease=fixture.disease,
        data_releases=fixture.data_releases,
        ranking_method=fixture.ranking_method,
        ranking_settings=fixture.ranking_settings,
        jury_config=fixture.jury_config,
        targets=fixture.targets,
        network=fixture.network,
        candidates=fixture.candidates,
        jury=None,
        dock_jobs=[],
        fixture_note=fixture.fixture_note,
        created_at=datetime.now(UTC),
        archived_at=None,
    )


def by_id(fixture: ExperimentFixture) -> dict[str, Candidate]:
    return {c.candidate_id: c for c in fixture.candidates}


def test_every_disease_folder_parses() -> None:
    source = FixtureSource(FIXTURES_DIR)
    assert COVID in source.disease_ids()
    for disease_id in source.disease_ids():
        assert source.load(disease_id).disease.id == disease_id


def test_fixture_says_its_numbers_are_made_up(fixture: ExperimentFixture) -> None:
    assert "fictional" in fixture.fixture_note


def test_shortlist_only(experiment: Experiment) -> None:
    assert 0 < len(experiment.candidates) <= SHORTLIST_MAX


def test_not_scorable_has_no_network(fixture: ExperimentFixture) -> None:
    remdesivir = by_id(fixture)[REMDESIVIR]
    assert remdesivir.status == "not_scorable"
    assert remdesivir.network is None
    assert remdesivir.unscorable_reason == "no_retained_drug_targets"
    assert remdesivir.unscorable_detail
    assert remdesivir.targets == []


def test_status_invariants(fixture: ExperimentFixture) -> None:
    statuses = Counter(c.status for c in fixture.candidates)
    assert statuses["scored"]
    assert statuses["distance_only"]
    assert statuses["not_scorable"]
    for c in fixture.candidates:
        if c.status == "scored":
            assert c.network
            assert c.network.degree_matched_z is not None
            assert c.network.warning is None
        elif c.status == "distance_only":
            assert c.network
            assert c.network.degree_matched_z is None
            assert c.network.warning in ("zero_null_variance", "insufficient_degree_matched_pool")
            assert c.network.mean_distance is not None
        else:
            assert c.network is None
            assert c.unscorable_reason


def test_network_ranks_follow_plan_ordering(fixture: ExperimentFixture) -> None:
    """Scored by z, then distance, then ID; distance_only after every scored Candidate."""
    scored = [c for c in fixture.candidates if c.status == "scored" and c.network]
    distance_only = [c for c in fixture.candidates if c.status == "distance_only" and c.network]

    def z_key(c: Candidate) -> tuple[float, float, str]:
        assert c.network
        assert c.network.degree_matched_z is not None
        return (c.network.degree_matched_z, c.network.mean_distance, c.candidate_id)

    def rank(c: Candidate) -> int:
        assert c.network
        return c.network.rank

    assert [rank(c) for c in sorted(scored, key=z_key)] == sorted(rank(c) for c in scored)
    assert min(rank(c) for c in distance_only) > max(rank(c) for c in scored)


def test_selection_reasons_match_selected_by(fixture: ExperimentFixture) -> None:
    for c in fixture.candidates:
        sources = {
            reason.split("_")[1] if reason.startswith("initial") else reason.split("_")[0]
            for reason in c.selection_reasons
        }
        assert sources == set(c.selected_by), c.name


def test_known_answer_is_baricitinib(fixture: ExperimentFixture) -> None:
    assert [c.candidate_id for c in fixture.candidates if c.known_answer] == [BARICITINIB]


def test_safety_never_claims_safe(fixture: ExperimentFixture) -> None:
    for c in fixture.candidates:
        assert c.safety_status in ("warnings_recorded", "unknown")
        assert (c.safety_status == "warnings_recorded") == bool(c.warnings)


def test_evidence_links_are_https(fixture: ExperimentFixture) -> None:
    for c in fixture.candidates:
        for item in c.evidence:
            assert item.url.startswith("https://"), item.url


def test_targets_rank_order(fixture: ExperimentFixture) -> None:
    scores = [t.evidence_only_score for t in fixture.targets]
    assert scores == sorted(scores, reverse=True)
    assert [t.rank for t in fixture.targets] == list(range(1, len(scores) + 1))
    excluded = [t for t in fixture.targets if not t.retained]
    assert excluded
    assert all(t.excluded_reason for t in excluded)


def test_network_roles_follow_targets(fixture: ExperimentFixture) -> None:
    disease = {t.target_id for t in fixture.targets if t.retained}
    excluded = {t.target_id for t in fixture.targets if not t.retained}
    drug = {t.id for c in fixture.candidates for t in c.targets}
    nodes = {n.id: n for n in fixture.network.nodes}
    assert disease <= set(nodes), "every retained Disease Target is drawn"
    assert not excluded & set(nodes), "an excluded Target is never drawn"
    for node in fixture.network.nodes:
        expected = {
            (True, True): "both",
            (True, False): "disease",
            (False, True): "drug",
            (False, False): "link",
        }[(node.id in disease, node.id in drug)]
        assert node.role == expected, node.symbol


def test_paths_run_from_a_drug_target_to_a_disease_target(fixture: ExperimentFixture) -> None:
    disease = {t.target_id for t in fixture.targets if t.retained}
    edges = {frozenset((e.source, e.target)) for e in fixture.network.edges}
    for c in fixture.candidates:
        if c.network is None:
            continue
        path = c.network.path
        assert path[0] in {t.id for t in c.targets}, c.name
        assert path[-1] in disease, c.name
        assert all(frozenset(step) in edges for step in itertools.pairwise(path))
        if c.network.mean_distance == 0:
            assert len(path) == 1


def test_one_evidence_record_keeps_one_id(experiment: Experiment) -> None:
    # Experiment validation already checks this; make the shared items explicit.
    shared = Counter(item.id for c in experiment.candidates for item in c.evidence)
    assert any(count > 1 for count in shared.values())


def test_jury_fixture_matches_the_shortlist(experiment: Experiment) -> None:
    check_against(FixtureJury(FIXTURES_DIR).load(experiment), experiment)


def test_jury_consensus_is_computed_from_the_votes(experiment: Experiment) -> None:
    """Borda points, shared ranks and Kendall's W as defined in stream A's README."""
    jury = FixtureJury(FIXTURES_DIR).load(experiment)
    ids = [c.candidate_id for c in experiment.candidates]
    valid = [j.model_id for j in jury.jurors if j.status == "valid"]
    n, m = len(ids), len(valid)
    points = {i: sum(n - v.rank for v in jury.votes if v.candidate_id == i) for i in ids}
    rank_sums = {i: sum(v.rank for v in jury.votes if v.candidate_id == i) for i in ids}
    expected = {i: 1 + sum(1 for o in ids if points[o] > points[i]) for i in ids}
    assert {e.candidate_id: e.borda_points for e in jury.consensus.ranking} == points
    assert {e.candidate_id: e.rank for e in jury.consensus.ranking} == expected
    assert jury.consensus.jurors_counted == m
    s = sum((rank_sums[i] - m * (n + 1) / 2) ** 2 for i in ids)
    assert jury.agreement == round(12 * s / (m**2 * (n**3 - n)), 4)
    contested = [i for i in ids if len({v.decision for v in jury.votes if v.candidate_id == i}) > 1]
    assert jury.contested == contested


def test_jury_models_have_display_names(fixture: ExperimentFixture) -> None:
    families = [m.family for m in fixture.jury_config.models]
    assert len(set(families)) == len(families) == 3
    assert all(m.display_name for m in fixture.jury_config.models)


def test_jury_fixture_rejects_votes_from_invalid_jurors() -> None:
    raw = json.loads((FIXTURES_DIR / COVID / "jury.json").read_text())
    raw["jurors"][0]["status"] = "invalid"
    with pytest.raises(ValidationError):
        JuryFixture.model_validate(raw)


def test_structures_parse_and_controls_are_marked() -> None:
    listing = StructureList.model_validate_json((FIXTURES_DIR / "structures.json").read_text())
    ids = [s.id for s in listing.structures]
    assert ids == ["6WTO_A", "6WTN_A", "6O0K_A", "7BQU_A"]
    for structure in listing.structures:
        control = structure.control
        assert control.success_threshold == REDOCK_SUCCESS_ANGSTROM
        # A made-up RMSD is never presented as a measurement (build-reference C6).
        assert control.fixture == (control.rmsd is not None)
        assert structure.id.startswith(structure.pdb_id)


def test_every_dockable_candidate_has_a_supported_structure(fixture: ExperimentFixture) -> None:
    docking = FixtureDocking(FIXTURES_DIR)
    for c in fixture.candidates:
        supported = [
            s
            for s in docking.structures()
            if unsupported_reason(c, s, docking.ligand_smiles(c.candidate_id)) is None
        ]
        assert bool(supported) == c.dockable, c.name


def test_docking_controls_reuse_the_candidate_cache_key() -> None:
    docking = FixtureDocking(FIXTURES_DIR)
    [(control, _key)] = docking.seed_jobs()
    assert control.kind == "redock_control"
    assert control.fixture
    assert control.candidate_id == BARICITINIB
    assert control.structure_id == "6WTO_A"


def test_evaluation_fixture_parses() -> None:
    evaluation = Evaluation.model_validate_json((FIXTURES_DIR / "evaluation.json").read_text())
    assert {r.experiment for r in evaluation.results} == {"retrieval"}


def test_the_fixture_is_a_closeness_shortlist(experiment: Experiment) -> None:
    """Saved before the random walk ran: zscore, and no walk result on any Candidate."""
    assert experiment.ranking_settings.shortlist_method == "zscore"
    assert experiment.ranking_settings.restart_probability is None
    assert all(c.network.rwr is None for c in experiment.candidates if c.network)


def test_a_walk_result_goes_with_the_physical_rwr_method(experiment: Experiment) -> None:
    data = experiment.model_dump(mode="json")
    walked = json.loads(json.dumps(data))
    walked["ranking_settings"] |= {"shortlist_method": "physical_rwr", "restart_probability": 0.3}
    for rank, candidate in enumerate((c for c in walked["candidates"] if c["network"]), 1):
        candidate["network"]["rwr"] = {"rank": rank, "mass": 0.01 / rank}
    Experiment.model_validate(walked)
    with pytest.raises(ValidationError, match="random-walk result exactly for physical_rwr"):
        Experiment.model_validate(data | {"ranking_settings": walked["ranking_settings"]})
    with pytest.raises(ValidationError, match="random-walk result exactly for physical_rwr"):
        Experiment.model_validate(walked | {"ranking_settings": data["ranking_settings"]})
    with pytest.raises(ValidationError, match="restart_probability is set exactly"):
        Experiment.model_validate(
            walked
            | {"ranking_settings": walked["ranking_settings"] | {"restart_probability": None}}
        )
