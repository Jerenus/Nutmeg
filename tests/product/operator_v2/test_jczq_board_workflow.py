from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.repository import schema
from nutmeg.product.jczq_board_workflow import (
    JczqBoard,
    JczqBoardMatch,
    JczqBoardWorkflow,
    JczqForecastDraft,
    JczqResearchArtifact,
)
from tests.ontology.operator.test_judgment_actions import _fixture

AT = datetime(2026, 9, 19, 8, tzinfo=UTC)


class _R0Recorder:
    def __init__(self) -> None:
        self.matches: list[str] = []

    def fulfill(self, match_id: str) -> None:
        self.matches.append(match_id)


class _ProposalWriter:
    def __init__(self) -> None:
        self.requests = []

    def create_agent_proposal(self, request):
        self.requests.append(request)
        return request


def _board(count: int) -> JczqBoard:
    return JczqBoard(
        business_date="2026-09-19",
        matches=tuple(
            JczqBoardMatch(
                match_id=f"match-{index}",
                official_match_no=f"{index:03d}",
                kickoff_at=AT + timedelta(hours=10),
            )
            for index in range(1, count + 1)
        ),
    )


def _seed_artifacts(fixture, artifacts) -> None:
    with fixture.engine.begin() as connection:
        for index, artifact in enumerate(artifacts, start=1):
            connection.execute(
                insert(schema.source_runs).values(
                    source_run_id=artifact.source_run_id,
                    source_name="jczq_research",
                    source_type="credible_media",
                    started_at=artifact.captured_at.isoformat(),
                    finished_at=artifact.captured_at.isoformat(),
                    status="succeeded",
                    error_code=None,
                    error_detail=None,
                )
            )
            connection.execute(
                insert(schema.source_artifacts).values(
                    artifact_id=artifact.artifact_id,
                    first_recorded_at=artifact.captured_at.isoformat(),
                    content_type="application/json",
                    storage_path=f"artifacts/{artifact.artifact_id}.json",
                    byte_size=1,
                    content_hash=f"{index:064x}",
                )
            )


def test_board_persists_one_explicit_research_terminal_state_per_match(
    tmp_path,
) -> None:
    fixture = _fixture(tmp_path)
    r0 = _R0Recorder()
    workflow = JczqBoardWorkflow(
        fixture.action_service,
        r0_recorder=r0,
    )
    board = _board(30)
    artifacts = tuple(
        JczqResearchArtifact(
            match_id=f"match-{index}",
            captured_at=AT,
            source_run_id=f"board-run-{index}",
            artifact_id=f"board-artifact-{index}",
            intake_errors=(() if index <= 25 else ("invalid",)),
        )
        for index in range(1, 28)
    )
    _seed_artifacts(fixture, artifacts)

    result = workflow.intake_board(board, artifacts, historical_replay=False)
    progress = workflow.progress("2026-09-19")

    assert result.total == 30
    assert (result.researched, result.rejected, result.price_only) == (25, 2, 3)
    assert progress == result
    assert len(r0.matches) == 25


def test_post_kickoff_artifact_cannot_create_prospective_forecast(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    writer = _ProposalWriter()
    workflow = JczqBoardWorkflow(
        fixture.action_service,
        proposal_writer=writer,
    )
    draft = JczqForecastDraft(
        match_id="match-1",
        information_cutoff_at=AT + timedelta(hours=11),
        kickoff_at=AT + timedelta(hours=10),
        payload={"prior": {"3": "0.500000000000"}},
        citation_refs=(),
        origin="ai:jczq-analyst",
    )

    with pytest.raises(ValueError, match="post-kickoff evidence cannot be prospective"):
        workflow.propose_forecasts((draft,), historical_replay=False)

    assert writer.requests == []


def test_rejected_intake_never_records_r0_fulfillment(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    r0 = _R0Recorder()
    workflow = JczqBoardWorkflow(fixture.action_service, r0_recorder=r0)
    board = _board(1)
    artifacts = (
        JczqResearchArtifact(
            match_id="match-1",
            captured_at=AT,
            source_run_id="board-run-1",
            artifact_id="board-artifact-1",
            intake_errors=("invalid",),
        ),
    )
    _seed_artifacts(fixture, artifacts)

    workflow.intake_board(
        board,
        artifacts,
        historical_replay=False,
        actor_id="system:jczq-board",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
    )

    assert r0.matches == []


def test_board_action_replay_does_not_duplicate_r0_fulfillment(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    r0 = _R0Recorder()
    workflow = JczqBoardWorkflow(fixture.action_service, r0_recorder=r0)
    board = _board(1)
    artifacts = (
        JczqResearchArtifact(
            match_id="match-1",
            captured_at=AT,
            source_run_id="board-run-1",
            artifact_id="board-artifact-1",
        ),
    )
    _seed_artifacts(fixture, artifacts)

    first = workflow.intake_board(board, artifacts, historical_replay=False)
    replay = workflow.intake_board(board, artifacts, historical_replay=False)

    assert first == replay
    assert r0.matches == ["match-1"]
