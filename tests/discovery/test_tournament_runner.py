from __future__ import annotations

from nutmeg.discovery.tournament_runner import finish_frozen_tournament, prepare_tournament
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_discovery_governance_actions import _create_request, _rig, _seed


def test_frozen_tournament_preparation_reproduces_matrix_and_proof(tmp_path):
    actions, engine = _rig(tmp_path)
    _seed(engine)
    assert actions.create_tournament(_create_request()).status is ActionStatus.COMMITTED

    first = prepare_tournament(engine, "t-1")
    second = prepare_tournament(engine, "t-1")
    assert first == second
    assert len(first.results) == 60
    assert first.winner_policy_revision_id == "policy-1"

    outcome = finish_frozen_tournament(engine, "t-1", requested_at=_create_request().requested_at)
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.tournament_completion("t-1").reproduction_hash == first.proof_hash
        assert [row.world_id for row in uow.discovery.exposed_holdouts("family-1")] == ["world-2"]
