from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.protected_ticket_actions import (
    ApproveOperatorTicketBatchRequest,
    CreateOperatorTicketBatchRequest,
    CurrentOperatorCandidateAudit,
    ProtectedTicketActions,
)
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.operator.confirmation import (
    ArtifactTerminalKind,
    ArtifactTerminalReason,
    consume_artifact_terminal,
)
from nutmeg.ontology.operator.decision_actions import (
    NoTicketDecisionContext,
    RecordNoTicketRequest,
    SelectTicketCandidateRequest,
    SupersedeNoTicketRequest,
)
from nutmeg.ontology.operator.models import (
    ConfirmationChallengeHeadRow,
    ConfirmationChallengeRevisionRow,
)
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.test_candidate_actions import (
    _generate,
    _generation_request,
    _ready_fixture,
)
from tests.ontology.operator.test_judgment_actions import WORK_ITEM_ID

AT = datetime(2026, 9, 4, 9, tzinfo=UTC)
TASK_FAMILY_ID = "jczq:2026-09-04"
LANE = "jczq"
BUSINESS_KEY = "2026-09-04"


def _clean_candidate_audit(_uow, _selected) -> CurrentOperatorCandidateAudit:
    return CurrentOperatorCandidateAudit(
        policy_version="operator-candidate-audit-v1",
        completed_audit_kinds=(
            "legs",
            "prescription_difference",
            "budget",
            "deployment",
        ),
        findings=(),
    )


@dataclass(frozen=True, slots=True)
class NoTicketFixture:
    engine: object
    actions: object
    context: NoTicketDecisionContext


@dataclass(frozen=True, slots=True)
class ArtifactFixture(NoTicketFixture):
    action_service: object
    artifact_id: str
    cutoff: datetime


def _fixture(tmp_path: Path) -> NoTicketFixture:
    judgment = _ready_fixture(tmp_path).judgment
    context = judgment.decision_actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        as_of=AT + timedelta(minutes=1),
    )
    return NoTicketFixture(
        engine=judgment.engine,
        actions=judgment.decision_actions,
        context=context,
    )


def _request(
    fixture: NoTicketFixture,
    *,
    reason_code: str = "operator_discretion",
    reason_basis: str = "operator_judgment",
    rule_ids: tuple[str, ...] = (),
    role: ActorRole = ActorRole.JUDGE_OPERATOR,
    key: str = "no-ticket:record:1",
    requested_at: datetime = AT + timedelta(minutes=1),
    context: NoTicketDecisionContext | None = None,
) -> RecordNoTicketRequest:
    current = context or fixture.context
    return RecordNoTicketRequest(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        expected_task_snapshot_hash=current.task_snapshot_hash,
        expected_scope_fingerprint=current.scope_fingerprint,
        reason_code=reason_code,
        reason_basis=reason_basis,
        reason_text="Jun explicitly closes the still-unplaced scope.",
        rule_ids=rule_ids,
        comparison_candidate_revision_id=None,
        actor_id="jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=requested_at,
    )


def _artifact_fixture(tmp_path: Path) -> ArtifactFixture:
    candidate_fixture = _ready_fixture(tmp_path)
    with OntologyUnitOfWork(candidate_fixture.judgment.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
    generation_request = (
        candidate_fixture.judgment.decision_actions.request_candidate_generation(
            _generation_request(candidate_fixture)
        )
    )
    _generate(
        candidate_fixture,
        request_id=generation_request.result_refs[0].object_id,
    )
    with OntologyUnitOfWork(candidate_fixture.judgment.engine) as uow:
        candidate_set = uow.operator_result.current_candidate_set(
            task_family_id=TASK_FAMILY_ID,
            work_item_id=WORK_ITEM_ID,
            set_kind="judgment_bound",
        )
        assert candidate_set is not None
        candidate = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )[0]
    selected = candidate_fixture.judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason="Jun explicitly selects the artifact fixture candidate.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="no-ticket:artifact:selection",
            requested_at=AT + timedelta(seconds=1),
            expected_current_revision_no=0,
        )
    )
    protected = ProtectedTicketActions(
        candidate_fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=candidate_fixture.judgment.decision_actions,
        operator_candidate_auditor=_clean_candidate_audit,
    )
    created = protected.create_operator_ticket_batch(
        CreateOperatorTicketBatchRequest(
            candidate_selection_id=selected.result_refs[0].object_id,
            account_id="acct-jczq",
            run_date="2026-09-04",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="no-ticket:artifact:create",
            requested_at=AT + timedelta(seconds=2),
        )
    )
    batch_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    approved = protected.approve_operator_ticket_batch(
        ApproveOperatorTicketBatchRequest(
            ticket_batch_revision_id=batch_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="no-ticket:artifact:approve",
            requested_at=AT + timedelta(seconds=3),
        )
    )
    artifact_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    with OntologyUnitOfWork(candidate_fixture.judgment.engine) as uow:
        binding = uow.tickets.protected_artifact_binding(artifact_id)
        assert binding is not None
    cutoff = datetime.fromisoformat(binding.frozen_deadline_at)
    context = candidate_fixture.judgment.decision_actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        as_of=AT + timedelta(minutes=1),
    )
    assert context.artifact_ids == (artifact_id,)
    return ArtifactFixture(
        engine=candidate_fixture.judgment.engine,
        actions=candidate_fixture.judgment.decision_actions,
        context=context,
        action_service=candidate_fixture.judgment.action_service,
        artifact_id=artifact_id,
        cutoff=cutoff,
    )


def _issue_challenge(fixture: ArtifactFixture) -> str:
    command = ActionCommand.create(
        action_type="issue_ticket_confirmation",
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="no-ticket:challenge:issue",
        requested_at=AT + timedelta(minutes=2),
        payload={"ticket_artifact_id": fixture.artifact_id},
    )
    challenge_id = "challenge-no-ticket-fixture"

    def handler(uow, action) -> tuple[ObjectRef, ...]:
        binding = uow.tickets.protected_artifact_binding(fixture.artifact_id)
        assert binding is not None
        uow.tickets.insert_confirmation_challenge_revision(
            ConfirmationChallengeRevisionRow(
                challenge_revision_id=challenge_id,
                challenge_family_id="challenge-family-no-ticket-fixture",
                legacy_confirmation_id=None,
                revision_no=1,
                supersedes_revision_id=None,
                ticket_artifact_id=fixture.artifact_id,
                artifact_composition_hash=binding.composition_hash,
                lineage_revision_id=binding.lineage_revision_id,
                nonce_hash="9" * 64,
                issued_at=(AT + timedelta(minutes=2)).isoformat(),
                effective_cutoff_at=fixture.cutoff.isoformat(),
                action_id=action.action_id,
            )
        )
        uow.tickets.insert_confirmation_challenge_head(
            ConfirmationChallengeHeadRow(
                ticket_artifact_id=fixture.artifact_id,
                challenge_revision_id=challenge_id,
                challenge_family_id="challenge-family-no-ticket-fixture",
                revision_no=1,
                updated_at=(AT + timedelta(minutes=2)).isoformat(),
            )
        )
        return (ObjectRef("confirmation_challenge_revision", challenge_id),)

    outcome = fixture.action_service.execute(command, handler)
    assert outcome.status is ActionStatus.COMMITTED
    return challenge_id


def _confirmation_module():
    module_name = "nutmeg.ontology.operator.confirmation"
    assert importlib.util.find_spec(module_name) is not None, (
        "Package 8 must provide the shared artifact terminal state machine"
    )
    return importlib.import_module(module_name)


def test_artifact_terminal_contract_is_closed_and_separates_state_from_reason() -> None:
    confirmation = _confirmation_module()

    assert {item.value for item in confirmation.ArtifactTerminalKind} == {
        "placed",
        "shadow",
    }
    assert {item.value for item in confirmation.ArtifactTerminalReason} == {
        "actual_placement_confirmed",
        "confirmation_not_requested",
        "deadline_unconfirmed",
        "human_no_ticket",
        "official_deadline_shortened",
        "official_offer_cancelled",
    }


def test_effective_artifact_cutoff_uses_the_earliest_bound_deadline() -> None:
    confirmation = _confirmation_module()
    artifact = SimpleNamespace(frozen_deadline_at=(AT + timedelta(hours=3)).isoformat())
    offers = (
        SimpleNamespace(sale_deadline_at=(AT + timedelta(hours=2)).isoformat()),
        SimpleNamespace(sale_deadline_at=(AT + timedelta(hours=4)).isoformat()),
    )

    assert confirmation.effective_artifact_cutoff(artifact, offers) == AT + timedelta(hours=2)


@pytest.mark.parametrize(
    ("terminal_kind", "terminal_reason"),
    [
        ("placed", "deadline_unconfirmed"),
        ("placed", "human_no_ticket"),
        ("shadow", "actual_placement_confirmed"),
    ],
)
def test_terminal_kind_rejects_an_incompatible_reason(
    terminal_kind: str,
    terminal_reason: str,
) -> None:
    confirmation = _confirmation_module()

    with pytest.raises(ValueError, match="terminal reason is incompatible"):
        confirmation.validate_terminal_transition(
            terminal_kind=terminal_kind,
            terminal_reason=terminal_reason,
            ingress_at=AT,
            cutoff=AT + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    ("receipt_delta", "terminal_kind", "terminal_reason", "accepted"),
    [
        (
            timedelta(microseconds=-1),
            "placed",
            "actual_placement_confirmed",
            True,
        ),
        (timedelta(0), "placed", "actual_placement_confirmed", False),
        (
            timedelta(microseconds=-1),
            "shadow",
            "human_no_ticket",
            True,
        ),
        (timedelta(0), "shadow", "human_no_ticket", False),
        (timedelta(microseconds=-1), "shadow", "deadline_unconfirmed", False),
        (timedelta(0), "shadow", "deadline_unconfirmed", True),
        (timedelta(microseconds=1), "shadow", "deadline_unconfirmed", True),
        (timedelta(0), "shadow", "confirmation_not_requested", True),
    ],
)
def test_terminal_transition_obeys_strict_cutoff_precedence(
    receipt_delta: timedelta,
    terminal_kind: str,
    terminal_reason: str,
    accepted: bool,
) -> None:
    confirmation = _confirmation_module()
    def call() -> None:
        confirmation.validate_terminal_transition(
            terminal_kind=terminal_kind,
            terminal_reason=terminal_reason,
            ingress_at=AT + receipt_delta,
            cutoff=AT,
        )

    if accepted:
        call()
    else:
        with pytest.raises(ValueError, match="effective cutoff"):
            call()


def test_terminal_transition_rejects_naive_time() -> None:
    confirmation = _confirmation_module()

    with pytest.raises(ValueError, match="timezone-aware"):
        confirmation.validate_terminal_transition(
            terminal_kind="shadow",
            terminal_reason="deadline_unconfirmed",
            ingress_at=AT.replace(tzinfo=None),
            cutoff=AT,
        )


def test_no_ticket_reason_codes_and_basis_are_closed() -> None:
    confirmation = _confirmation_module()

    assert {item.value for item in confirmation.NoTicketReasonCode} == {
        "human_all_dice",
        "evidence_incomplete",
        "no_compliant_structure_within_cap",
        "discipline_brake",
        "operator_discretion",
    }
    assert {item.value for item in confirmation.NoTicketReasonBasis} == {
        "rule_derived",
        "operator_judgment",
    }
    assert {item.value for item in confirmation.NoTicketCommandResult} == {
        "recorded",
        "task_snapshot_changed",
        "already_current",
    }


@pytest.mark.parametrize("reason_code", ["human_all_dice", "operator_discretion"])
def test_operator_judgment_reason_does_not_require_a_fabricated_rule(
    reason_code: str,
) -> None:
    confirmation = _confirmation_module()

    confirmation.validate_no_ticket_reason(
        reason_code=reason_code,
        reason_basis="operator_judgment",
        reason_text="Jun explicitly closed the remaining sale-wave scope.",
        rule_ids=(),
    )


def test_rule_derived_reason_requires_a_named_rule() -> None:
    confirmation = _confirmation_module()

    with pytest.raises(ValueError, match="named Rule"):
        confirmation.validate_no_ticket_reason(
            reason_code="discipline_brake",
            reason_basis="rule_derived",
            reason_text="The explicit discipline rule was exercised.",
            rule_ids=(),
        )


@pytest.mark.parametrize(
    ("reason_code", "reason_basis", "reason_text"),
    [
        ("automatic_low_confidence", "operator_judgment", "human reason"),
        ("human_all_dice", "software_inferred", "human reason"),
        ("human_all_dice", "operator_judgment", "  "),
    ],
)
def test_no_ticket_reason_rejects_open_or_blank_fields(
    reason_code: str,
    reason_basis: str,
    reason_text: str,
) -> None:
    confirmation = _confirmation_module()

    with pytest.raises(ValueError):
        confirmation.validate_no_ticket_reason(
            reason_code=reason_code,
            reason_basis=reason_basis,
            reason_text=reason_text,
            rule_ids=(),
        )


def test_unit_of_work_can_take_the_sqlite_write_lock_before_state_reads(tmp_path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)

    with OntologyUnitOfWork(engine) as owner:
        owner.acquire_write_lock()
        with engine.connect() as competitor:
            competitor.exec_driver_sql("PRAGMA busy_timeout=1")
            with pytest.raises(OperationalError, match="database is locked"):
                competitor.exec_driver_sql(
                    "UPDATE schema_migrations SET checksum = checksum WHERE version = 1"
                )


@pytest.mark.parametrize(
    "reason_code",
    (
        "human_all_dice",
        "evidence_incomplete",
        "no_compliant_structure_within_cap",
        "discipline_brake",
        "operator_discretion",
    ),
)
def test_record_no_ticket_persists_every_closed_human_reason_and_server_scope(
    tmp_path: Path,
    reason_code: str,
) -> None:
    fixture = _fixture(tmp_path)

    result = fixture.actions.record_no_ticket(
        _request(fixture, reason_code=reason_code)
    )

    assert result.status is ActionStatus.COMMITTED
    receipt = fixture.actions.no_ticket_command_receipt(result.action_id)
    assert receipt is not None
    assert receipt.result == "recorded"
    assert receipt.no_ticket_revision_id is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        revision = uow.operator_result.no_ticket_revision(
            receipt.no_ticket_revision_id
        )
        offer_scopes = uow.operator_result.no_ticket_offer_scopes(
            receipt.no_ticket_revision_id
        )
        artifact_scopes = uow.operator_result.no_ticket_artifact_scopes(
            receipt.no_ticket_revision_id
        )
        eligibility = uow.operator_result.review_eligibility_facts_for_work_item(
            WORK_ITEM_ID
        )
    assert revision is not None
    assert revision.reason_code == reason_code
    assert revision.reason_basis == "operator_judgment"
    assert revision.phase == "envelope"
    assert revision.market_prior_baseline_revision_id is not None
    assert [row.official_offer_revision_id for row in offer_scopes] == [
        "offer-revision-1"
    ]
    assert artifact_scopes == ()
    assert len(eligibility) == 1
    assert eligibility[0].terminal_trigger == "no_ticket"
    assert eligibility[0].review_kind == "forecast_truth"
    assert eligibility[0].readiness_condition == "outcomes_required"


def test_record_no_ticket_captures_pre_evidence_requirement_state_from_server_context(
    tmp_path: Path,
) -> None:
    base = _ready_fixture(tmp_path).judgment

    def context_resolver(_uow, **scope) -> NoTicketDecisionContext:
        current = base.decision_actions.no_ticket_decision_context(
            task_family_id=TASK_FAMILY_ID,
            lane=LANE,
            business_key=BUSINESS_KEY,
            work_item_id=WORK_ITEM_ID,
            as_of=scope["as_of"],
        )
        return replace(
            current,
            phase="evidence",
            requirement_snapshot_hash="a" * 64,
            missing_requirement_ids=("E2",),
            stale_requirement_ids=("E4",),
            conflicting_requirement_ids=("EC",),
            market_prior_baseline_revision_id=None,
            baseline_envelope_revision_id=None,
            candidate_set_revision_id=None,
            comparison_candidate_revision_ids=(),
        )

    actions = type(base.decision_actions)(
        base.action_service,
        no_ticket_context_resolver=context_resolver,
    )
    context = context_resolver(None, as_of=AT + timedelta(minutes=1))
    fixture = NoTicketFixture(base.engine, actions, context)

    result = actions.record_no_ticket(
        _request(
            fixture,
            reason_code="evidence_incomplete",
            reason_basis="rule_derived",
            rule_ids=("EVIDENCE-GATE",),
        )
    )

    receipt = actions.no_ticket_command_receipt(result.action_id)
    assert receipt is not None and receipt.no_ticket_revision_id is not None
    with OntologyUnitOfWork(base.engine) as uow:
        revision = uow.operator_result.no_ticket_revision(
            receipt.no_ticket_revision_id
        )
        eligibility = uow.operator_result.review_eligibility_facts_for_work_item(
            WORK_ITEM_ID
        )
    assert revision is not None
    assert revision.requirement_snapshot_hash == "a" * 64
    assert revision.missing_requirement_ids == ("E2",)
    assert revision.stale_requirement_ids == ("E4",)
    assert revision.conflicting_requirement_ids == ("EC",)
    assert revision.market_prior_baseline_revision_id is None
    assert eligibility[0].review_kind == "operational_data_availability"
    assert eligibility[0].readiness_condition == "immediate"


def test_record_no_ticket_is_judge_only_idempotent_and_reports_already_current(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    denied = fixture.actions.record_no_ticket(
        _request(
            fixture,
            role=ActorRole.AI_ANALYST,
            key="no-ticket:record:ai-denied",
        )
    )
    request = _request(fixture)

    first = fixture.actions.record_no_ticket(request)
    replay = fixture.actions.record_no_ticket(request)
    refreshed = fixture.actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        as_of=AT + timedelta(minutes=2),
    )
    already_current = fixture.actions.record_no_ticket(
        _request(
            fixture,
            key="no-ticket:record:already-current",
            requested_at=AT + timedelta(minutes=2),
            context=refreshed,
        )
    )

    assert denied.status is ActionStatus.REJECTED
    assert first == replay
    assert first.status is ActionStatus.COMMITTED
    duplicate_receipt = fixture.actions.no_ticket_command_receipt(
        already_current.action_id
    )
    assert duplicate_receipt is not None
    assert duplicate_receipt.result == "already_current"
    assert duplicate_receipt.no_ticket_revision_id is not None
    assert any(
        ref.object_type == "no_ticket_revision"
        for ref in already_current.result_refs
    )
    with fixture.engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM operator_no_ticket_revisions), "
                "(SELECT COUNT(*) FROM operator_no_ticket_command_receipts), "
                "(SELECT COUNT(*) FROM operator_review_eligibility_facts)"
            )
        ).one()
    assert counts == (1, 2, 1)


def test_record_no_ticket_returns_snapshot_changed_when_server_scope_gains_offer(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with fixture.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO matches (match_id) VALUES ('match-2'); "
            )
        )
        connection.execute(
            text(
                "INSERT INTO official_offer_families "
                "(official_offer_family_id, lane, business_key, official_match_no, "
                "match_id, created_at) VALUES "
                "('offer-family-2', 'jczq', '2026-09-04', '002', 'match-2', :at)"
            ),
            {"at": AT.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO official_offer_revisions "
                "(official_offer_revision_id, official_offer_family_id, slate_revision_id, "
                "match_id, official_match_no, market_definition_ids_json, sale_opens_at, "
                "sale_deadline_at, status) VALUES "
                "('offer-revision-2', 'offer-family-2', 'slate-1', 'match-2', '002', "
                "'[]', :opens, :deadline, 'on_sale')"
            ),
            {
                "opens": AT.isoformat(),
                "deadline": (AT + timedelta(hours=4)).isoformat(),
            },
        )

    result = fixture.actions.record_no_ticket(_request(fixture))

    receipt = fixture.actions.no_ticket_command_receipt(result.action_id)
    assert receipt is not None
    assert receipt.result == "task_snapshot_changed"
    assert receipt.no_ticket_revision_id is None
    with fixture.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_no_ticket_revisions")
        ) == 0


@pytest.mark.parametrize(
    ("receipt_delta", "expected_result", "expected_reason"),
    (
        (
            timedelta(microseconds=-1),
            "recorded",
            "human_no_ticket",
        ),
        (
            timedelta(0),
            "task_snapshot_changed",
            "confirmation_not_requested",
        ),
        (
            timedelta(microseconds=1),
            "task_snapshot_changed",
            "confirmation_not_requested",
        ),
    ),
)
def test_record_no_ticket_uses_cutoff_first_artifact_cas_without_scanner(
    tmp_path: Path,
    receipt_delta: timedelta,
    expected_result: str,
    expected_reason: str,
) -> None:
    fixture = _artifact_fixture(tmp_path)

    result = fixture.actions.record_no_ticket(
        _request(
            fixture,
            key=f"no-ticket:artifact:boundary:{receipt_delta.total_seconds()}",
            requested_at=fixture.cutoff + receipt_delta,
        )
    )

    receipt = fixture.actions.no_ticket_command_receipt(result.action_id)
    assert receipt is not None
    assert receipt.result == expected_result
    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
        placement = uow.tickets.placement_for_artifact(fixture.artifact_id)
        eligibility = uow.operator_result.review_eligibility_facts_for_work_item(
            WORK_ITEM_ID
        )
    assert terminal is not None
    assert terminal.terminal_kind == "shadow"
    assert terminal.terminal_reason == expected_reason
    assert placement is None
    if expected_result == "recorded":
        assert receipt.no_ticket_revision_id is not None
        assert [fact.terminal_trigger for fact in eligibility] == ["no_ticket"]
    else:
        assert receipt.no_ticket_revision_id is None
        assert [fact.terminal_trigger for fact in eligibility] == [
            "artifact_terminal"
        ]


def test_human_no_ticket_invalidates_open_challenge_and_binds_terminal_receipt(
    tmp_path: Path,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    challenge_id = _issue_challenge(fixture)
    context = fixture.actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        as_of=AT + timedelta(minutes=3),
    )

    result = fixture.actions.record_no_ticket(
        _request(
            fixture,
            context=context,
            key="no-ticket:challenge:human-close",
            requested_at=AT + timedelta(minutes=3),
        )
    )

    command_receipt = fixture.actions.no_ticket_command_receipt(result.action_id)
    assert command_receipt is not None
    assert command_receipt.result == "recorded"
    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
    assert terminal is not None
    assert terminal.challenge_revision_id == challenge_id
    assert terminal.terminal_reason == "human_no_ticket"
    assert head is None


def test_consumed_challenge_wins_no_ticket_competition_exactly_once(
    tmp_path: Path,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    challenge_id = _issue_challenge(fixture)
    stale_context = fixture.actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        as_of=AT + timedelta(minutes=3),
    )
    placement = ActionCommand.create(
        action_type="confirm_ticket_placement",
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="no-ticket:challenge:placement-wins",
        requested_at=AT + timedelta(minutes=4),
        payload={"ticket_artifact_id": fixture.artifact_id},
    )

    def place(uow, action) -> tuple[ObjectRef, ...]:
        transition = consume_artifact_terminal(
            uow,
            ticket_artifact_id=fixture.artifact_id,
            challenge_revision_id=challenge_id,
            terminal_kind=ArtifactTerminalKind.PLACED,
            terminal_reason=ArtifactTerminalReason.ACTUAL_PLACEMENT_CONFIRMED,
            action_id=action.action_id,
            ingress_at=AT + timedelta(minutes=4),
        )
        return (
            ObjectRef(
                "artifact_terminal_receipt",
                transition.receipt.artifact_terminal_receipt_id,
            ),
        )

    placed = fixture.action_service.execute(
        placement,
        place,
        acquire_write_lock=True,
    )
    no_ticket = fixture.actions.record_no_ticket(
        _request(
            fixture,
            context=stale_context,
            key="no-ticket:challenge:loses",
            requested_at=AT + timedelta(minutes=5),
        )
    )

    assert placed.status is ActionStatus.COMMITTED
    command_receipt = fixture.actions.no_ticket_command_receipt(no_ticket.action_id)
    assert command_receipt is not None
    assert command_receipt.result == "task_snapshot_changed"
    with fixture.engine.connect() as connection:
        terminals = connection.execute(
            text(
                "SELECT terminal_kind, terminal_reason, challenge_revision_id "
                "FROM operator_artifact_terminal_receipts"
            )
        ).all()
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_no_ticket_revisions")
        ) == 0
    assert terminals == [
        ("placed", "actual_placement_confirmed", challenge_id)
    ]


def _supersede_request(
    *,
    no_ticket_revision_id: str,
    context: NoTicketDecisionContext,
    requested_at: datetime,
    key: str,
    role: ActorRole = ActorRole.JUDGE_OPERATOR,
) -> SupersedeNoTicketRequest:
    return SupersedeNoTicketRequest(
        no_ticket_revision_id=no_ticket_revision_id,
        expected_task_snapshot_hash=context.task_snapshot_hash,
        expected_scope_fingerprint=context.scope_fingerprint,
        reason_text="Jun explicitly reopens only the still-on-sale family scope.",
        actor_id="jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=requested_at,
    )


@pytest.mark.parametrize(
    ("receipt_delta", "expected_result", "expected_revision_count"),
    (
        (timedelta(microseconds=-1), "recorded", 2),
        (timedelta(0), "task_snapshot_changed", 1),
        (timedelta(microseconds=1), "task_snapshot_changed", 1),
    ),
)
def test_supersede_no_ticket_reopens_only_strictly_before_cutoff(
    tmp_path: Path,
    receipt_delta: timedelta,
    expected_result: str,
    expected_revision_count: int,
) -> None:
    fixture = _fixture(tmp_path)
    recorded = fixture.actions.record_no_ticket(_request(fixture))
    recorded_receipt = fixture.actions.no_ticket_command_receipt(recorded.action_id)
    assert recorded_receipt is not None
    assert recorded_receipt.no_ticket_revision_id is not None
    requested_at = AT + timedelta(hours=3) + receipt_delta
    context = fixture.actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        as_of=requested_at,
    )

    result = fixture.actions.supersede_no_ticket(
        _supersede_request(
            no_ticket_revision_id=recorded_receipt.no_ticket_revision_id,
            context=context,
            requested_at=requested_at,
            key=f"no-ticket:supersede:{receipt_delta.total_seconds()}",
        )
    )

    command_receipt = fixture.actions.no_ticket_command_receipt(result.action_id)
    assert command_receipt is not None
    assert command_receipt.result == expected_result
    with fixture.engine.connect() as connection:
        revisions = connection.execute(
            text(
                "SELECT revision_no, supersedes_revision_id, deployment_outcome "
                "FROM operator_no_ticket_revisions ORDER BY revision_no"
            )
        ).all()
    assert len(revisions) == expected_revision_count
    if expected_result == "recorded":
        assert revisions[1] == (
            2,
            recorded_receipt.no_ticket_revision_id,
            "reopened",
        )


def test_supersede_no_ticket_is_judge_only_and_does_not_reopen_new_offer_family(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    recorded = fixture.actions.record_no_ticket(_request(fixture))
    recorded_receipt = fixture.actions.no_ticket_command_receipt(recorded.action_id)
    assert recorded_receipt is not None
    assert recorded_receipt.no_ticket_revision_id is not None
    with fixture.engine.begin() as connection:
        connection.execute(text("INSERT INTO matches (match_id) VALUES ('match-new')"))
        connection.execute(
            text(
                "INSERT INTO official_offer_families "
                "(official_offer_family_id, lane, business_key, official_match_no, "
                "match_id, created_at) VALUES "
                "('offer-family-new', 'jczq', '2026-09-04', '099', "
                "'match-new', :at)"
            ),
            {"at": AT.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO official_offer_revisions "
                "(official_offer_revision_id, official_offer_family_id, slate_revision_id, "
                "match_id, official_match_no, market_definition_ids_json, sale_opens_at, "
                "sale_deadline_at, status) VALUES "
                "('offer-revision-new', 'offer-family-new', 'slate-1', 'match-new', "
                "'099', '[]', :at, :deadline, 'on_sale')"
            ),
            {
                "at": AT.isoformat(),
                "deadline": (AT + timedelta(hours=4)).isoformat(),
            },
        )
    context = fixture.actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=WORK_ITEM_ID,
        as_of=AT + timedelta(minutes=2),
    )
    denied = fixture.actions.supersede_no_ticket(
        _supersede_request(
            no_ticket_revision_id=recorded_receipt.no_ticket_revision_id,
            context=context,
            requested_at=AT + timedelta(minutes=2),
            key="no-ticket:supersede:ai-denied",
            role=ActorRole.AI_ANALYST,
        )
    )
    result = fixture.actions.supersede_no_ticket(
        _supersede_request(
            no_ticket_revision_id=recorded_receipt.no_ticket_revision_id,
            context=context,
            requested_at=AT + timedelta(minutes=2),
            key="no-ticket:supersede:human",
        )
    )

    assert denied.status is ActionStatus.REJECTED
    command_receipt = fixture.actions.no_ticket_command_receipt(result.action_id)
    assert command_receipt is not None
    assert command_receipt.result == "recorded"
    assert command_receipt.no_ticket_revision_id is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        scopes = uow.operator_result.no_ticket_offer_scopes(
            command_receipt.no_ticket_revision_id
        )
    assert [scope.official_offer_revision_id for scope in scopes] == [
        "offer-revision-1"
    ]


def test_no_ticket_closed_family_survives_a_new_slate_revision(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    recorded = fixture.actions.record_no_ticket(_request(fixture))
    assert recorded.status is ActionStatus.COMMITTED
    changed_at = AT + timedelta(minutes=2)
    with fixture.engine.begin() as connection:
        connection.execute(text("INSERT INTO matches (match_id) VALUES ('match-new')"))
        connection.execute(
            text(
                "INSERT INTO official_offer_families "
                "(official_offer_family_id, lane, business_key, official_match_no, "
                "match_id, created_at) VALUES "
                "('offer-family-new', 'jczq', '2026-09-04', '099', "
                "'match-new', :at)"
            ),
            {"at": changed_at.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO official_sale_slate_revisions "
                "(slate_revision_id, slate_family_id, lane, business_key, revision_no, "
                "source_artifact_retrieval_id, published_at, retrieved_at, valid_from, "
                "supersedes_slate_revision_id, content_hash) VALUES "
                "('slate-2', 'jczq:2026-09-04', 'jczq', '2026-09-04', 2, "
                "'retrieval-1', :at, :at, :at, 'slate-1', :content_hash)"
            ),
            {"at": changed_at.isoformat(), "content_hash": "f" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO official_offer_revisions "
                "(official_offer_revision_id, official_offer_family_id, slate_revision_id, "
                "match_id, official_match_no, market_definition_ids_json, sale_opens_at, "
                "sale_deadline_at, status) VALUES "
                "('offer-revision-1-v2', 'offer-family-1', 'slate-2', 'match-1', "
                "'001', '[]', :opens, :deadline, 'on_sale'), "
                "('offer-revision-new-v2', 'offer-family-new', 'slate-2', 'match-new', "
                "'099', '[]', :opens, :deadline, 'on_sale')"
            ),
            {
                "opens": AT.isoformat(),
                "deadline": (AT + timedelta(hours=4)).isoformat(),
            },
        )

    corrected = fixture.actions.no_ticket_decision_context(
        task_family_id=TASK_FAMILY_ID,
        lane=LANE,
        business_key=BUSINESS_KEY,
        work_item_id=f"{TASK_FAMILY_ID}:corrected-wave",
        as_of=changed_at + timedelta(seconds=1),
    )

    assert corrected.offer_revision_ids == ("offer-revision-new-v2",)
    assert corrected.current_no_ticket_revision_id is None
