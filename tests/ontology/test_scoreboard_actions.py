from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import (
    RecordScoreboardExportRequest,
    RecordScoreboardObservationRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

NOW = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def _legacy_artifact(kernel) -> str:
    outcome = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b'{"chains":{"main":{"tally":"1/1"}}}',
            content_type="application/json",
            source_name="legacy-scoreboard",
            source_type="fixture",
            actor_id="source:m5-test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="m5:legacy-scoreboard",
            retrieved_at=NOW,
        )
    )
    return next(
        ref.object_id
        for ref in outcome.result_refs
        if ref.object_type == "source_artifact"
    )


def _observation(
    *, role: ActorRole = ActorRole.JUDGE_OPERATOR, key: str = "m5:observation"
) -> RecordScoreboardObservationRequest:
    return RecordScoreboardObservationRequest(
        group_key="chains",
        metric_key="main",
        tally="1/1",
        detail="the manually reviewed chain hit",
        status="active",
        numerator=1.0,
        denominator=1.0,
        value=1.0,
        unit="ratio",
        evidence_refs=[ObjectRef("adjudication", "adj-1")],
        effective_at=NOW,
        supersedes_observation_id=None,
        actor_id="operator:jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=NOW,
    )


def test_observation_requires_evidence_and_ai_is_denied(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    with pytest.raises(ValueError, match="evidence_refs cannot be empty"):
        replace(_observation(), evidence_refs=[])

    denied = kernel.scoreboard_actions.record_observation(
        _observation(role=ActorRole.AI_ANALYST, key="m5:observation:denied")
    )

    assert denied.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.scoreboard.count_observations() == 0


def test_observation_is_idempotent_and_revision_must_exist(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    first = kernel.scoreboard_actions.record_observation(_observation())
    replay = kernel.scoreboard_actions.record_observation(_observation())

    assert first.status is ActionStatus.COMMITTED
    assert replay.action_id == first.action_id
    observation_id = first.result_refs[0].object_id
    revised = kernel.scoreboard_actions.record_observation(
        replace(
            _observation(key="m5:observation:revision"),
            tally="2/2",
            numerator=2.0,
            denominator=2.0,
            supersedes_observation_id=observation_id,
        )
    )
    assert revised.status is ActionStatus.COMMITTED

    with pytest.raises(ValueError, match="does not exist"):
        kernel.scoreboard_actions.record_observation(
            replace(
                _observation(key="m5:observation:missing"),
                supersedes_observation_id="sbo-missing",
            )
        )


def test_observation_revision_must_extend_current_chain_and_respects_recorded_as_of(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    first = kernel.scoreboard_actions.record_observation(_observation())
    first_id = first.result_refs[0].object_id

    with pytest.raises(ValueError, match="supersede.*current"):
        kernel.scoreboard_actions.record_observation(
            replace(_observation(key="m5:observation:parallel"), detail="parallel leaf")
        )

    later = datetime(2026, 8, 24, 12, tzinfo=UTC)
    revised = kernel.scoreboard_actions.record_observation(
        replace(
            _observation(key="m5:observation:later"),
            detail="later recorded correction",
            supersedes_observation_id=first_id,
            requested_at=later,
        )
    )
    revised_id = revised.result_refs[0].object_id

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert (
            uow.scoreboard.latest_observations(NOW.isoformat())[
                0
            ].scoreboard_observation_id
            == first_id
        )
        assert (
            uow.scoreboard.latest_observations(later.isoformat())[
                0
            ].scoreboard_observation_id
            == revised_id
        )


def test_export_is_system_only(tmp_path: Path) -> None:
    """record_export 只接系统身份（影子评审 / cutover 动作 2026-10-13 随记分牌权威 CLI 删除）。"""
    kernel = _kernel(tmp_path)
    _legacy_artifact(kernel)
    export = RecordScoreboardExportRequest(
        export_sha256="b" * 64,
        projection_version="sb-v1",
        source_high_watermark=42,
        expected_authority_version=1,
        actor_id="system:scoreboard",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="m5:export:denied",
        requested_at=NOW,
    )
    denied = kernel.scoreboard_actions.record_export(export)
    assert denied.status is ActionStatus.REJECTED
