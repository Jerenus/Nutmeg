from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import (
    CreateTicketBatchRequest,
    RemoveTicketLegRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.market import QuoteRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.tickets.models import TicketLegDraft
from nutmeg.ontology.wiring import build_ontology_kernel

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 24, 12, tzinfo=UTC)
PRIOR = {"home": 0.6, "draw": 0.25, "away": 0.15}


def _setup(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
        uow.market.insert_quote(
            QuoteRow(
                quote_id="quote-home",
                match_id="match-1",
                market_definition_id="md-had",
                selection_id="sel-had-home",
                provider="sporttery",
                bookmaker=None,
                decimal_odds=2.1,
                captured_at="2026-08-24T09:55:00+00:00",
                artifact_retrieval_id=None,
                quote_status="active",
            )
        )
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    forecast = ForecastActions(service).commit_forecast(
        CommitForecastRequest(
            match_id="match-1",
            market_definition_id="md-had",
            decision_session_id=None,
            prior_distribution=PRIOR,
            belief_distribution=PRIOR,
            factors=[],
            commitment_tier="judged",
            evidence_bundle_id=None,
            prior_snapshot_id=None,
            falsifier=None,
            actor_id="operator:owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m4:forecast:1",
            requested_at=AT,
        )
    )
    return kernel, forecast.result_refs[0].object_id


def _leg(forecast_revision_id: str, **changes: object) -> TicketLegDraft:
    values: dict[str, object] = {
        "leg_key": "match-1:md-had:home",
        "match_id": "match-1",
        "match_no": 1,
        "name": "Home FC - Away FC",
        "market_definition_id": "md-had",
        "selection_id": "sel-had-home",
        "outcome_key": "home",
        "faces": "3",
        "forecast_revision_id": forecast_revision_id,
        "entry_quote_id": "quote-home",
        "odds": 2.1,
        "line": None,
        "bucket": "main",
        "fair": PRIOR,
        "confidence": 4,
        "directional_flags": (),
        "nondirectional_flags": (),
        "anchor_integrity": "pass",
        "precedents": (),
    }
    values.update(changes)
    return TicketLegDraft(**values)


def _create_request(
    leg: TicketLegDraft,
    *,
    key: str = "m4:batch:create",
    role: ActorRole = ActorRole.JUDGE_OPERATOR,
) -> CreateTicketBatchRequest:
    return CreateTicketBatchRequest(
        run_date="2026-08-24",
        channel="jczq",
        account_id="acct-jczq",
        currency="CNY",
        deadline_at=DEADLINE,
        legs=[leg],
        actor_id="operator:owner" if role is ActorRole.JUDGE_OPERATOR else "model:test",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT,
    )


def _created_row(kernel, outcome):
    revision_id = next(
        ref.object_id
        for ref in outcome.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        return uow.tickets.batch_revision(revision_id)


def test_create_batch_writes_revision_cas_action_and_event(tmp_path: Path) -> None:
    kernel, forecast_id = _setup(tmp_path)

    outcome = kernel.protected_tickets.create_ticket_batch(
        _create_request(_leg(forecast_id))
    )

    assert outcome.status is ActionStatus.COMMITTED
    row = _created_row(kernel, outcome)
    assert row is not None
    assert row.revision_no == 1
    assert row.state == "draft"
    assert row.composition["total_stake_yuan"] == 100
    digest = row.source_artifact_id.removeprefix("sha256:")
    artifact_path = (
        kernel.paths.artifacts / "sha256" / digest[:2] / digest
    )
    assert artifact_path.read_bytes()
    with OntologyUnitOfWork(kernel.engine) as uow:
        events = uow.outbox.after(0, limit=100)
    assert any(event.action_id == outcome.action_id for event in events)


def test_create_batch_replays_without_duplicate_revision_or_artifact(
    tmp_path: Path,
) -> None:
    kernel, forecast_id = _setup(tmp_path)
    request = _create_request(_leg(forecast_id))

    first = kernel.protected_tickets.create_ticket_batch(request)
    second = kernel.protected_tickets.create_ticket_batch(request)

    assert second.action_id == first.action_id
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.count_batches() == 1
        assert uow.artifacts.count_artifacts() == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"forecast_revision_id": "fr-stale"}, "current committed"),
        ({"odds": 2.2}, "quote odds"),
        ({"selection_id": "sel-had-draw"}, "selection"),
    ],
)
def test_create_batch_rejects_stale_forecast_or_mismatched_quote(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    kernel, forecast_id = _setup(tmp_path)
    leg_values = {"forecast_revision_id": forecast_id, **changes}

    with pytest.raises(ValueError, match=message):
        kernel.protected_tickets.create_ticket_batch(
            _create_request(_leg(**leg_values))
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.count_batches() == 0


def test_ai_cannot_create_or_remove_ticket_batch(tmp_path: Path) -> None:
    kernel, forecast_id = _setup(tmp_path)
    denied = kernel.protected_tickets.create_ticket_batch(
        _create_request(
            _leg(forecast_id), key="m4:batch:ai", role=ActorRole.AI_ANALYST
        )
    )

    assert denied.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.count_batches() == 0


def test_remove_leg_creates_new_empty_revision_and_rejects_stale_version(
    tmp_path: Path,
) -> None:
    kernel, forecast_id = _setup(tmp_path)
    created = kernel.protected_tickets.create_ticket_batch(
        _create_request(_leg(forecast_id))
    )
    first = _created_row(kernel, created)
    assert first is not None
    request = RemoveTicketLegRequest(
        ticket_batch_id=first.ticket_batch_id,
        leg_key="match-1:md-had:home",
        expected_revision_no=1,
        actor_id="operator:owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="m4:batch:remove",
        requested_at=AT,
    )

    removed = kernel.protected_tickets.remove_ticket_leg(request)
    second = _created_row(kernel, removed)

    assert second is not None
    assert second.revision_no == 2
    assert second.supersedes_revision_id == first.ticket_batch_revision_id
    assert second.state == "empty"
    assert second.input_legs == []
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.batch_revision(first.ticket_batch_revision_id) == first
    with pytest.raises(Exception, match="expected 1"):
        kernel.protected_tickets.remove_ticket_leg(
            replace(request, idempotency_key="m4:batch:stale")
        )


def test_remove_absent_leg_fails_without_new_revision(tmp_path: Path) -> None:
    kernel, forecast_id = _setup(tmp_path)
    created = kernel.protected_tickets.create_ticket_batch(
        _create_request(_leg(forecast_id))
    )
    first = _created_row(kernel, created)
    assert first is not None

    with pytest.raises(ValueError, match="leg .* not found"):
        kernel.protected_tickets.remove_ticket_leg(
            RemoveTicketLegRequest(
                ticket_batch_id=first.ticket_batch_id,
                leg_key="missing-leg",
                expected_revision_no=1,
                actor_id="operator:owner",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="m4:batch:missing",
                requested_at=AT,
            )
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert len(uow.tickets.batch_history(first.ticket_batch_id)) == 1
