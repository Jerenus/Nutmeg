import pytest

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.contracts import ProductActionRequest
from nutmeg.product.errors import ProductActionNotAllowedError


def _forecast_payload() -> dict[str, object]:
    return {
        "match_id": "match-1",
        "market_definition_id": "md-had",
        "cutoff_at": "2026-08-24T10:00:00+00:00",
        "prior_distribution": {"home": 0.9, "draw": 0.05, "away": 0.05},
        "belief_distribution": {"home": 0.52, "draw": 0.28, "away": 0.2},
        "factors": [],
        "commitment_tier": "judged",
        "falsifier": "official lineup contradicts availability",
    }


def _request(
    action_type: str,
    payload: dict[str, object],
    *,
    key: str = "product:action:1",
    expected_versions: dict[str, int] | None = None,
) -> ProductActionRequest:
    return ProductActionRequest(
        action_type=action_type,
        idempotency_key=key,
        payload=payload,
        expected_versions=expected_versions or {},
    )


def test_forecast_commit_uses_server_snapshot_not_client_prior(product_services) -> None:
    response = product_services.actions.execute(
        _request(
            "commit_forecast",
            _forecast_payload(),
            expected_versions={"forecast:match-1:md-had": 1},
        )
    )

    assert response.status == "committed"
    assert response.result_refs[0].object_type == "forecast_revision"
    with OntologyUnitOfWork(product_services.kernel.engine) as uow:
        series_id = uow.decision.ensure_series("match-1", "md-had")
        revision = uow.decision.current_committed_revision(series_id)
    assert revision is not None
    assert revision.prior_snapshot_id == "snapshot-before"
    assert revision.prior_distribution == {"home": 0.5, "draw": 0.3, "away": 0.2}
    assert revision.information_cutoff_at == "2026-08-24T10:00:00+00:00"


def test_unknown_action_is_rejected_before_kernel_write(product_services) -> None:
    before = product_services.queries.health().action_counts.copy()

    with pytest.raises(ProductActionNotAllowedError, match="raw_sql"):
        product_services.actions.execute(
            _request("raw_sql", {"sql": "drop table matches"})
        )

    assert product_services.queries.health().action_counts == before


def test_ai_actor_cannot_be_spoofed_by_payload(product_services) -> None:
    request = _request(
        "record_adjudication",
        {
            "actor_role": "judge_operator",
            "subject_type": "claim",
            "subject_id": "claim-before",
            "decision": "approve",
            "reason": "model asks for approval",
            "evidence_rejected": [],
            "alternative": {},
        },
    )

    response = product_services.actions.execute(
        request,
        actor_id="model:analyst",
        actor_role=ActorRole.AI_ANALYST,
    )

    assert response.status == "rejected"


def test_stale_forecast_version_is_a_conflict(product_services) -> None:
    product_services.actions.execute(
        _request(
            "commit_forecast",
            _forecast_payload(),
            key="forecast:first",
            expected_versions={"forecast:match-1:md-had": 1},
        )
    )

    with pytest.raises(OptimisticConcurrencyError):
        product_services.actions.execute(
            _request(
                "commit_forecast",
                _forecast_payload(),
                key="forecast:stale",
                expected_versions={"forecast:match-1:md-had": 1},
            )
        )


def test_forecast_requires_semantic_expected_version(product_services) -> None:
    with pytest.raises(ValueError, match="expected version"):
        product_services.actions.execute(
            _request("commit_forecast", _forecast_payload())
        )
