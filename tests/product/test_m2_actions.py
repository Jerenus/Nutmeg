import pytest

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.identity.models import EntityType, ResolutionStatus
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.contracts import ProductActionRequest
from nutmeg.product.errors import ProductNotFoundError


def _merge_request(
    *,
    key: str = "ui:merge:1",
    entity_type: str = "team",
    from_id: str = "team-duplicate",
    into_id: str = "team-home",
    **extra_payload: object,
) -> ProductActionRequest:
    return ProductActionRequest(
        action_type="merge_entity",
        idempotency_key=key,
        payload={
            "entity_type": entity_type,
            "from_id": from_id,
            "into_id": into_id,
            "reason": "same provider-backed club",
            **extra_payload,
        },
        expected_versions={},
    )


def test_operator_can_merge_provisional_duplicate(m2_product_services) -> None:
    response = m2_product_services.actions.execute(_merge_request())

    assert response.status == "committed"
    assert response.result_refs[0].object_id == "team-home"
    with OntologyUnitOfWork(m2_product_services.kernel.engine) as uow:
        assert uow.identity.redirect("team-duplicate", EntityType.TEAM) == "team-home"
        assert (
            uow.identity.get_team("team-duplicate").resolution_status
            is ResolutionStatus.MERGED
        )


@pytest.mark.parametrize(
    "action_request",
    [_merge_request(from_id="missing"), _merge_request(into_id="missing")],
)
def test_merge_rejects_absent_team(
    m2_product_services,
    action_request: ProductActionRequest,
) -> None:
    with pytest.raises(ProductNotFoundError, match="team missing not found"):
        m2_product_services.actions.execute(action_request)


def test_merge_ignores_payload_actor_spoof(m2_product_services) -> None:
    response = m2_product_services.actions.execute(
        _merge_request(actor_id="owner", actor_role="judge_operator"),
        actor_id="model:test",
        actor_role=ActorRole.AI_ANALYST,
    )

    assert response.status == "rejected"
    with OntologyUnitOfWork(m2_product_services.kernel.engine) as uow:
        assert (
            uow.identity.get_team("team-duplicate").resolution_status
            is ResolutionStatus.PROVISIONAL
        )


@pytest.mark.parametrize(
    ("action_request", "message"),
    [
        (_merge_request(from_id="team-home", into_id="team-home"), "itself"),
        (_merge_request(entity_type="person"), "team entities"),
    ],
)
def test_merge_rejects_invalid_identity_shape(
    m2_product_services,
    action_request: ProductActionRequest,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        m2_product_services.actions.execute(action_request)


def test_merge_rejects_already_merged_source_with_new_action(
    m2_product_services,
) -> None:
    m2_product_services.actions.execute(_merge_request())

    with pytest.raises(ValueError, match="source.*provisional"):
        m2_product_services.actions.execute(_merge_request(key="ui:merge:second"))


def test_merge_rejects_merged_target(m2_product_services) -> None:
    m2_product_services.actions.execute(_merge_request())
    with OntologyUnitOfWork(m2_product_services.kernel.engine) as uow:
        uow.identity.mark_resolution_status(
            "team-away", EntityType.TEAM, ResolutionStatus.PROVISIONAL
        )

    with pytest.raises(ValueError, match="target.*merged"):
        m2_product_services.actions.execute(
            _merge_request(
                key="ui:merge:target-merged",
                from_id="team-away",
                into_id="team-duplicate",
            )
        )


def test_merge_replays_same_idempotency_key(m2_product_services) -> None:
    first = m2_product_services.actions.execute(_merge_request())
    replay = m2_product_services.actions.execute(_merge_request())

    assert replay.action_id == first.action_id
    assert replay.status == "committed"
