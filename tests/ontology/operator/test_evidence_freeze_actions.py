from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.evidence_actions import (
    EvidenceActions,
    EvidenceFreezeGate,
    EvidenceFreezeMatchPlan,
    LinkTaskEvidenceFreezeRequest,
    RequestEvidenceFreezeRequest,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.operator_decision import OperatorDecisionRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_workers import EvidenceFreezeRequestWorker

AT = datetime(2026, 9, 4, 8, tzinfo=UTC)


def _gate() -> EvidenceFreezeGate:
    return EvidenceFreezeGate(
        task_family_id="jczq:2026-09-04",
        lane="jczq",
        business_key="2026-09-04",
        slate_revision_id="slate-1",
        task_snapshot_hash="a" * 64,
        requirement_revision_token="requirements-1",
        information_cutoff_at=AT,
        policy_version="governance-v1",
        ready=True,
        required_match_count=1,
        matches=(
            EvidenceFreezeMatchPlan(
                match_id="match-1",
                market_snapshot_id=None,
                prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
                candidate_observation_ids=(),
                caveat_claim_ids=(),
                requirement_states=(("E1", "complete"),),
                requirement_ref_tokens=("match-revision-1",),
                market_prior_ref_tokens=(),
                conflicts_cleared_ref_tokens=(),
            ),
        ),
    )


def _seed_slate(engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO source_runs "
            "(source_run_id, source_name, source_type, started_at, finished_at, status) "
            "VALUES ('run-1', 'sporttery', 'official_sale_schedule', ?, ?, 'succeeded')",
            (AT.isoformat(), AT.isoformat()),
        )
        connection.exec_driver_sql(
            "INSERT INTO source_artifacts "
            "(artifact_id, first_recorded_at, content_type, storage_path, byte_size, "
            "content_hash) VALUES ('artifact-1', ?, 'application/json', 'freeze/action', 2, ?)",
            (AT.isoformat(), "f" * 64),
        )
        connection.exec_driver_sql(
            "INSERT INTO artifact_retrievals "
            "(artifact_retrieval_id, artifact_id, source_run_id, source_name, source_type, "
            "reported_content_type, retrieved_at, status) VALUES "
            "('retrieval-1', 'artifact-1', 'run-1', 'sporttery', "
            "'official_sale_schedule', 'application/json', ?, 'stored')",
            (AT.isoformat(),),
        )
        connection.exec_driver_sql("INSERT INTO matches (match_id) VALUES ('match-1')")
        connection.exec_driver_sql(
            "INSERT INTO official_sale_slate_revisions "
            "(slate_revision_id, slate_family_id, lane, business_key, revision_no, "
            "source_artifact_retrieval_id, published_at, retrieved_at, valid_from, "
            "supersedes_slate_revision_id, content_hash) VALUES "
            "('slate-1', 'jczq:2026-09-04', 'jczq', '2026-09-04', 1, 'retrieval-1', "
            "?, ?, ?, NULL, ?)",
            (AT.isoformat(), AT.isoformat(), AT.isoformat(), "e" * 64),
        )


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_slate(engine)
    calls: list[str] = []

    def resolve_gate(_uow, lane: str, business_key: str, as_of: datetime):
        calls.append(f"{lane}:{business_key}:{as_of.isoformat()}")
        return _gate()

    action_service = ActionService(lambda: OntologyUnitOfWork(engine))
    actions = EvidenceActions(
        action_service,
        freeze_gate_resolver=resolve_gate,
    )
    return actions, action_service, engine, calls


def _request(key: str) -> RequestEvidenceFreezeRequest:
    return RequestEvidenceFreezeRequest(
        task_family_id="jczq:2026-09-04",
        lane="jczq",
        business_key="2026-09-04",
        requirement_revision_token="requirements-1",
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=key,
        requested_at=AT,
    )


def test_judge_request_atomically_enqueues_once_and_replay_adds_nothing(
    tmp_path: Path,
) -> None:
    actions, _service, engine, calls = _setup(tmp_path)

    first = actions.request_evidence_freeze(_request("freeze-request:1"))
    replay = actions.request_evidence_freeze(_request("freeze-request:1"))

    assert first.status is ActionStatus.COMMITTED
    assert replay == first
    assert len(calls) == 1  # the first handler re-resolves inside its transaction
    with engine.connect() as connection:
        request_count = connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_freeze_requests)
        )
        jobs = connection.execute(select(sod.operator_worker_jobs)).mappings().all()
    assert request_count == 1
    assert len(jobs) == 1
    assert jobs[0]["job_kind"] == "evidence_freeze"
    assert jobs[0]["state"] == "queued"
    assert jobs[0]["source_object_type"] == "operator_evidence_freeze_request"
    assert first.result_refs[0].object_id == jobs[0]["source_object_id"]


def test_request_rejects_non_judge_without_invoking_the_gate(tmp_path: Path) -> None:
    actions, _service, engine, calls = _setup(tmp_path)
    request = replace(_request("freeze-request:denied"), actor_role=ActorRole.AI_ANALYST)

    outcome = actions.request_evidence_freeze(request)

    assert outcome.status is ActionStatus.REJECTED
    assert calls == []
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_freeze_requests)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_worker_jobs)
        ) == 0


def test_request_rolls_back_when_current_requirement_token_changed(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_slate(engine)

    def changed_gate(_uow, _lane: str, _business_key: str, _as_of: datetime):
        return replace(_gate(), requirement_revision_token="requirements-new")

    actions = EvidenceActions(
        ActionService(lambda: OntologyUnitOfWork(engine)),
        freeze_gate_resolver=changed_gate,
    )

    with pytest.raises(ValueError, match="dependencies changed"):
        actions.request_evidence_freeze(_request("freeze-request:stale"))

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_freeze_requests)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_worker_jobs)
        ) == 0


def test_expired_worker_lease_is_recovered_then_claimed_again(tmp_path: Path) -> None:
    actions, _service, engine, _calls = _setup(tmp_path)
    actions.request_evidence_freeze(_request("freeze-request:lease"))
    expired_at = AT - timedelta(minutes=1)
    with engine.begin() as connection:
        connection.execute(
            update(sod.operator_worker_jobs).values(
                state="leased",
                lease_owner="dead-worker",
                lease_expires_at=expired_at.isoformat(),
                attempt_count=1,
                updated_at=expired_at.isoformat(),
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        repository = OperatorDecisionRepository(uow.connection)
        assert repository.recover_expired_worker_jobs(
            job_kind="evidence_freeze",
            as_of=AT.isoformat(),
        ) == 1
        too_early = repository.claim_worker_jobs(
            job_kind="evidence_freeze",
            lease_owner="worker-2",
            as_of=AT.isoformat(),
            lease_expires_at=(AT + timedelta(minutes=5)).isoformat(),
            limit=1,
        )
        claimed = repository.claim_worker_jobs(
            job_kind="evidence_freeze",
            lease_owner="worker-2",
            as_of=(AT + timedelta(seconds=1)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=5)).isoformat(),
            limit=1,
        )

    assert too_early == ()
    assert len(claimed) == 1
    assert claimed[0].state == "leased"
    assert claimed[0].lease_owner == "worker-2"
    assert claimed[0].attempt_count == 2


def test_expired_worker_lease_backoff_is_capped(tmp_path: Path) -> None:
    actions, _service, engine, _calls = _setup(tmp_path)
    requested = actions.request_evidence_freeze(_request("freeze-request:lease-cap"))
    expired_at = AT - timedelta(minutes=1)
    with engine.begin() as connection:
        connection.execute(
            update(sod.operator_worker_jobs).values(
                state="leased",
                lease_owner="dead-worker",
                lease_expires_at=expired_at.isoformat(),
                attempt_count=10,
                updated_at=expired_at.isoformat(),
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.operator_decision.recover_expired_worker_jobs(
            job_kind="evidence_freeze",
            as_of=AT.isoformat(),
        ) == 1
        job = uow.operator_decision.worker_job_for_source(
            job_kind="evidence_freeze",
            source_object_type="operator_evidence_freeze_request",
            source_object_id=requested.result_refs[0].object_id,
        )

    assert job is not None
    assert datetime.fromisoformat(job.available_at) == AT + timedelta(seconds=300)


def _freeze_one_bundle(service: ActionService, *, key: str = "bundle:1"):
    return BundleActions(service).freeze_bundle(
        FreezeBundleRequest(
            match_id="match-1",
            decision_session_id=None,
            cutoff_at=AT.isoformat(),
            market_snapshot_id=None,
            prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
            candidate_observation_ids=[],
            caveat_claim_ids=[],
            actor_id="operator-evidence-worker",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=key,
            requested_at=AT + timedelta(seconds=1),
        )
    )


def _link_request(
    request_id: str,
    bundle_action_id: str,
    *,
    item_count: int = 1,
    lease_owner: str = "operator-evidence-worker",
) -> LinkTaskEvidenceFreezeRequest:
    return LinkTaskEvidenceFreezeRequest(
        evidence_freeze_request_id=request_id,
        freeze_bundle_action_ids=(bundle_action_id,),
        required_match_count=1,
        bundle_count=1,
        item_count=item_count,
        lease_owner=lease_owner,
        actor_id="operator-evidence-worker",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key=f"link:{request_id}:{item_count}:{lease_owner}",
        requested_at=AT + timedelta(seconds=2),
    )


def _claim_freeze_job(engine, *, owner: str = "operator-evidence-worker") -> None:
    with OntologyUnitOfWork(engine) as uow:
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="evidence_freeze",
            lease_owner=owner,
            as_of=(AT + timedelta(seconds=1)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=5)).isoformat(),
            limit=1,
        )
    assert len(claimed) == 1


def test_link_verifies_exact_bundle_actions_reconciles_counts_and_queues_baseline(
    tmp_path: Path,
) -> None:
    actions, service, engine, _calls = _setup(tmp_path)
    requested = actions.request_evidence_freeze(_request("freeze-request:link"))
    request_id = requested.result_refs[0].object_id
    frozen = _freeze_one_bundle(service)
    _claim_freeze_job(engine)

    linked = actions.link_operator_task_evidence_freeze(
        _link_request(request_id, frozen.action_id)
    )

    assert linked.status is ActionStatus.COMMITTED
    assert linked.result_refs[0].object_type == "task_evidence_bundle_revision"
    revision_id = linked.result_refs[0].object_id
    with engine.connect() as connection:
        revision = connection.execute(
            select(sod.operator_task_evidence_bundle_revisions).where(
                sod.operator_task_evidence_bundle_revisions.c.task_evidence_bundle_revision_id
                == revision_id
            )
        ).mappings().one()
        item = connection.execute(
            select(sod.operator_task_evidence_bundle_items).where(
                sod.operator_task_evidence_bundle_items.c.task_evidence_bundle_revision_id
                == revision_id
            )
        ).mappings().one()
        baseline_jobs = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.job_kind == "market_baseline"
            )
        ).mappings().all()
    assert revision["required_match_count"] == revision["bundle_count"] == 1
    assert revision["item_count"] == 1
    assert item["freeze_bundle_action_id"] == frozen.action_id
    assert len(baseline_jobs) == 1
    assert baseline_jobs[0]["source_object_type"] == "task_evidence_bundle_revision"
    assert baseline_jobs[0]["source_object_id"] == revision_id


@pytest.mark.parametrize("tamper", ["wrong_action", "wrong_count"])
def test_link_rejects_non_bundle_action_or_unreconciled_declared_count(
    tmp_path: Path,
    tamper: str,
) -> None:
    actions, service, engine, _calls = _setup(tmp_path)
    requested = actions.request_evidence_freeze(_request(f"freeze-request:{tamper}"))
    request_id = requested.result_refs[0].object_id
    frozen = _freeze_one_bundle(service, key=f"bundle:{tamper}")
    action_id = requested.action_id if tamper == "wrong_action" else frozen.action_id
    item_count = 1 if tamper == "wrong_action" else 2

    with pytest.raises(ValueError):
        actions.link_operator_task_evidence_freeze(
            _link_request(request_id, action_id, item_count=item_count)
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(
                sod.operator_task_evidence_bundle_revisions
            )
        ) == 0
        assert connection.scalar(
            select(func.count())
            .select_from(sod.operator_worker_jobs)
            .where(sod.operator_worker_jobs.c.job_kind == "market_baseline")
        ) == 0


def test_worker_runs_public_bundle_and_link_actions_then_binds_terminal_job(
    tmp_path: Path,
) -> None:
    actions, service, engine, _calls = _setup(tmp_path)
    requested = actions.request_evidence_freeze(_request("freeze-request:worker"))
    worker = EvidenceFreezeRequestWorker(
        action_service=service,
        evidence_actions=actions,
        bundle_actions=BundleActions(service),
        worker_id="worker-1",
        lease_duration=timedelta(minutes=5),
    )

    outcomes = worker.run_once(limit=1, as_of=AT + timedelta(seconds=10))
    replay = worker.run_once(limit=1, as_of=AT + timedelta(seconds=20))

    assert len(outcomes) == 1
    assert outcomes[0].action_type == "link_operator_task_evidence_freeze"
    assert outcomes[0].status is ActionStatus.COMMITTED
    assert replay == ()
    with engine.connect() as connection:
        source_job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.source_object_id
                == requested.result_refs[0].object_id
            )
        ).mappings().one()
        action_types = tuple(
            connection.execute(
                select(sod.operator_task_evidence_bundle_items.c.freeze_bundle_action_id)
            ).scalars()
        )
    assert source_job["state"] == "completed"
    assert source_job["result_action_id"] == outcomes[0].action_id
    assert source_job["result_object_type"] == "task_evidence_bundle_revision"
    assert source_job["result_object_id"] == outcomes[0].result_refs[0].object_id
    assert len(action_types) == 1


def test_new_evidence_preserves_old_bundle_and_explicit_refreeze_appends_child(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_slate(engine)
    current_gate = {"value": _gate()}

    def resolve_gate(_uow, _lane: str, _business_key: str, _as_of: datetime):
        return current_gate["value"]

    service = ActionService(lambda: OntologyUnitOfWork(engine))
    actions = EvidenceActions(service, freeze_gate_resolver=resolve_gate)
    worker = EvidenceFreezeRequestWorker(
        action_service=service,
        evidence_actions=actions,
        bundle_actions=BundleActions(service),
        worker_id="worker-refreeze",
        lease_duration=timedelta(minutes=5),
    )

    actions.request_evidence_freeze(_request("freeze-request:revision-1"))
    first = worker.run_once(limit=1, as_of=AT + timedelta(seconds=10))[0]
    first_revision_id = first.result_refs[0].object_id
    with engine.connect() as connection:
        first_row_before = connection.execute(
            select(sod.operator_task_evidence_bundle_revisions).where(
                sod.operator_task_evidence_bundle_revisions.c.task_evidence_bundle_revision_id
                == first_revision_id
            )
        ).mappings().one()

    current_gate["value"] = replace(
        _gate(),
        task_snapshot_hash="b" * 64,
        requirement_revision_token="requirements-2",
        matches=(
            replace(
                _gate().matches[0],
                requirement_ref_tokens=("match-revision-2",),
            ),
        ),
    )
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(
                sod.operator_task_evidence_bundle_revisions
            )
        ) == 1

    actions.request_evidence_freeze(
        replace(
            _request("freeze-request:revision-2"),
            requirement_revision_token="requirements-2",
            requested_at=AT + timedelta(seconds=20),
        )
    )
    second = worker.run_once(limit=1, as_of=AT + timedelta(seconds=30))[0]
    second_revision_id = second.result_refs[0].object_id

    with engine.connect() as connection:
        revisions = connection.execute(
            select(sod.operator_task_evidence_bundle_revisions).order_by(
                sod.operator_task_evidence_bundle_revisions.c.revision_no
            )
        ).mappings().all()
        first_row_after = connection.execute(
            select(sod.operator_task_evidence_bundle_revisions).where(
                sod.operator_task_evidence_bundle_revisions.c.task_evidence_bundle_revision_id
                == first_revision_id
            )
        ).mappings().one()
        repository = OperatorDecisionRepository(connection)
        historical = repository.current_task_evidence_bundle_revision(
            "jczq:2026-09-04",
            as_of=(AT + timedelta(seconds=15)).isoformat(),
        )
        current = repository.current_task_evidence_bundle_revision(
            "jczq:2026-09-04",
            as_of=(AT + timedelta(seconds=30)).isoformat(),
        )

    assert len(revisions) == 2
    assert dict(first_row_after) == dict(first_row_before)
    assert revisions[1]["supersedes_revision_id"] == first_revision_id
    assert revisions[1]["task_evidence_bundle_revision_id"] == second_revision_id
    assert historical is not None
    assert historical.task_evidence_bundle_revision_id == first_revision_id
    assert current is not None
    assert current.task_evidence_bundle_revision_id == second_revision_id


def test_link_and_source_job_completion_share_one_action_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, service, engine, _calls = _setup(tmp_path)
    requested = actions.request_evidence_freeze(_request("freeze-request:atomic-link"))
    request_id = requested.result_refs[0].object_id
    frozen = _freeze_one_bundle(service, key="bundle:atomic-link")
    with OntologyUnitOfWork(engine) as uow:
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="evidence_freeze",
            lease_owner="worker-atomic",
            as_of=(AT + timedelta(seconds=1)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=5)).isoformat(),
            limit=1,
        )
    assert len(claimed) == 1

    def fail_completion(self, **_kwargs) -> None:
        raise RuntimeError("forced source-job completion failure")

    monkeypatch.setattr(
        OperatorDecisionRepository,
        "complete_worker_job",
        fail_completion,
    )

    with pytest.raises(RuntimeError, match="forced source-job completion failure"):
        actions.link_operator_task_evidence_freeze(
            _link_request(
                request_id,
                frozen.action_id,
                lease_owner="worker-atomic",
            )
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(
                sod.operator_task_evidence_bundle_revisions
            )
        ) == 0
        assert connection.scalar(
            select(func.count())
            .select_from(sod.operator_worker_jobs)
            .where(sod.operator_worker_jobs.c.job_kind == "market_baseline")
        ) == 0
        source_job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.source_object_id == request_id
            )
        ).mappings().one()
    assert source_job["state"] == "leased"


def test_sqlite_contention_requeues_worker_job_with_bounded_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, service, engine, _calls = _setup(tmp_path)
    requested = actions.request_evidence_freeze(_request("freeze-request:retryable"))
    worker = EvidenceFreezeRequestWorker(
        action_service=service,
        evidence_actions=actions,
        bundle_actions=BundleActions(service),
        worker_id="worker-retry",
        lease_duration=timedelta(minutes=5),
    )

    def locked(*_args, **_kwargs):
        raise OperationalError(
            "worker step",
            {},
            sqlite3.OperationalError("database is locked"),
        )

    monkeypatch.setattr(worker, "process_evidence_freeze_request", locked)

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=10)) == ()

    with engine.connect() as connection:
        job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.source_object_id
                == requested.result_refs[0].object_id
            )
        ).mappings().one()
    assert job["state"] == "queued"
    assert job["lease_owner"] is None
    assert job["last_error_code"] == "sqlite_contention"
    assert datetime.fromisoformat(job["available_at"]) > AT + timedelta(seconds=10)


def test_validation_failure_is_visible_and_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, service, engine, _calls = _setup(tmp_path)
    requested = actions.request_evidence_freeze(_request("freeze-request:terminal"))
    worker = EvidenceFreezeRequestWorker(
        action_service=service,
        evidence_actions=actions,
        bundle_actions=BundleActions(service),
        worker_id="worker-terminal",
        lease_duration=timedelta(minutes=5),
    )

    def invalid(*_args, **_kwargs):
        raise ValueError("evidence gate changed before freeze")

    monkeypatch.setattr(worker, "process_evidence_freeze_request", invalid)

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=10)) == ()

    with engine.connect() as connection:
        job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.source_object_id
                == requested.result_refs[0].object_id
            )
        ).mappings().one()
    assert job["state"] == "failed"
    assert job["last_error_code"] == "invariant_failure"


def test_worker_rechecks_current_gate_at_execution_time(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_slate(engine)
    seen_as_of: list[datetime] = []

    def resolve_gate(_uow, _lane: str, _business_key: str, as_of: datetime):
        seen_as_of.append(as_of)
        if as_of > AT:
            return replace(_gate(), requirement_revision_token="requirements-new")
        return _gate()

    service = ActionService(lambda: OntologyUnitOfWork(engine))
    actions = EvidenceActions(service, freeze_gate_resolver=resolve_gate)
    requested = actions.request_evidence_freeze(_request("freeze-request:execution-time"))
    worker = EvidenceFreezeRequestWorker(
        action_service=service,
        evidence_actions=actions,
        bundle_actions=BundleActions(service),
        worker_id="worker-current-gate",
        lease_duration=timedelta(minutes=5),
    )

    assert worker.run_once(limit=1, as_of=AT + timedelta(seconds=10)) == ()

    with engine.connect() as connection:
        job = connection.execute(
            select(sod.operator_worker_jobs).where(
                sod.operator_worker_jobs.c.source_object_id
                == requested.result_refs[0].object_id
            )
        ).mappings().one()
        freeze_actions = connection.scalar(
            select(func.count())
            .select_from(schema.actions)
            .where(schema.actions.c.action_type == "freeze_evidence_bundle")
        )
    assert seen_as_of == [AT, AT + timedelta(seconds=10)]
    assert job["state"] == "failed"
    assert job["last_error_code"] == "stale_dependency"
    assert freeze_actions == 0


def test_retry_takeover_reuses_bundle_action_across_worker_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, service, engine, _calls = _setup(tmp_path)
    actions.request_evidence_freeze(_request("freeze-request:worker-takeover"))
    first = EvidenceFreezeRequestWorker(
        action_service=service,
        evidence_actions=actions,
        bundle_actions=BundleActions(service),
        worker_id="worker-first",
        lease_duration=timedelta(minutes=5),
    )
    second = EvidenceFreezeRequestWorker(
        action_service=service,
        evidence_actions=actions,
        bundle_actions=BundleActions(service),
        worker_id="worker-second",
        lease_duration=timedelta(minutes=5),
    )
    original_link = actions.link_operator_task_evidence_freeze

    def interrupted_link(*_args, **_kwargs):
        raise OperationalError(
            "worker step",
            {},
            sqlite3.OperationalError("database is locked"),
        )

    monkeypatch.setattr(actions, "link_operator_task_evidence_freeze", interrupted_link)
    assert first.run_once(limit=1, as_of=AT + timedelta(seconds=10)) == ()
    monkeypatch.setattr(actions, "link_operator_task_evidence_freeze", original_link)

    outcomes = second.run_once(limit=1, as_of=AT + timedelta(seconds=12))

    assert len(outcomes) == 1
    assert outcomes[0].status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        committed_bundle_actions = connection.scalar(
            select(func.count())
            .select_from(schema.actions)
            .where(
                schema.actions.c.action_type == "freeze_evidence_bundle",
                schema.actions.c.status == "committed",
            )
        )
    assert committed_bundle_actions == 1
