from datetime import UTC, date, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import RemoveTicketLegRequest
from nutmeg.ontology.repository.decision import ForecastRevisionRow
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.identity import MatchRevisionRow, TeamAppearanceRow
from nutmeg.ontology.repository.market import QuoteRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from tests.ontology.test_protected_ticket_actions import (
    AT,
    _approve_request,
    _create_request,
    _created_row,
    _leg,
    _setup,
)

CUTOFF = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _queries(kernel) -> ProductQueryService:
    return ProductQueryService(ProductReadRepository(kernel.engine), kernel)


def _insert_match(uow, match_id: str, kickoff: str) -> None:
    uow.identity.insert_match(match_id)
    uow.identity.insert_match_revision(
        MatchRevisionRow(
            match_revision_id=f"revision-{match_id}",
            match_id=match_id,
            version=1,
            competition_edition_id=None,
            scheduled_at=kickoff,
            schedule_status="confirmed",
            venue_id=None,
            status="scheduled",
            round_label=None,
            recorded_at="2026-08-24T08:00:00+00:00",
            supersedes_revision_id=None,
        )
    )
    uow.identity.insert_team_appearance(
        TeamAppearanceRow(
            f"appearance-{match_id}-home", match_id, "team-home", "home"
        )
    )
    uow.identity.insert_team_appearance(
        TeamAppearanceRow(
            f"appearance-{match_id}-away", match_id, "team-away", "away"
        )
    )


def _insert_forecast(
    uow,
    *,
    match_id: str,
    forecast_id: str,
    revision_no: int,
    made_at: str,
) -> None:
    series_id = uow.decision.ensure_series(match_id, "md-had")
    uow.decision.insert_revision(
        ForecastRevisionRow(
            forecast_revision_id=forecast_id,
            forecast_series_id=series_id,
            decision_session_id=None,
            revision_no=revision_no,
            status="committed",
            made_at=made_at,
            information_cutoff_at=None,
            prior_snapshot_id=None,
            prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
            belief_distribution={"home": 0.55, "draw": 0.27, "away": 0.18},
            evidence_bundle_id=None,
            falsifier=None,
            actor_id="operator:owner",
            model_name=None,
            model_version=None,
            policy_version="governance-v1",
            commitment_tier="judged",
            evidence_coverage=None,
            evidence_quality=None,
            forecast_stability=None,
            supersedes_revision_id=None,
        )
    )


def _insert_quote(
    uow,
    *,
    quote_id: str,
    match_id: str,
    captured_at: str,
    selection_id: str = "sel-had-home",
) -> None:
    uow.market.insert_quote(
        QuoteRow(
            quote_id=quote_id,
            match_id=match_id,
            market_definition_id="md-had",
            selection_id=selection_id,
            provider="sporttery",
            bookmaker=None,
            decimal_odds=2.1,
            captured_at=captured_at,
            artifact_retrieval_id=None,
            quote_status="active",
        )
    )


def test_workbench_uses_current_forecast_and_latest_active_quote_at_cutoff(
    seeded_product,
) -> None:
    kernel = seeded_product.kernel
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
        # This is 09:30Z and must be visible despite looking later lexically.
        _insert_quote(
            uow,
            quote_id="quote-offset-past",
            match_id="match-1",
            captured_at="2026-08-24T10:30:00+01:00",
        )
        # This is 10:45Z and must not leak despite looking earlier lexically.
        _insert_quote(
            uow,
            quote_id="quote-offset-future",
            match_id="match-1",
            captured_at="2026-08-24T09:45:00-01:00",
        )
        series_id = uow.decision.ensure_series("match-1", "md-had")
        uow.decision.insert_revision(
            ForecastRevisionRow(
                forecast_revision_id="fr-offset-future",
                forecast_series_id=series_id,
                decision_session_id=None,
                revision_no=2,
                status="committed",
                made_at="2026-08-24T09:30:00-01:00",
                information_cutoff_at=None,
                prior_snapshot_id=None,
                prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
                belief_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
                evidence_bundle_id=None,
                falsifier=None,
                actor_id="operator:owner",
                model_name=None,
                model_version=None,
                policy_version="governance-v1",
                commitment_tier="judged",
                evidence_coverage=None,
                evidence_quality=None,
                forecast_stability=None,
                supersedes_revision_id="fr-legacy",
            )
        )

    response = _queries(kernel).ticket_workbench(date(2026, 8, 24), as_of=CUTOFF)

    [match] = response.matches
    assert match.match_id == "match-1"
    assert match.forecast_revision_id == "fr-legacy"
    assert match.belief_distribution == {"home": 0.52, "draw": 0.28, "away": 0.2}
    home = next(item for item in match.selections if item.outcome_key == "home")
    assert home.quote_id == "quote-offset-past"
    assert home.odds == 2.1
    assert home.eligible is True
    assert match.eligible is True
    dumped = response.model_dump(mode="json")
    assert dumped["date"] == "2026-08-24"
    assert dumped["as_of"] == "2026-08-24T10:00:00Z"
    assert "quote-offset-future" not in str(dumped)
    assert "fr-offset-future" not in str(dumped)


def test_workbench_exposes_explicit_no_forecast_and_no_quote_reasons(
    seeded_product,
) -> None:
    kernel = seeded_product.kernel
    with OntologyUnitOfWork(kernel.engine) as uow:
        _insert_match(uow, "match-no-forecast", "2026-08-24T13:00:00+00:00")
        _insert_quote(
            uow,
            quote_id="quote-no-forecast",
            match_id="match-no-forecast",
            captured_at="2026-08-24T09:50:00+00:00",
        )
        _insert_match(uow, "match-no-quote", "2026-08-24T14:00:00+00:00")
        _insert_forecast(
            uow,
            match_id="match-no-quote",
            forecast_id="fr-no-quote",
            revision_no=1,
            made_at="2026-08-24T09:40:00+00:00",
        )

    response = _queries(kernel).ticket_workbench(date(2026, 8, 24), as_of=CUTOFF)
    matches = {item.match_id: item for item in response.matches}

    assert matches["match-no-forecast"].block_reasons == ["no_committed_forecast"]
    assert matches["match-no-forecast"].eligible is False
    assert matches["match-no-quote"].block_reasons == ["no_active_quote"]
    assert matches["match-no-quote"].eligible is False


def test_batch_history_has_semantic_diffs_and_artifact_detail_is_safe(
    tmp_path: Path,
) -> None:
    history_kernel, forecast_id = _setup(tmp_path / "history")
    created = history_kernel.protected_tickets.create_ticket_batch(
        _create_request(_leg(forecast_id), key="m4:history:create")
    )
    draft = _created_row(history_kernel, created)
    assert draft is not None

    history_kernel.protected_tickets.remove_ticket_leg(
        RemoveTicketLegRequest(
            ticket_batch_id=draft.ticket_batch_id,
            leg_key="match-1:md-had:home",
            expected_revision_no=1,
            actor_id="operator:owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m4:history:remove",
            requested_at=AT,
        )
    )

    history = _queries(history_kernel).ticket_batch(draft.ticket_batch_id)
    assert [item.revision_no for item in history.revisions] == [1, 2]
    assert history.revisions[0].added_leg_keys == ["match-1:md-had:home"]
    assert history.revisions[1].removed_leg_keys == ["match-1:md-had:home"]
    assert history.revisions[1].state == "empty"

    artifact_kernel, artifact_forecast_id = _setup(tmp_path / "artifact")
    artifact_created = artifact_kernel.protected_tickets.create_ticket_batch(
        _create_request(_leg(artifact_forecast_id), key="m4:artifact:create")
    )
    artifact_draft = _created_row(artifact_kernel, artifact_created)
    assert artifact_draft is not None
    approved = artifact_kernel.protected_tickets.approve_ticket_batch(
        _approve_request(
            artifact_draft.ticket_batch_id,
            1,
            key="m4:artifact:approve",
        )
    )
    artifact_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )

    detail = _queries(artifact_kernel).ticket_artifact(artifact_id)
    dumped = detail.model_dump(mode="json")
    assert detail.ticket_hash == detail.source_artifact_id.removeprefix("sha256:")
    assert detail.amount == 100.0
    assert detail.placement_state == "unplaced"
    assert detail.confirmation_state == "not_issued"
    assert "receipt_bytes" not in str(dumped)
    assert "nonce_hash" not in str(dumped)
