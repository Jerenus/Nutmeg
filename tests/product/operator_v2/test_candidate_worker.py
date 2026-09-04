from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.operator.decision_actions import (
    FaceOffsetInput,
    FaceProbabilityInput,
    FactorAdjustmentInput,
    FreezeJudgmentPrescriptionRequest,
)
from nutmeg.ontology.operator.result_actions import OperatorResultActions
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product import operator_workers as operator_worker_module
from nutmeg.product.operator_workers import CandidateGenerationWorker
from tests.ontology.operator.test_candidate_actions import (
    CandidateFixture,
    _generation_request,
    _ready_fixture,
)
from tests.ontology.operator.test_judgment_actions import (
    AT,
    WORK_ITEM_ID,
    _baseline_request,
    _envelope_request,
    _fixture,
    _judgment_request,
)


def _ready_fixture_with_cap(
    tmp_path: Path,
    capital_cap_minor: int,
    *,
    shifted_belief: bool = False,
    dropped_modal: bool = False,
) -> CandidateFixture:
    fixture = _fixture(tmp_path)
    baseline = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )
    envelope = fixture.decision_actions.record_baseline_envelope(
        replace(_envelope_request(fixture), capital_cap_minor=capital_cap_minor)
    )
    baseline_id = baseline.result_refs[0].object_id
    envelope_id = envelope.result_refs[0].object_id
    judgment_request = _judgment_request(fixture, baseline_id, envelope_id)
    if shifted_belief or dropped_modal:
        belief = (
            (
                FaceProbabilityInput("3", "0.200000000000"),
                FaceProbabilityInput("1", "0.300000000000"),
                FaceProbabilityInput("0", "0.500000000000"),
            )
            if dropped_modal
            else (
                FaceProbabilityInput("3", "0.500000000000"),
                FaceProbabilityInput("1", "0.300000000000"),
                FaceProbabilityInput("0", "0.200000000000"),
            )
        )
        offsets = (
            (
                FaceOffsetInput("3", "-0.200000000000"),
                FaceOffsetInput("1", "0.000000000000"),
                FaceOffsetInput("0", "0.200000000000"),
            )
            if dropped_modal
            else (
                FaceOffsetInput("3", "0.100000000000"),
                FaceOffsetInput("1", "0.000000000000"),
                FaceOffsetInput("0", "-0.100000000000"),
            )
        )
        judgment_request = replace(
            judgment_request,
            belief=belief,
            factors=(
                FactorAdjustmentInput(
                    factor_definition_id="factor-1",
                    scope_key="match-1",
                    evidence_ref_tokens=("obs-anchor",),
                    offsets=offsets,
                ),
            ),
        )
    judgment = fixture.decision_actions.commit_operator_match_judgment(judgment_request)
    judgment_id = next(
        ref.object_id
        for ref in judgment.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    prescription = fixture.decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=fixture.task_bundle_revision_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id=WORK_ITEM_ID,
            judgment_revision_ids=(judgment_id,),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="candidate-worker:prescription:1",
            requested_at=AT + timedelta(seconds=5),
            expected_current_revision_no=0,
        )
    )
    return CandidateFixture(
        judgment=fixture,
        result_actions=OperatorResultActions(fixture.action_service),
        baseline_id=baseline_id,
        envelope_id=envelope_id,
        prescription_id=prescription.result_refs[0].object_id,
    )


def _worker(fixture: CandidateFixture, *, worker_id: str = "candidate-worker", actions=None):
    return CandidateGenerationWorker(
        action_service=fixture.judgment.action_service,
        result_actions=actions or fixture.result_actions,
        worker_id=worker_id,
        lease_duration=timedelta(minutes=5),
    )


def _request_generation(fixture: CandidateFixture):
    return fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )


def test_worker_assembles_frozen_judgment_and_market_counterfactual_sets(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture_with_cap(
        tmp_path,
        capital_cap_minor=20_000,
        shifted_belief=True,
    )
    requested = _request_generation(fixture)

    completed = _worker(fixture).run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7),
    )

    assert requested.status is ActionStatus.COMMITTED
    assert len(completed) == 1
    assert completed[0].status is ActionStatus.COMMITTED
    with fixture.judgment.engine.connect() as connection:
        sets = connection.execute(
            text(
                "SELECT set_kind, candidate_count, comparison_only "
                "FROM operator_candidate_set_revisions ORDER BY set_kind"
            )
        ).all()
        probabilities = connection.execute(
            text(
                "SELECT candidate_set.set_kind, metric.objective_probability_decimal "
                "FROM operator_candidate_metrics AS metric "
                "JOIN operator_candidates AS candidate "
                "USING (candidate_revision_id) "
                "JOIN operator_candidate_set_revisions AS candidate_set "
                "USING (candidate_set_revision_id) "
                "ORDER BY candidate_set.set_kind, metric.objective_probability_decimal"
            )
        ).all()
        job = connection.execute(
            text(
                "SELECT state, attempt_count, result_action_id "
                "FROM operator_worker_jobs WHERE job_kind = 'candidate_generation'"
            )
        ).one()
        selected_count = connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_selections")
        )
        prescription_differences = connection.execute(
            text(
                "SELECT candidate_set.set_kind, finding.finding_code, "
                "finding.severity, finding.official_match_no, finding.rule_id "
                "FROM operator_candidate_audit_findings AS finding "
                "JOIN operator_candidates AS candidate USING (candidate_revision_id) "
                "JOIN operator_candidate_set_revisions AS candidate_set "
                "USING (candidate_set_revision_id) "
                "WHERE finding.audit_kind = 'prescription_difference' "
                "ORDER BY candidate_set.set_kind, finding.finding_code"
            )
        ).all()
    assert sets == [
        ("conditional_market_counterfactual", 2, 1),
        ("judgment_bound", 1, 0),
    ]
    assert probabilities == [
        ("conditional_market_counterfactual", "0.400000000000"),
        ("conditional_market_counterfactual", "0.700000000000"),
        ("judgment_bound", "0.800000000000"),
    ]
    assert job == ("completed", 1, completed[0].action_id)
    assert selected_count == 0
    assert (
        "conditional_market_counterfactual",
        "candidate_differs_from_prescription",
        "WARN",
        "001",
        "k",
    ) in prescription_differences


def test_worker_persists_over_cap_candidates_instead_of_hiding_them(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture_with_cap(tmp_path, capital_cap_minor=300)
    _request_generation(fixture)

    completed = _worker(fixture).run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7),
    )

    assert len(completed) == 1
    with fixture.judgment.engine.connect() as connection:
        partitions = connection.execute(
            text(
                "SELECT candidate_set.set_kind, candidate.partition, "
                "candidate.rank, candidate.deployable, metric.stake_minor "
                "FROM operator_candidates AS candidate "
                "JOIN operator_candidate_set_revisions AS candidate_set "
                "USING (candidate_set_revision_id) "
                "JOIN operator_candidate_metrics AS metric USING (candidate_revision_id) "
                "ORDER BY candidate_set.set_kind, metric.stake_minor, candidate.content_hash"
            )
        ).all()
        budget_findings = connection.execute(
            text(
                "SELECT candidate_set.set_kind, finding.finding_code, finding.severity "
                "FROM operator_candidate_audit_findings AS finding "
                "JOIN operator_candidates AS candidate USING (candidate_revision_id) "
                "JOIN operator_candidate_set_revisions AS candidate_set "
                "USING (candidate_set_revision_id) "
                "WHERE finding.audit_kind = 'budget' "
                "ORDER BY candidate_set.set_kind"
            )
        ).all()
    assert partitions == [
        ("conditional_market_counterfactual", "eligible", 1, 0, 200),
        ("conditional_market_counterfactual", "over_cap", None, 0, 400),
        ("judgment_bound", "over_cap", None, 0, 400),
    ]
    assert budget_findings == [
        ("conditional_market_counterfactual", "capital_cap_exceeded", "ERROR"),
        ("judgment_bound", "capital_cap_exceeded", "ERROR"),
    ]


def test_worker_persists_deployment_audit_findings_for_every_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _ready_fixture(tmp_path)
    _request_generation(fixture)
    monkeypatch.setitem(
        operator_worker_module._SUPPORTED_SETTLEMENT_MARKETS,
        "jczq",
        frozenset(),
    )

    completed = _worker(fixture).run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7),
    )

    assert len(completed) == 1
    with fixture.judgment.engine.connect() as connection:
        candidates = connection.scalar(text("SELECT COUNT(*) FROM operator_candidates"))
        findings = connection.execute(
            text(
                "SELECT audit_kind, finding_code, severity "
                "FROM operator_candidate_audit_findings "
                "WHERE audit_kind = 'deployment'"
            )
        ).all()
        completion_count = connection.scalar(
            text(
                "SELECT COUNT(*) FROM operator_candidates "
                "WHERE leg_audit_completed = 1 "
                "AND prescription_audit_completed = 1 "
                "AND budget_check_completed = 1 "
                "AND deployment_report_completed = 1"
            )
        )
    assert len(findings) == candidates
    assert set(findings) == {
        ("deployment", "unsupported_settlement_market", "ERROR")
    }
    assert completion_count == candidates


def test_worker_rejects_generation_at_exact_offer_deadline(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    _request_generation(fixture)

    completed = _worker(fixture).run_once(
        limit=1,
        as_of=AT + timedelta(hours=4),
    )

    assert completed == ()
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_set_revisions")
        ) == 0
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM actions "
                "WHERE action_type = 'generate_ticket_candidate_set'"
            )
        ) == 0
        state = connection.execute(
            text(
                "SELECT state, last_error_code FROM operator_worker_jobs "
                "WHERE job_kind = 'candidate_generation'"
            )
        ).one()
    assert state[0] == "failed"


@pytest.mark.parametrize("drift_kind", ("captured_at", "selection", "membership"))
def test_worker_rejects_quote_lineage_drift_after_request(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    fixture = _ready_fixture(tmp_path)
    _request_generation(fixture)
    with fixture.judgment.engine.begin() as connection:
        if drift_kind == "captured_at":
            connection.execute(
                text(
                    "UPDATE market_quotes SET captured_at = :captured_at "
                    "WHERE quote_id = 'quote-3'"
                ),
                {"captured_at": (AT - timedelta(minutes=1)).isoformat()},
            )
        elif drift_kind == "selection":
            connection.execute(
                text(
                    "UPDATE market_quotes SET selection_id = 'sel-had-draw' "
                    "WHERE quote_id = 'quote-3'"
                )
            )
        else:
            connection.execute(
                text(
                    "DELETE FROM market_snapshot_quotes "
                    "WHERE market_snapshot_id = 'snapshot-1' "
                    "AND quote_id = 'quote-3'"
                )
            )

    assert _worker(fixture).run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7),
    ) == ()
    with fixture.judgment.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_candidate_set_revisions")
        ) == 0
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM actions "
                "WHERE action_type = 'generate_ticket_candidate_set'"
            )
        ) == 0
        state = connection.execute(
            text(
                "SELECT state, last_error_code FROM operator_worker_jobs "
                "WHERE job_kind = 'candidate_generation'"
            )
        ).one()
    assert state[0] == "failed"


def test_worker_runs_current_leg_audit_before_candidate_ordering(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture_with_cap(
        tmp_path,
        capital_cap_minor=20_000,
        dropped_modal=True,
    )
    _request_generation(fixture)

    completed = _worker(fixture).run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7),
    )

    assert len(completed) == 1
    with fixture.judgment.engine.connect() as connection:
        judgment_candidate = connection.execute(
            text(
                "SELECT candidate.candidate_revision_id, candidate.partition "
                "FROM operator_candidates AS candidate "
                "JOIN operator_candidate_set_revisions AS candidate_set "
                "USING (candidate_set_revision_id) "
                "WHERE candidate_set.set_kind = 'judgment_bound'"
            )
        ).one()
        findings = connection.execute(
            text(
                "SELECT audit_kind, finding_code, severity, official_match_no "
                "FROM operator_candidate_audit_findings "
                "WHERE candidate_revision_id = :candidate_revision_id"
            ),
            {"candidate_revision_id": judgment_candidate.candidate_revision_id},
        ).all()
    assert judgment_candidate.partition == "audit_blocked"
    assert (
        "legs",
        "modal_face_dropped",
        "ERROR",
        "001",
    ) in findings


def test_hhad_worker_freezes_quote_line_through_baseline_and_candidate(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        market_definition_id="md-hhad",
        settlement_parameter_decimal="-1.000000000000",
    )
    baseline = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )
    envelope = fixture.decision_actions.record_baseline_envelope(
        _envelope_request(fixture, market_code="hhad")
    )
    baseline_id = baseline.result_refs[0].object_id
    envelope_id = envelope.result_refs[0].object_id
    judgment = fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            market_definition_id="md-hhad",
        )
    )
    judgment_id = next(
        ref.object_id
        for ref in judgment.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    prescription = fixture.decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=fixture.task_bundle_revision_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id=WORK_ITEM_ID,
            judgment_revision_ids=(judgment_id,),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="candidate-worker:hhad-prescription:1",
            requested_at=AT + timedelta(seconds=5),
            expected_current_revision_no=0,
        )
    )
    candidate_fixture = CandidateFixture(
        judgment=fixture,
        result_actions=OperatorResultActions(fixture.action_service),
        baseline_id=baseline_id,
        envelope_id=envelope_id,
        prescription_id=prescription.result_refs[0].object_id,
    )
    _request_generation(candidate_fixture)

    completed = _worker(candidate_fixture).run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7),
    )

    assert len(completed) == 1
    with fixture.engine.connect() as connection:
        baseline_lines = connection.execute(
            text(
                "SELECT DISTINCT settlement_parameter_decimal "
                "FROM operator_market_prior_baseline_probabilities"
            )
        ).scalars().all()
        candidate_lines = connection.execute(
            text(
                "SELECT DISTINCT settlement_parameter_decimal "
                "FROM operator_candidate_ticket_legs"
            )
        ).scalars().all()
    assert baseline_lines == ["-1.000000000000"]
    assert candidate_lines == ["-1.000000000000"]


class _LockedOnceResultActions:
    def __init__(self, delegate: OperatorResultActions) -> None:
        self.delegate = delegate
        self.calls = 0

    def generate_ticket_candidate_set(self, request):
        self.calls += 1
        if self.calls == 1:
            raise OperationalError(
                "UPDATE operator_worker_jobs",
                {},
                Exception("database is locked"),
            )
        return self.delegate.generate_ticket_candidate_set(request)


def test_worker_requeues_sqlite_contention_and_retries_same_request(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    requested = _request_generation(fixture)
    actions = _LockedOnceResultActions(fixture.result_actions)
    worker = _worker(fixture, actions=actions)

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=7)) == ()
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        queued = uow.operator_decision.worker_job_for_source(
            job_kind="candidate_generation",
            source_object_type="operator_candidate_generation_request",
            source_object_id=requested.result_refs[0].object_id,
        )
    assert queued is not None
    assert (queued.state, queued.attempt_count, queued.last_error_code) == (
        "queued",
        1,
        "sqlite_contention",
    )
    assert queued.available_at == (AT + timedelta(seconds=8)).isoformat()

    assert worker.run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7, microseconds=999_999),
    ) == ()
    completed = worker.run_once(limit=1, as_of=AT + timedelta(seconds=8))

    assert len(completed) == 1
    assert actions.calls == 2


def test_worker_recovers_only_expired_candidate_generation_lease(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    _request_generation(fixture)
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="candidate_generation",
            lease_owner="dead-worker",
            as_of=(AT + timedelta(seconds=7)).isoformat(),
            lease_expires_at=(AT + timedelta(seconds=8)).isoformat(),
            limit=1,
        )
    assert len(claimed) == 1
    replacement = _worker(fixture, worker_id="replacement-worker")

    assert replacement.run_once(
        limit=1,
        as_of=AT + timedelta(seconds=7, microseconds=999_999),
    ) == ()
    assert replacement.run_once(limit=1, as_of=AT + timedelta(seconds=8)) == ()
    completed = replacement.run_once(limit=1, as_of=AT + timedelta(seconds=9))

    assert len(completed) == 1
    with fixture.judgment.engine.connect() as connection:
        job = connection.execute(
            text(
                "SELECT state, lease_owner, attempt_count "
                "FROM operator_worker_jobs WHERE job_kind = 'candidate_generation'"
            )
        ).one()
    assert job == ("completed", None, 2)
