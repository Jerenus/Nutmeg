from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.actions.models import ActionCommand, ActionStatus, ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import (
    ApproveOperatorTicketBatchRequest,
    CreateOperatorTicketBatchRequest,
    CurrentOperatorCandidateAudit,
    CurrentOperatorCandidateAuditFinding,
    ProtectedTicketActions,
    RemoveTicketLegRequest,
)
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.operator.decision_actions import (
    RecordTicketAuditOverrideRequest,
    SelectTicketCandidateRequest,
    TicketAuditOverrideInput,
)
from nutmeg.ontology.operator.result_actions import CandidateAuditFindingInput
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.tickets.models import TicketLegDraft
from nutmeg.product.operator_workers import audit_current_candidate
from tests.ontology.operator.test_candidate_actions import (
    _candidate,
    _generate,
    _generation_request,
    _ready_fixture,
)
from tests.ontology.operator.test_judgment_actions import AT

TOKEN_KEY = "operator-audit-token-key-with-at-least-32-bytes"


@dataclass(frozen=True, slots=True)
class OverrideFixture:
    candidate_fixture: object
    engine: object
    action_service: object
    actions: object
    batch_revision_id: str
    batch_id: str
    candidate_set_revision_id: str
    candidate_revision_id: str
    candidate_selection_id: str
    candidate_ticket_id: str
    candidate_ticket_leg_id: str
    baseline_probability_id: str
    judgment_revision_id: str
    forecast_revision_id: str
    batch_token: str


def _audit_blocked_candidate(content_hash: str = "d" * 64):
    return replace(
        _candidate(set_kind="judgment_bound", content_hash=content_hash),
        partition="audit_blocked",
        rank=None,
        deployable=False,
        audit_findings=(
            CandidateAuditFindingInput(
                finding_id="legs:001:low-confidence",
                audit_kind="legs",
                code="low_conf_single",
                severity="ERROR",
                message="single has insufficient confidence",
                official_match_no="001",
                rule_id="conf",
            ),
            CandidateAuditFindingInput(
                finding_id="prescription:001:single",
                audit_kind="prescription_difference",
                code="prescription_deviation",
                severity="ERROR",
                message="candidate removes a prescribed face",
                official_match_no="001",
                rule_id="m-单选",
            ),
        ),
    )


def _setup_override_fixture(
    tmp_path: Path,
    *,
    attach_lineage: bool = True,
    judgment_candidate=None,
) -> OverrideFixture:
    candidate_fixture = _ready_fixture(tmp_path)
    candidate_fixture.judgment.decision_actions.configure_audit_override_tokens(TOKEN_KEY)
    requested = candidate_fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(candidate_fixture)
    )
    generated = _generate(
        candidate_fixture,
        request_id=requested.result_refs[0].object_id,
        judgment_candidate=judgment_candidate or _audit_blocked_candidate(),
    )
    assert generated.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(candidate_fixture.judgment.engine) as uow:
        candidate_set = next(
            row
            for row in uow.operator_result.candidate_sets_for_request(
                requested.result_refs[0].object_id
            )
            if row.set_kind == "judgment_bound"
        )
        candidate = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )[0]
        candidate_ticket = uow.operator_result.candidate_tickets(
            candidate.candidate_revision_id
        )[0]
        candidate_leg = uow.operator_result.candidate_ticket_legs(
            candidate_ticket.candidate_ticket_id
        )[0]
        prescription_item = uow.operator_decision.judgment_prescription_items(
            candidate_fixture.prescription_id
        )[0]
        judgment = uow.operator_decision.operator_match_judgment_revision(
            prescription_item.operator_match_judgment_revision_id
        )
        assert judgment is not None
        baseline_probability = next(
            row
            for row in uow.operator_decision.market_prior_baseline_probabilities(
                candidate_fixture.baseline_id
            )
            if row["face_code"] == "3"
        )
        forecast = uow.decision.current_committed_revision(
            uow.decision.ensure_series("match-1", "md-had")
        )
        assert forecast is not None
        assert forecast.forecast_revision_id == judgment.forecast_revision_id
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )

    selected = candidate_fixture.judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason="Jun explicitly selects this audit-blocked draft for adjudication.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="lineage:selection:1",
            requested_at=AT + timedelta(seconds=9),
            expected_current_revision_no=0,
        )
    )
    selection_id = selected.result_refs[0].object_id
    protected = ProtectedTicketActions(
        candidate_fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
    )
    leg = TicketLegDraft(
        leg_key="match-1:md-had:home",
        match_id="match-1",
        match_no=1,
        name="Home FC - Away FC",
        market_definition_id="md-had",
        selection_id="sel-had-home",
        outcome_key="home",
        faces="3",
        forecast_revision_id=judgment.forecast_revision_id,
        entry_quote_id="quote-3",
        odds=2.5,
        line=None,
        bucket="main",
        fair={
            "home": forecast.belief_distribution["3"],
            "draw": forecast.belief_distribution["1"],
            "away": forecast.belief_distribution["0"],
        },
        confidence=4,
        directional_flags=(),
        nondirectional_flags=(),
        anchor_integrity="pass",
        precedents=(),
    )
    command = ActionCommand.create(
        action_type="create_ticket_batch",
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="lineage:batch:1",
        requested_at=AT + timedelta(seconds=10),
        payload={"candidate_selection_id": selection_id},
    )

    def create_batch_with_lineage(uow, action_command):
        refs = protected._insert_revision(
            uow,
            command=action_command,
            batch_id="ticket-batch-lineage-fixture",
            revision_no=1,
            supersedes_revision_id=None,
            run_date="2026-09-04",
            channel="jczq",
            account_id="acct-jczq",
            currency="CNY",
            deadline_at=AT + timedelta(hours=3),
            legs=[leg],
            requested_at=AT + timedelta(seconds=10),
        )
        if not attach_lineage:
            return refs
        batch_revision_ref = next(
            ref for ref in refs if ref.object_type == "ticket_batch_revision"
        )
        lineage_ref = (
            candidate_fixture.judgment.decision_actions.insert_ticket_decision_lineage(
                uow,
                ticket_batch_revision_id=batch_revision_ref.object_id,
                candidate_selection_id=selection_id,
                action_id=action_command.action_id,
                created_at=AT + timedelta(seconds=10),
            )
        )
        return (*refs, lineage_ref)

    batch = candidate_fixture.judgment.action_service.execute(
        command,
        create_batch_with_lineage,
    )
    batch_revision_id = next(
        ref.object_id
        for ref in batch.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    with OntologyUnitOfWork(candidate_fixture.judgment.engine) as uow:
        batch_row = uow.tickets.batch_revision(batch_revision_id)
        assert batch_row is not None
    batch_token = (
        candidate_fixture.judgment.decision_actions.issue_ticket_batch_audit_token(
            batch_revision_id
        )
    )
    return OverrideFixture(
        candidate_fixture=candidate_fixture,
        engine=candidate_fixture.judgment.engine,
        action_service=candidate_fixture.judgment.action_service,
        actions=candidate_fixture.judgment.decision_actions,
        batch_revision_id=batch_revision_id,
        batch_id=batch_row.ticket_batch_id,
        candidate_set_revision_id=candidate_set.candidate_set_revision_id,
        candidate_revision_id=candidate.candidate_revision_id,
        candidate_selection_id=selection_id,
        candidate_ticket_id=candidate_ticket.candidate_ticket_id,
        candidate_ticket_leg_id=candidate_leg.candidate_ticket_leg_id,
        baseline_probability_id=str(
            baseline_probability["market_prior_baseline_probability_id"]
        ),
        judgment_revision_id=judgment.operator_match_judgment_revision_id,
        forecast_revision_id=judgment.forecast_revision_id,
        batch_token=batch_token,
    )


def _override_request(
    fixture: OverrideFixture,
    *,
    key: str = "audit-override:1",
    role: ActorRole = ActorRole.JUDGE_OPERATOR,
) -> RecordTicketAuditOverrideRequest:
    context = fixture.actions.ticket_audit_override_context(fixture.batch_token)
    rules = {
        "low_conf_single": ("conf",),
        "prescription_deviation": ("m-单选",),
    }
    return RecordTicketAuditOverrideRequest(
        ticket_batch_token=fixture.batch_token,
        expected_snapshot_token=context.expected_snapshot_token,
        overrides=tuple(
            TicketAuditOverrideInput(
                finding_token=finding.finding_token,
                reason=f"Jun rejects {finding.finding_code} after reviewing the evidence.",
                rule_ids=rules[finding.finding_code],
            )
            for finding in context.findings
        ),
        actor_id="jun" if role is ActorRole.JUDGE_OPERATOR else "model:test",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT + timedelta(seconds=11),
    )


def test_lineage_normalizes_every_selected_candidate_dependency(tmp_path: Path) -> None:
    fixture = _setup_override_fixture(tmp_path)

    with OntologyUnitOfWork(fixture.engine) as uow:
        lineage = uow.operator_result.ticket_decision_lineage_for_batch(
            fixture.batch_revision_id
        )
        assert lineage is not None
        items = uow.operator_result.ticket_decision_lineage_items(
            lineage.lineage_revision_id
        )

    assert lineage.candidate_set_revision_id == fixture.candidate_set_revision_id
    assert lineage.candidate_selection_id == fixture.candidate_selection_id
    assert lineage.candidate_revision_id == fixture.candidate_revision_id
    assert lineage.audit_policy_version == "operator-candidate-audit-v1"
    assert len(items) == 1
    assert items[0].candidate_ticket_id == fixture.candidate_ticket_id
    assert items[0].candidate_ticket_leg_id == fixture.candidate_ticket_leg_id
    assert items[0].market_prior_baseline_probability_id == fixture.baseline_probability_id
    assert items[0].operator_match_judgment_revision_id == fixture.judgment_revision_id
    assert items[0].forecast_revision_id == fixture.forecast_revision_id


def test_override_commits_exact_errors_receipts_and_one_regeneration_request(
    tmp_path: Path,
) -> None:
    fixture = _setup_override_fixture(tmp_path)
    request = _override_request(fixture)

    first = fixture.actions.record_ticket_audit_override(request)
    replay = fixture.actions.record_ticket_audit_override(request)

    assert first == replay
    assert first.status is ActionStatus.COMMITTED
    assert {ref.object_type for ref in first.result_refs} == {
        "adjudication",
        "ticket_audit_override_receipt",
        "operator_candidate_generation_request",
    }
    with OntologyUnitOfWork(fixture.engine) as uow:
        receipts = uow.operator_result.ticket_audit_override_receipts_for_batch(
            fixture.batch_revision_id
        )
        links = uow.operator_result.candidate_generation_override_links(
            next(
                ref.object_id
                for ref in first.result_refs
                if ref.object_type == "operator_candidate_generation_request"
            )
        )
        adjudications = uow.workflow.iter_adjudications()
        candidate_count = len(
            uow.operator_result.candidates_for_set(fixture.candidate_set_revision_id)
        )
        candidate_sets = uow.operator_result.current_candidate_set(
            task_family_id="jczq:2026-09-04",
            work_item_id="jczq:2026-09-04:wave:current",
            set_kind="judgment_bound",
        )

    assert len(receipts) == len(adjudications) == len(links) == 2
    assert {row.finding_code for row in receipts} == {
        "low_conf_single",
        "prescription_deviation",
    }
    assert all(row.candidate_content_hash == "d" * 64 for row in receipts)
    assert all(row.audit_policy_version == "operator-candidate-audit-v1" for row in receipts)
    assert all(row.decision == "override" for row in adjudications)
    assert {
        tuple(
            (item["object_type"], item["object_id"])
            for item in row.evidence_rejected
        )
        for row in adjudications
    } == {
        (("ticket_audit_finding", receipt.candidate_audit_finding_id),)
        for receipt in receipts
    }
    assert candidate_count == 1
    assert candidate_sets is not None
    assert candidate_sets.candidate_set_revision_id == fixture.candidate_set_revision_id


def test_override_requires_the_exact_nonempty_current_error_set(tmp_path: Path) -> None:
    fixture = _setup_override_fixture(tmp_path)
    request = _override_request(fixture)

    with pytest.raises(ValueError, match="exact.*ERROR|ERROR.*exact"):
        fixture.actions.record_ticket_audit_override(
            replace(
                request,
                overrides=request.overrides[:-1],
                idempotency_key="audit-override:incomplete",
            )
        )
    with pytest.raises(ValueError, match="Rule|deviation"):
        fixture.actions.record_ticket_audit_override(
            replace(
                request,
                overrides=(
                    request.overrides[0],
                    replace(request.overrides[1], rule_ids=("conf",)),
                ),
                idempotency_key="audit-override:wrong-rules",
            )
        )

    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.workflow.count_adjudications() == 0
        assert not uow.operator_result.ticket_audit_override_receipts_for_batch(
            fixture.batch_revision_id
        )


def test_override_prevalidates_all_signed_findings_before_the_first_write(
    tmp_path: Path,
) -> None:
    fixture = _setup_override_fixture(tmp_path)
    request = _override_request(fixture)
    payload_frame, signature_frame = request.overrides[1].finding_token.split(".")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(signature_frame[-1])
    assert final_index % 4 == 0
    tampered = (
        payload_frame
        + "."
        + signature_frame[:-1]
        + alphabet[final_index + 1]
    )

    with pytest.raises(ValueError, match="invalid|signed|token"):
        fixture.actions.record_ticket_audit_override(
            replace(
                request,
                overrides=(
                    request.overrides[0],
                    replace(request.overrides[1], finding_token=tampered),
                ),
                idempotency_key="audit-override:tampered",
            )
        )

    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.workflow.count_adjudications() == 0
        assert not uow.operator_result.ticket_audit_override_receipts_for_batch(
            fixture.batch_revision_id
        )


def test_override_rejects_missing_or_superseded_batch_lineage(tmp_path: Path) -> None:
    missing = _setup_override_fixture(tmp_path / "missing", attach_lineage=False)
    with pytest.raises(ValueError, match="lineage"):
        missing.actions.ticket_audit_override_context(missing.batch_token)

    stale = _setup_override_fixture(tmp_path / "stale")
    with OntologyUnitOfWork(stale.engine) as uow:
        batch = uow.tickets.batch_revision(stale.batch_revision_id)
        assert batch is not None
    protected = ProtectedTicketActions(
        stale.action_service,
        ContentAddressedArtifactStore(tmp_path / "stale" / "ticket-artifacts"),
    )
    removed = protected.remove_ticket_leg(
        RemoveTicketLegRequest(
            ticket_batch_id=stale.batch_id,
            leg_key="match-1:md-had:home",
            expected_revision_no=1,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="lineage:batch:supersede",
            requested_at=AT + timedelta(seconds=12),
        )
    )
    assert removed.status is ActionStatus.COMMITTED

    with pytest.raises(ValueError, match="current|superseded|stale"):
        stale.actions.record_ticket_audit_override(_override_request(stale))


def test_ai_cannot_record_an_audit_error_override(tmp_path: Path) -> None:
    fixture = _setup_override_fixture(tmp_path)

    outcome = fixture.actions.record_ticket_audit_override(
        _override_request(
            fixture,
            key="audit-override:ai-denied",
            role=ActorRole.AI_ANALYST,
        )
    )

    assert outcome.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.workflow.count_adjudications() == 0
        assert not uow.operator_result.ticket_audit_override_receipts_for_batch(
            fixture.batch_revision_id
        )


@pytest.mark.parametrize(
    "failure_sql",
    (
        "CREATE TRIGGER fail_override_adjudication BEFORE INSERT ON adjudications "
        "BEGIN SELECT RAISE(ABORT, 'forced adjudication failure'); END",
        "CREATE TRIGGER fail_override_receipt BEFORE INSERT ON "
        "operator_ticket_audit_override_receipts "
        "BEGIN SELECT RAISE(ABORT, 'forced receipt failure'); END",
        "CREATE TRIGGER fail_override_second_receipt BEFORE INSERT ON "
        "operator_ticket_audit_override_receipts "
        "WHEN (SELECT COUNT(*) FROM operator_ticket_audit_override_receipts) = 1 "
        "BEGIN SELECT RAISE(ABORT, 'forced second receipt failure'); END",
        "CREATE TRIGGER fail_override_regeneration BEFORE INSERT ON "
        "operator_candidate_generation_requests WHEN "
        "(SELECT action_type FROM actions WHERE action_id = NEW.action_id) = "
        "'record_ticket_audit_override' "
        "BEGIN SELECT RAISE(ABORT, 'forced regeneration failure'); END",
    ),
)
def test_override_failure_rolls_back_every_business_row(
    tmp_path: Path,
    failure_sql: str,
) -> None:
    fixture = _setup_override_fixture(tmp_path)
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql(failure_sql)

    with pytest.raises(IntegrityError, match="forced"):
        fixture.actions.record_ticket_audit_override(_override_request(fixture))

    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.workflow.count_adjudications() == 0
        assert not uow.operator_result.ticket_audit_override_receipts_for_batch(
            fixture.batch_revision_id
        )
        assert not uow.operator_result.candidate_generation_override_links_for_batch(
            fixture.batch_revision_id
        )
    with fixture.engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM operator_candidate_generation_requests "
                "WHERE action_id IN (SELECT action_id FROM actions WHERE "
                "action_type = 'record_ticket_audit_override')"
            )
        ) == 0


def test_web_contract_exposes_no_error_override_command() -> None:
    from nutmeg.interfaces import operator_api

    assert not hasattr(operator_api, "RecordTicketAuditOverrideCommandV2")


def _selected_candidate_fixture(tmp_path: Path):
    fixture = _ready_fixture(tmp_path)
    requested = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    generated = _generate(fixture, request_id=requested.result_refs[0].object_id)
    assert generated.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        candidate_set = next(
            row
            for row in uow.operator_result.candidate_sets_for_request(
                requested.result_refs[0].object_id
            )
            if row.set_kind == "judgment_bound"
        )
        candidate = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )[0]
        candidate_ticket = uow.operator_result.candidate_tickets(
            candidate.candidate_revision_id
        )[0]
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
    selected = fixture.judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason="Jun explicitly selects this candidate for materialization.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="operator-batch:selection:1",
            requested_at=AT + timedelta(seconds=9),
            expected_current_revision_no=0,
        )
    )
    return fixture, selected.result_refs[0].object_id, candidate, candidate_ticket


def _create_operator_batch(protected, selection_id: str, *, key: str):
    return protected.create_operator_ticket_batch(
        CreateOperatorTicketBatchRequest(
            candidate_selection_id=selection_id,
            account_id="acct-jczq",
            run_date="2026-09-04",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=key,
            requested_at=AT + timedelta(seconds=10),
        )
    )


def _persisted_current_audit(uow, selected) -> CurrentOperatorCandidateAudit:
    return CurrentOperatorCandidateAudit(
        policy_version=selected.candidate_set.audit_policy_version,
        completed_audit_kinds=(
            "legs",
            "prescription_difference",
            "budget",
            "deployment",
        ),
        findings=tuple(
            CurrentOperatorCandidateAuditFinding(
                candidate_audit_finding_id=row.candidate_audit_finding_id,
                audit_kind=row.audit_kind,
                finding_code=row.finding_code,
                severity=row.severity,
                message=row.message,
                official_match_no=row.official_match_no,
                rule_id=row.rule_id,
            )
            for row in uow.operator_result.candidate_audit_findings(
                selected.candidate.candidate_revision_id
            )
        ),
    )


def test_operator_materialization_reruns_all_current_authoritative_audits(
    tmp_path: Path,
) -> None:
    fixture, selection_id, _candidate, _candidate_ticket = _selected_candidate_fixture(
        tmp_path
    )
    observed: list[CurrentOperatorCandidateAudit] = []

    def current_auditor(uow, selected):
        audit = audit_current_candidate(uow, selected)
        observed.append(audit)
        return audit

    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=current_auditor,
    )

    result = _create_operator_batch(
        protected,
        selection_id,
        key="operator-batch:create:current-audit",
    )

    assert result.status is ActionStatus.COMMITTED
    assert len(observed) == 1
    assert observed[0].policy_version == "operator-candidate-audit-v1"
    assert observed[0].completed_audit_kinds == (
        "legs",
        "prescription_difference",
        "budget",
        "deployment",
    )


def test_operator_approval_rejects_a_fresh_error_absent_from_persisted_findings(
    tmp_path: Path,
) -> None:
    fixture, selection_id, candidate, _candidate_ticket = _selected_candidate_fixture(
        tmp_path
    )
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        assert not uow.operator_result.candidate_audit_findings(
            candidate.candidate_revision_id
        )
    calls = 0

    def current_auditor(_uow, _selected):
        nonlocal calls
        calls += 1
        return CurrentOperatorCandidateAudit(
            policy_version="operator-candidate-audit-v1",
            completed_audit_kinds=(
                "legs",
                "prescription_difference",
                "budget",
                "deployment",
            ),
            findings=(
                CurrentOperatorCandidateAuditFinding(
                    candidate_audit_finding_id="fresh-current-error",
                    audit_kind="legs",
                    finding_code="fresh_leg_error",
                    severity="ERROR",
                    message="the current authoritative leg audit now blocks approval",
                    official_match_no="001",
                    rule_id=None,
                ),
            ),
        )

    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=current_auditor,
    )
    created = _create_operator_batch(
        protected,
        selection_id,
        key="operator-batch:create:fresh-error",
    )
    draft_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )

    with pytest.raises(ValueError, match="ERROR.*exact current override"):
        protected.approve_operator_ticket_batch(
            ApproveOperatorTicketBatchRequest(
                ticket_batch_revision_id=draft_revision_id,
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="operator-batch:approve:fresh-error",
                requested_at=AT + timedelta(seconds=11),
            )
        )

    assert calls == 2
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        draft = uow.tickets.batch_revision(draft_revision_id)
        assert draft is not None
        assert [finding["code"] for finding in draft.audit_findings] == [
            "fresh_leg_error"
        ]


def test_operator_candidate_materialization_atomically_writes_complete_lineage(
    tmp_path: Path,
) -> None:
    fixture, selection_id, candidate, candidate_ticket = _selected_candidate_fixture(
        tmp_path
    )
    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=_persisted_current_audit,
    )

    result = _create_operator_batch(
        protected,
        selection_id,
        key="operator-batch:create:1",
    )

    assert result.status is ActionStatus.COMMITTED
    batch_revision_id = next(
        ref.object_id
        for ref in result.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        selected = fixture.judgment.decision_actions.resolve_current_selection_in_uow(
            uow,
            candidate_selection_id=selection_id,
        )
        batch = uow.tickets.batch_revision(batch_revision_id)
        lineage = uow.operator_result.ticket_decision_lineage_for_batch(
            batch_revision_id
        )
        assert batch is not None
        assert lineage is not None
        assert lineage.candidate_revision_id == candidate.candidate_revision_id
        assert lineage.candidate_selection_id == selection_id
        assert selected.candidate.candidate_revision_id == candidate.candidate_revision_id
        assert len(
            uow.operator_result.ticket_decision_lineage_items(
                lineage.lineage_revision_id
            )
        ) == 1
        assert uow.tickets.ticket_artifacts_for_revision(batch_revision_id) == []
        assert batch.state == "draft"
        assert batch.currency == candidate_ticket.currency


def test_operator_batch_idempotency_binds_account_and_run_date(tmp_path: Path) -> None:
    fixture, selection_id, _candidate, _candidate_ticket = _selected_candidate_fixture(
        tmp_path
    )
    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=_persisted_current_audit,
    )
    _create_operator_batch(
        protected,
        selection_id,
        key="operator-batch:create:idempotency-scope",
    )

    with pytest.raises(IdempotencyConflictError):
        protected.create_operator_ticket_batch(
            CreateOperatorTicketBatchRequest(
                candidate_selection_id=selection_id,
                account_id="acct-jczq",
                run_date="2026-09-05",
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="operator-batch:create:idempotency-scope",
                requested_at=AT + timedelta(seconds=10),
            )
        )


def test_operator_approval_freezes_server_deadline_and_relational_artifact(
    tmp_path: Path,
) -> None:
    fixture, selection_id, candidate, candidate_ticket = _selected_candidate_fixture(
        tmp_path
    )
    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=_persisted_current_audit,
    )
    created = _create_operator_batch(
        protected,
        selection_id,
        key="operator-batch:create:approval",
    )
    draft_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )

    approved = protected.approve_operator_ticket_batch(
        ApproveOperatorTicketBatchRequest(
            ticket_batch_revision_id=draft_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="operator-batch:approve:1",
            requested_at=AT + timedelta(seconds=11),
        )
    )

    artifact_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    approved_revision_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        binding = uow.tickets.protected_artifact_binding(artifact_id)
        links = uow.tickets.protected_artifact_offer_revision_links(artifact_id)
        artifact = uow.tickets.ticket_artifact(artifact_id)
        approved_lineage = (
            None
            if binding is None
            else uow.operator_result.ticket_decision_lineage_revision(
                binding.lineage_revision_id
            )
        )
        assert binding is not None
        assert artifact is not None
        assert approved_lineage is not None
        assert artifact.ticket_batch_revision_id == approved_revision_id
        assert approved_lineage.ticket_batch_revision_id == approved_revision_id
        assert approved_lineage.supersedes_revision_id is not None
        assert binding.candidate_revision_id == candidate.candidate_revision_id
        assert binding.candidate_ticket_id == candidate_ticket.candidate_ticket_id
        assert binding.stake_minor == candidate_ticket.stake_minor
        assert binding.composition_hash == candidate_ticket.composition_hash
        assert binding.frozen_deadline_at == (AT + timedelta(hours=4)).isoformat()
        assert artifact.deadline_at == binding.frozen_deadline_at
        assert [link.official_offer_revision_id for link in links] == [
            "offer-revision-1"
        ]
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM tickets")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM cash_transactions")) == 0


def test_operator_approval_requires_regeneration_and_inherits_exact_overrides(
    tmp_path: Path,
) -> None:
    fixture = _setup_override_fixture(tmp_path)
    protected = ProtectedTicketActions(
        fixture.action_service,
        ContentAddressedArtifactStore(tmp_path / "approved-artifacts"),
        operator_decisions=fixture.actions,
        operator_candidate_auditor=_persisted_current_audit,
    )
    request = ApproveOperatorTicketBatchRequest(
        ticket_batch_revision_id=fixture.batch_revision_id,
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="operator-batch:approve:error",
        requested_at=AT + timedelta(seconds=12),
    )

    with pytest.raises(ValueError, match="ERROR"):
        protected.approve_operator_ticket_batch(request)

    override = fixture.actions.record_ticket_audit_override(_override_request(fixture))
    assert override.status is ActionStatus.COMMITTED
    with pytest.raises(ValueError, match="regenerat"):
        protected.approve_operator_ticket_batch(
            replace(request, idempotency_key="operator-batch:approve:pending-regeneration")
        )

    generation_request_id = next(
        ref.object_id
        for ref in override.result_refs
        if ref.object_type == "operator_candidate_generation_request"
    )
    regenerated = _generate(
        fixture.candidate_fixture,
        request_id=generation_request_id,
        key="candidate:generate:override",
        judgment_candidate=_audit_blocked_candidate(),
        as_of=AT + timedelta(seconds=12),
    )
    assert regenerated.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(fixture.engine) as uow:
        candidate_set = next(
            row
            for row in uow.operator_result.candidate_sets_for_request(
                generation_request_id
            )
            if row.set_kind == "judgment_bound"
        )
        candidate = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )[0]
    selected = fixture.actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason="Jun explicitly reselects the regenerated candidate.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="operator-batch:selection:regenerated",
            requested_at=AT + timedelta(seconds=13),
            expected_current_revision_no=1,
        )
    )
    fresh_batch = _create_operator_batch(
        protected,
        selected.result_refs[0].object_id,
        key="operator-batch:create:regenerated",
    )
    fresh_batch_revision_id = next(
        ref.object_id
        for ref in fresh_batch.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    approved = protected.approve_operator_ticket_batch(
        ApproveOperatorTicketBatchRequest(
            ticket_batch_revision_id=fresh_batch_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="operator-batch:approve:regenerated",
            requested_at=AT + timedelta(seconds=14),
        )
    )

    assert approved.status is ActionStatus.COMMITTED
    assert any(
        ref.object_type == "audited_ticket_artifact" for ref in approved.result_refs
    )


def test_operator_approval_rejects_exact_official_deadline(tmp_path: Path) -> None:
    fixture, selection_id, _candidate_row, _candidate_ticket = (
        _selected_candidate_fixture(tmp_path)
    )
    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=_persisted_current_audit,
    )
    created = _create_operator_batch(
        protected,
        selection_id,
        key="operator-batch:create:cutoff",
    )
    draft_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )

    with pytest.raises(ValueError, match="deadline|closed"):
        protected.approve_operator_ticket_batch(
            ApproveOperatorTicketBatchRequest(
                ticket_batch_revision_id=draft_revision_id,
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="operator-batch:approve:cutoff",
                requested_at=AT + timedelta(hours=4),
            )
        )
