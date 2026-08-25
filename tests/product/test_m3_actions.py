from datetime import timedelta

import pytest

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.product.contracts import ProductActionRequest
from nutmeg.product.errors import ProductActionBlockedError, ProductNotFoundError

from .conftest import CLOCK

ACTION_AT = CLOCK + timedelta(hours=1)


def _request(
    action_type: str,
    payload: dict[str, object],
    *,
    key: str,
    expected_versions: dict[str, int] | None = None,
) -> ProductActionRequest:
    return ProductActionRequest(
        action_type=action_type,
        idempotency_key=key,
        payload=payload,
        expected_versions=expected_versions or {},
    )


def _forecast_payload(
    *,
    cutoff_at: str = "2026-08-24T11:00:00+00:00",
    belief: dict[str, float] | None = None,
    agent_proposal_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "match_id": "match-1",
        "market_definition_id": "md-had",
        "cutoff_at": cutoff_at,
        "belief_distribution": belief
        or {"home": 0.46, "draw": 0.32, "away": 0.22},
        "factors": [],
        "commitment_tier": "judged",
        "falsifier": "official lineup restores midfield protection",
    }
    if agent_proposal_id is not None:
        payload["agent_proposal_id"] = agent_proposal_id
    return payload


def _create_proposal(m3_product_services) -> str:
    response = m3_product_services.actions.execute(
        _request(
            "create_agent_proposal",
            {
                "subject_type": "match",
                "subject_id": "match-1",
                "proposal_type": "forecast_investigation",
                "information_cutoff_at": CLOCK.isoformat(),
                "operator_prompt": "Compare the availability claims.",
                "payload": {
                    "summary": "Draw risk remains material.",
                    "scenarios": [],
                    "proposed_belief": {
                        "home": 0.46,
                        "draw": 0.32,
                        "away": 0.22,
                    },
                    "factors": [],
                    "falsifier": "official lineup restores midfield protection",
                    "conflicts": ["availability_risk"],
                    "missing_evidence": ["official lineup"],
                },
                "citation_refs": [
                    {"object_type": "observation", "object_id": "obs-before"}
                ],
                "model_name": "fixture-copilot",
                "model_version": "1",
            },
            key="proposal:m3:create",
        ),
        actor_id="model:fixture-copilot",
        actor_role=ActorRole.AI_ANALYST,
    )
    assert response.status == "committed"
    return response.result_refs[0].object_id


def _resolve_proposal(m3_product_services, proposal_id: str) -> None:
    response = m3_product_services.actions.execute(
        _request(
            "resolve_agent_proposal",
            {"agent_proposal_id": proposal_id, "resolution": "approved"},
            key="proposal:m3:approve",
            expected_versions={f"agent_proposal:{proposal_id}": 1},
        )
    )
    assert response.status == "committed"


def test_claim_status_actions_use_server_assigned_judge(m3_product_services) -> None:
    response = m3_product_services.actions.execute(
        _request(
            "dispute_claim",
            {"claim_id": "claim-before"},
            key="claim:dispute:product",
        )
    )

    assert response.status == "committed"
    at_action = m3_product_services.queries.match("match-1", as_of=ACTION_AT)
    claim = next(
        item for item in at_action.evidence.claims if item.claim_id == "claim-before"
    )
    assert claim.status == "disputed"
    action = next(
        item
        for item in m3_product_services.queries.actions(limit=100).items
        if item.action_id == response.action_id
    )
    assert action.actor_role == "judge_operator"


def test_claim_action_rejects_absent_claim(m3_product_services) -> None:
    with pytest.raises(ProductNotFoundError, match="claim missing not found"):
        m3_product_services.actions.execute(
            _request(
                "verify_claim",
                {"claim_id": "missing"},
                key="claim:missing",
            )
        )


def test_ai_cannot_adjudicate_claim_or_commit_forecast(m3_product_services) -> None:
    claim_response = m3_product_services.actions.execute(
        _request(
            "verify_claim",
            {"claim_id": "claim-before"},
            key="denied:verify_claim",
        ),
        actor_id="model:m3",
        actor_role=ActorRole.AI_ANALYST,
    )
    forecast_response = m3_product_services.actions.execute(
        _request(
            "commit_forecast",
            _forecast_payload(cutoff_at=CLOCK.isoformat()),
            key="denied:commit_forecast",
            expected_versions={"forecast:match-1:md-had": 1},
        ),
        actor_id="model:m3",
        actor_role=ActorRole.AI_ANALYST,
    )

    assert claim_response.status == "rejected"
    assert forecast_response.status == "rejected"


def test_blocking_conflict_prevents_forecast_but_not_proposal(
    m3_product_services,
) -> None:
    proposal_id = _create_proposal(m3_product_services)
    assert proposal_id

    with pytest.raises(ProductActionBlockedError, match="source_conflict_unresolved"):
        m3_product_services.actions.execute(
            _request(
                "commit_forecast",
                _forecast_payload(cutoff_at="2026-08-24T10:30:00+00:00"),
                key="forecast:blocked:conflict",
                expected_versions={"forecast:match-1:md-had": 1},
            )
        )


def test_forecast_requires_approved_matching_proposal(m3_product_services) -> None:
    proposal_id = _create_proposal(m3_product_services)
    m3_product_services.actions.execute(
        _request(
            "retract_claim",
            {"claim_id": "claim-conflict"},
            key="claim:retract:pending-proposal",
        )
    )
    with pytest.raises(ProductActionBlockedError, match="proposal.*approved"):
        m3_product_services.actions.execute(
            _request(
                "commit_forecast",
                _forecast_payload(agent_proposal_id=proposal_id),
                key="forecast:pending-proposal",
                expected_versions={
                    "forecast:match-1:md-had": 1,
                    f"agent_proposal:{proposal_id}": 1,
                },
            )
        )

    _resolve_proposal(m3_product_services, proposal_id)
    with pytest.raises(ProductActionBlockedError, match="belief"):
        m3_product_services.actions.execute(
            _request(
                "commit_forecast",
                _forecast_payload(
                    belief={"home": 0.47, "draw": 0.31, "away": 0.22},
                    agent_proposal_id=proposal_id,
                ),
                key="forecast:proposal-belief-mismatch",
                expected_versions={
                    "forecast:match-1:md-had": 1,
                    f"agent_proposal:{proposal_id}": 2,
                },
            )
        )


def test_approved_proposal_commits_bundled_forecast(m3_product_services) -> None:
    proposal_id = _create_proposal(m3_product_services)
    _resolve_proposal(m3_product_services, proposal_id)
    m3_product_services.actions.execute(
        _request(
            "retract_claim",
            {"claim_id": "claim-conflict"},
            key="claim:retract:for-commit",
        )
    )

    response = m3_product_services.actions.execute(
        _request(
            "commit_forecast",
            _forecast_payload(agent_proposal_id=proposal_id),
            key="forecast:proposal:commit",
            expected_versions={
                "forecast:match-1:md-had": 1,
                f"agent_proposal:{proposal_id}": 2,
            },
        )
    )

    assert response.status == "committed"
    detail = m3_product_services.queries.match("match-1", as_of=ACTION_AT)
    assert detail.forecasts[-1].evidence_status == "bundled"
    assert detail.forecasts[-1].belief_distribution == {
        "home": 0.46,
        "draw": 0.32,
        "away": 0.22,
    }


def test_stale_proposal_version_is_an_optimistic_conflict(m3_product_services) -> None:
    proposal_id = _create_proposal(m3_product_services)
    _resolve_proposal(m3_product_services, proposal_id)
    m3_product_services.actions.execute(
        _request(
            "retract_claim",
            {"claim_id": "claim-conflict"},
            key="claim:retract:stale-proposal",
        )
    )

    with pytest.raises(OptimisticConcurrencyError, match="proposal"):
        m3_product_services.actions.execute(
            _request(
                "commit_forecast",
                _forecast_payload(agent_proposal_id=proposal_id),
                key="forecast:stale-proposal",
                expected_versions={
                    "forecast:match-1:md-had": 1,
                    f"agent_proposal:{proposal_id}": 1,
                },
            )
        )
