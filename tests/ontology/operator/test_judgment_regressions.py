from __future__ import annotations

import json
import re
from dataclasses import fields, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from nutmeg.ontology.actions.models import ActionOutcome, ActionStatus, ActorRole
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.operator.decision_actions import (
    FaceOffsetInput,
    FactorAdjustmentInput,
    FreezeJudgmentPrescriptionRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from nutmeg.product.operator_workers import MarketBaselineWorker
from tests.ontology.operator.test_judgment_actions import (
    AT,
    WORK_ITEM_ID,
    JudgmentFixture,
    _baseline_request,
    _envelope_request,
    _fixture,
    _judgment_request,
)

_EXPECTED_REVISION_FIELD = "expected_current_revision_no"
_NO_EXPECTED_REVISION = object()


def _result_id(outcome: ActionOutcome, object_type: str) -> str:
    assert outcome.status is ActionStatus.COMMITTED
    return next(
        ref.object_id for ref in outcome.result_refs if ref.object_type == object_type
    )


def _supports_expected_revision(request_or_type: object) -> bool:
    return _EXPECTED_REVISION_FIELD in {
        field.name for field in fields(request_or_type)
    }


def _with_expected_revision(request: object, revision_no: int):
    if not _supports_expected_revision(request):
        return request
    return replace(request, expected_current_revision_no=revision_no)


def _create_baseline_and_envelope(
    fixture: JudgmentFixture,
) -> tuple[str, str]:
    baseline = fixture.decision_actions.freeze_market_prior_baseline(
        _baseline_request(fixture)
    )
    envelope_request = _with_expected_revision(_envelope_request(fixture), 0)
    envelope = fixture.decision_actions.record_baseline_envelope(envelope_request)
    return (
        _result_id(baseline, "market_prior_baseline_revision"),
        _result_id(envelope, "baseline_envelope_revision"),
    )


def _commit_judgment(
    fixture: JudgmentFixture,
    baseline_id: str,
    envelope_id: str,
    *,
    key: str,
    expected_revision_no: int,
    rationale: str,
    factors: tuple[FactorAdjustmentInput, ...] = (),
) -> str:
    request = replace(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            key=key,
            factors=factors,
        ),
        expected_current_revision_no=expected_revision_no,
        rationale=rationale,
    )
    outcome = fixture.decision_actions.commit_operator_match_judgment(request)
    return _result_id(outcome, "operator_match_judgment_revision")


def _prescription_request(
    fixture: JudgmentFixture,
    baseline_id: str,
    envelope_id: str,
    judgment_ids: tuple[str, ...],
    *,
    key: str,
    expected_revision_no: int | object = _NO_EXPECTED_REVISION,
) -> FreezeJudgmentPrescriptionRequest:
    kwargs: dict[str, object] = {
        "task_evidence_bundle_revision_id": fixture.task_bundle_revision_id,
        "market_prior_baseline_revision_id": baseline_id,
        "baseline_envelope_revision_id": envelope_id,
        "work_item_id": WORK_ITEM_ID,
        "judgment_revision_ids": judgment_ids,
        "actor_id": "jun",
        "actor_role": ActorRole.JUDGE_OPERATOR,
        "idempotency_key": key,
        "requested_at": AT + timedelta(seconds=5),
    }
    if (
        expected_revision_no is not _NO_EXPECTED_REVISION
        and _supports_expected_revision(FreezeJudgmentPrescriptionRequest)
    ):
        kwargs[_EXPECTED_REVISION_FIELD] = expected_revision_no
    return FreezeJudgmentPrescriptionRequest(**kwargs)


def _insert_superseding_slate(fixture: JudgmentFixture) -> None:
    changed_at = (AT + timedelta(seconds=20)).isoformat()
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO official_sale_slate_revisions "
            "(slate_revision_id, slate_family_id, lane, business_key, revision_no, "
            "source_artifact_retrieval_id, published_at, retrieved_at, valid_from, "
            "supersedes_slate_revision_id, content_hash) VALUES "
            "('slate-2', 'jczq:2026-09-04', 'jczq', '2026-09-04', 2, "
            "'retrieval-1', ?, ?, ?, 'slate-1', ?)",
            (changed_at, changed_at, changed_at, "d" * 64),
        )


def _cancel_current_offer(fixture: JudgmentFixture) -> None:
    with fixture.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE official_offer_revisions SET status = 'cancelled' "
                "WHERE official_offer_revision_id = 'offer-revision-1'"
            )
        )


def _invoke_decision_write(
    fixture: JudgmentFixture,
    action_kind: str,
    baseline_id: str,
    envelope_id: str,
) -> ActionOutcome:
    if action_kind == "baseline":
        return fixture.decision_actions.freeze_market_prior_baseline(
            _baseline_request(fixture, key=f"baseline:{action_kind}:changed-sale")
        )
    if action_kind == "envelope":
        request = _with_expected_revision(
            _envelope_request(fixture, key=f"envelope:{action_kind}:changed-sale"),
            1,
        )
        return fixture.decision_actions.record_baseline_envelope(request)
    if action_kind == "judgment":
        return fixture.decision_actions.commit_operator_match_judgment(
            _judgment_request(
                fixture,
                baseline_id,
                envelope_id,
                key=f"judgment:{action_kind}:changed-sale",
            )
        )
    raise AssertionError(f"unknown test action kind {action_kind}")


@pytest.mark.parametrize("action_kind", ("baseline", "envelope", "judgment"))
def test_superseding_official_slate_blocks_every_judgment_write(
    tmp_path: Path,
    action_kind: str,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    _insert_superseding_slate(fixture)

    with pytest.raises(ValueError, match="slate|stale|superseded"):
        _invoke_decision_write(fixture, action_kind, baseline_id, envelope_id)


@pytest.mark.parametrize("action_kind", ("baseline", "envelope", "judgment"))
def test_cancelled_current_offer_blocks_every_judgment_write(
    tmp_path: Path,
    action_kind: str,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    _cancel_current_offer(fixture)

    with pytest.raises(ValueError, match="cancel|current.*offer|offer.*current|stale"):
        _invoke_decision_write(fixture, action_kind, baseline_id, envelope_id)


def test_envelope_requires_an_explicit_expected_revision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))
    request = _envelope_request(fixture, key="envelope:missing-cas")

    assert _supports_expected_revision(request), (
        "RecordBaselineEnvelopeRequest must expose expected_current_revision_no"
    )
    request = replace(request, expected_current_revision_no=None)
    with pytest.raises(ValueError, match="expected_current_revision_no.*required"):
        fixture.decision_actions.record_baseline_envelope(request)


def test_judgment_requires_an_explicit_expected_revision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    request = replace(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            key="judgment:missing-cas",
        ),
        expected_current_revision_no=None,
    )

    with pytest.raises(ValueError, match="expected_current_revision_no.*required"):
        fixture.decision_actions.commit_operator_match_judgment(request)


def test_prescription_requires_an_explicit_expected_revision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    judgment_id = _commit_judgment(
        fixture,
        baseline_id,
        envelope_id,
        key="judgment:for-missing-prescription-cas",
        expected_revision_no=0,
        rationale="Initial committed judgment.",
    )

    assert _supports_expected_revision(FreezeJudgmentPrescriptionRequest), (
        "FreezeJudgmentPrescriptionRequest must expose expected_current_revision_no"
    )
    request = _prescription_request(
        fixture,
        baseline_id,
        envelope_id,
        (judgment_id,),
        key="prescription:missing-cas",
    )
    with pytest.raises(ValueError, match="expected_current_revision_no.*required"):
        fixture.decision_actions.freeze_judgment_prescription(request)


def test_envelope_rejects_a_stale_expected_revision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _baseline_id, _envelope_id = _create_baseline_and_envelope(fixture)
    stale_request = _with_expected_revision(
        replace(
            _envelope_request(fixture, key="envelope:stale-cas"),
            capital_cap_minor=18000,
        ),
        0,
    )

    with pytest.raises(OptimisticConcurrencyError):
        fixture.decision_actions.record_baseline_envelope(stale_request)


def test_judgment_rejects_a_stale_expected_revision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    _commit_judgment(
        fixture,
        baseline_id,
        envelope_id,
        key="judgment:cas-a",
        expected_revision_no=0,
        rationale="Revision A.",
    )
    stale_request = replace(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            key="judgment:cas-stale",
        ),
        expected_current_revision_no=0,
        rationale="Stale revision attempt.",
    )

    with pytest.raises(OptimisticConcurrencyError):
        fixture.decision_actions.commit_operator_match_judgment(stale_request)


def test_prescription_rejects_a_stale_expected_revision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    judgment_a = _commit_judgment(
        fixture,
        baseline_id,
        envelope_id,
        key="judgment:prescription-cas-a",
        expected_revision_no=0,
        rationale="Revision A.",
    )
    first = _prescription_request(
        fixture,
        baseline_id,
        envelope_id,
        (judgment_a,),
        key="prescription:cas-a",
        expected_revision_no=0,
    )
    fixture.decision_actions.freeze_judgment_prescription(first)
    judgment_b = _commit_judgment(
        fixture,
        baseline_id,
        envelope_id,
        key="judgment:prescription-cas-b",
        expected_revision_no=1,
        rationale="Revision B.",
    )
    stale_request = _prescription_request(
        fixture,
        baseline_id,
        envelope_id,
        (judgment_b,),
        key="prescription:cas-stale",
        expected_revision_no=0,
    )

    with pytest.raises(OptimisticConcurrencyError):
        fixture.decision_actions.freeze_judgment_prescription(stale_request)


def test_superseded_envelope_invalidates_progress_and_prescription_context(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_a = _create_baseline_and_envelope(fixture)
    judgment_id = _commit_judgment(
        fixture,
        baseline_id,
        envelope_a,
        key="judgment:before-envelope-change",
        expected_revision_no=0,
        rationale="Bound to envelope A.",
    )
    prescription = fixture.decision_actions.freeze_judgment_prescription(
        _prescription_request(
            fixture,
            baseline_id,
            envelope_a,
            (judgment_id,),
            key="prescription:before-envelope-change",
            expected_revision_no=0,
        )
    )
    prescription_id = _result_id(
        prescription,
        "judgment_prescription_revision",
    )
    envelope_b = fixture.decision_actions.record_baseline_envelope(
        _with_expected_revision(
            replace(
                _envelope_request(fixture, key="envelope:superseding"),
                capital_cap_minor=18000,
            ),
            1,
        )
    )
    assert _result_id(envelope_b, "baseline_envelope_revision") != envelope_a

    assert fixture.decision_actions.committed_judgment_progress(
        fixture.task_bundle_revision_id
    ) == (0, 1)
    queries = OperatorQueryService(
        repository=SimpleNamespace(),
        product_queries=SimpleNamespace(),
        official_history_provider=lambda: [],
        clock=lambda: AT + timedelta(seconds=30),
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(b"j" * 32),
    )
    with pytest.raises(ProductActionBlockedError, match="current committed judgment"):
        queries.judgment_prescription_context(
            "jczq:2026-09-04",
            as_of=AT + timedelta(seconds=30),
        )
    with fixture.engine.connect() as connection:
        historical_count = connection.scalar(
            text(
                "SELECT COUNT(*) FROM operator_judgment_prescription_revisions "
                "WHERE judgment_prescription_revision_id = :revision_id"
            ),
            {"revision_id": prescription_id},
        )
    assert historical_count == 1


def test_envelope_revision_chain_allows_semantic_a_b_a(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))
    request_a = _envelope_request(fixture, key="envelope:aba:a1")
    first = fixture.decision_actions.record_baseline_envelope(
        _with_expected_revision(request_a, 0)
    )
    second = fixture.decision_actions.record_baseline_envelope(
        _with_expected_revision(
            replace(request_a, capital_cap_minor=18000, idempotency_key="envelope:aba:b"),
            1,
        )
    )
    third = fixture.decision_actions.record_baseline_envelope(
        _with_expected_revision(
            replace(request_a, idempotency_key="envelope:aba:a2"),
            2,
        )
    )

    ids = [
        _result_id(item, "baseline_envelope_revision")
        for item in (first, second, third)
    ]
    assert len(set(ids)) == 3
    with fixture.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT baseline_envelope_revision_id, revision_no, "
                "supersedes_revision_id, capital_cap_minor, content_hash "
                "FROM operator_baseline_envelope_revisions "
                "ORDER BY revision_no"
            )
        ).mappings().all()
    assert [row["revision_no"] for row in rows] == [1, 2, 3]
    assert [row["capital_cap_minor"] for row in rows] == [20000, 18000, 20000]
    assert rows[1]["supersedes_revision_id"] == rows[0]["baseline_envelope_revision_id"]
    assert rows[2]["supersedes_revision_id"] == rows[1]["baseline_envelope_revision_id"]
    assert rows[0]["content_hash"] == rows[2]["content_hash"]
    assert rows[0]["content_hash"] != rows[1]["content_hash"]


def test_judgment_revision_chain_allows_semantic_a_b_a(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    ids = [
        _commit_judgment(
            fixture,
            baseline_id,
            envelope_id,
            key="judgment:aba:a1",
            expected_revision_no=0,
            rationale="Semantic revision A.",
        ),
        _commit_judgment(
            fixture,
            baseline_id,
            envelope_id,
            key="judgment:aba:b",
            expected_revision_no=1,
            rationale="Semantic revision B.",
        ),
        _commit_judgment(
            fixture,
            baseline_id,
            envelope_id,
            key="judgment:aba:a2",
            expected_revision_no=2,
            rationale="Semantic revision A.",
        ),
    ]

    assert len(set(ids)) == 3
    with fixture.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT operator_match_judgment_revision_id, revision_no, "
                "supersedes_revision_id, rationale, content_hash "
                "FROM operator_match_judgment_revisions ORDER BY revision_no"
            )
        ).mappings().all()
    assert [row["revision_no"] for row in rows] == [1, 2, 3]
    assert [row["rationale"] for row in rows] == [
        "Semantic revision A.",
        "Semantic revision B.",
        "Semantic revision A.",
    ]
    assert rows[1]["supersedes_revision_id"] == rows[0][
        "operator_match_judgment_revision_id"
    ]
    assert rows[2]["supersedes_revision_id"] == rows[1][
        "operator_match_judgment_revision_id"
    ]
    assert rows[0]["content_hash"] == rows[2]["content_hash"]
    assert rows[0]["content_hash"] != rows[1]["content_hash"]


def test_market_code_alias_is_normalized_or_rejected_without_a_second_revision(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))
    canonical_request = _envelope_request(fixture, key="envelope:market-code")
    canonical = fixture.decision_actions.record_baseline_envelope(
        _with_expected_revision(canonical_request, 0)
    )
    canonical_id = _result_id(canonical, "baseline_envelope_revision")
    internal_id_request = replace(
        canonical_request,
        offer_constraints=(
            replace(canonical_request.offer_constraints[0], market_code="md-had"),
        ),
        idempotency_key="envelope:internal-market-id",
    )

    try:
        internal = fixture.decision_actions.record_baseline_envelope(
            _with_expected_revision(internal_id_request, 1)
        )
    except ValueError as error:
        assert re.search("market", str(error), flags=re.IGNORECASE)
    else:
        assert _result_id(internal, "baseline_envelope_revision") == canonical_id


def test_market_kind_alias_is_rejected_as_an_internal_judgment_market_id(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    request = replace(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            key="judgment:market-kind-as-id",
        ),
        market_definition_id="had",
    )

    with pytest.raises(ValueError, match="offer|market"):
        fixture.decision_actions.commit_operator_match_judgment(request)


def test_baseline_requires_the_complete_registered_market_face_set(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    incomplete = json.dumps(
        {"away": 0.5, "home": 0.5},
        sort_keys=True,
        separators=(",", ":"),
    )
    with fixture.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE market_snapshots SET fair_distribution_json = :distribution "
                "WHERE market_snapshot_id = 'snapshot-1'"
            ),
            {"distribution": incomplete},
        )
        connection.execute(
            text(
                "UPDATE evidence_bundles SET prior_distribution_json = :distribution "
                "WHERE evidence_bundle_id = ("
                "SELECT evidence_bundle_id FROM operator_task_evidence_bundle_items "
                "WHERE task_evidence_bundle_revision_id = :revision_id)"
            ),
            {
                "distribution": incomplete,
                "revision_id": fixture.task_bundle_revision_id,
            },
        )
        connection.execute(
            text(
                "DELETE FROM market_snapshot_quotes "
                "WHERE market_snapshot_id = 'snapshot-1' AND quote_id = 'quote-1'"
            )
        )

    with pytest.raises(ValueError, match="complete|face|selection"):
        fixture.decision_actions.freeze_market_prior_baseline(
            _baseline_request(fixture, key="baseline:incomplete-faces")
        )


def _zero_factor(scope_key: str) -> tuple[FactorAdjustmentInput, ...]:
    return (
        FactorAdjustmentInput(
            factor_definition_id="factor-1",
            scope_key=scope_key,
            evidence_ref_tokens=("obs-anchor",),
            offsets=(
                FaceOffsetInput("3", "0.000000000000"),
                FaceOffsetInput("1", "0.000000000000"),
                FaceOffsetInput("0", "0.000000000000"),
            ),
        ),
    )


def _set_factor_definition(
    fixture: JudgmentFixture,
    *,
    status: str = "active",
    scope: str | None = "match",
) -> None:
    with fixture.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE factor_definitions SET status = :status, scope = :scope "
                "WHERE factor_definition_id = 'factor-1'"
            ),
            {"status": status, "scope": scope},
        )


@pytest.mark.parametrize("status", ("probation", "active"))
def test_every_non_retired_factor_lifecycle_state_can_support_judgment(
    tmp_path: Path,
    status: str,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    _set_factor_definition(fixture, status=status)

    judgment_id = _commit_judgment(
        fixture,
        baseline_id,
        envelope_id,
        key=f"judgment:factor-status:{status}",
        expected_revision_no=0,
        rationale=f"Use a {status} Factor without inferring an outcome.",
        factors=_zero_factor("match-1"),
    )
    assert judgment_id


def test_retired_factor_cannot_support_judgment(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    _set_factor_definition(fixture, status="retired")

    with pytest.raises(ValueError, match="retired|inactive|Factor"):
        _commit_judgment(
            fixture,
            baseline_id,
            envelope_id,
            key="judgment:retired-factor",
            expected_revision_no=0,
            rationale="A retired Factor must remain unavailable.",
            factors=_zero_factor("match-1"),
        )


@pytest.mark.parametrize(
    ("scope", "scope_key"),
    (
        ("match", "match-1"),
        ("pairing", "match-1"),
        ("team", "team-stable-1"),
        ("league", "league-stable-1"),
    ),
)
def test_registered_factor_scope_kinds_use_their_explicit_scope_key(
    tmp_path: Path,
    scope: str,
    scope_key: str,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    _set_factor_definition(fixture, scope=scope)

    judgment_id = _commit_judgment(
        fixture,
        baseline_id,
        envelope_id,
        key=f"judgment:factor-scope:{scope}",
        expected_revision_no=0,
        rationale=f"Use the registered {scope} scope.",
        factors=_zero_factor(scope_key),
    )
    assert judgment_id


@pytest.mark.parametrize("scope", (None, "global", "invented"))
def test_unknown_factor_scope_kind_is_rejected(
    tmp_path: Path,
    scope: str | None,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    _set_factor_definition(fixture, scope=scope)

    with pytest.raises(ValueError, match="Factor.*scope|scope.*Factor"):
        _commit_judgment(
            fixture,
            baseline_id,
            envelope_id,
            key=f"judgment:unknown-scope:{scope}",
            expected_revision_no=0,
            rationale="Unknown Factor scope must fail closed.",
            factors=_zero_factor("match-1"),
        )


@pytest.mark.parametrize(
    ("market_state", "expected_error_code"),
    (
        ("stale", "stale_dependency"),
        ("missing", "evidence_missing"),
        ("conflict", "evidence_conflict"),
    ),
)
def test_market_baseline_worker_persists_stable_terminal_error_codes(
    tmp_path: Path,
    market_state: str,
    expected_error_code: str,
) -> None:
    fixture = _fixture(
        tmp_path,
        market_state="complete" if market_state == "stale" else market_state,
    )
    if market_state == "stale":
        _insert_superseding_slate(fixture)
    worker = MarketBaselineWorker(
        action_service=fixture.action_service,
        decision_actions=fixture.decision_actions,
        worker_id=f"baseline-worker-{market_state}",
        lease_duration=timedelta(minutes=5),
        work_item_id_resolver=lambda _revision_id: WORK_ITEM_ID,
    )

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=30)) == ()
    with OntologyUnitOfWork(fixture.engine) as uow:
        job = uow.operator_decision.worker_job_for_source(
            job_kind="market_baseline",
            source_object_type="task_evidence_bundle_revision",
            source_object_id=fixture.task_bundle_revision_id,
        )
    assert job is not None
    assert job.state == "failed"
    assert job.last_error_code == expected_error_code
    with fixture.engine.connect() as connection:
        baseline_count = connection.scalar(
            text("SELECT COUNT(*) FROM operator_market_prior_baseline_revisions")
        )
    assert baseline_count == 0
