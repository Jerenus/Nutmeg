from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActionStatus, ObjectRef
from nutmeg.ontology.actions.replay_actions import (
    FinishHistoricalReplayRequest,
    ReplayActions,
    StartHistoricalReplayRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path) -> tuple[ReplayActions, object, str]:
    database = (tmp_path / "isolated" / "ontology.db").resolve()
    engine = build_ontology_engine(database)
    run_migrations(engine)
    return (
        ReplayActions(ActionService(lambda: OntologyUnitOfWork(engine))),
        engine,
        str(database),
    )


def _start(database: str, **overrides) -> StartHistoricalReplayRequest:
    values = {
        "replay_run_id": "replay-20260919-a",
        "business_date": "2026-09-19",
        "source_root_fingerprint": "source",
        "source_manifest_hash": "manifest",
        "isolated_database_identity": database,
        "production_database_identity": str(Path(database).parent / "production.db"),
        "schema_version": 35,
        "production_before": {"tree": "before"},
        "idempotency_key": "replay:start:20260919:a",
        "requested_at": datetime(2026, 9, 20, tzinfo=UTC),
    }
    values.update(overrides)
    return StartHistoricalReplayRequest(**values)


def _finish(database: str, **overrides) -> FinishHistoricalReplayRequest:
    values = {
        "replay_run_id": "replay-20260919-a",
        "business_date": "2026-09-19",
        "isolated_database_identity": database,
        "status": "accepted",
        "production_after": {"tree": "before"},
        "report_sha256": "a" * 64,
        "failure_codes": (),
        "idempotency_key": "replay:finish:20260919:a",
        "requested_at": datetime(2026, 9, 20, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return FinishHistoricalReplayRequest(**values)


def test_start_is_idempotent_and_returns_replay_run_ref(tmp_path: Path) -> None:
    actions, _engine, database = _actions(tmp_path)
    first = actions.start(_start(database))
    second = actions.start(_start(database))
    assert first.status is ActionStatus.COMMITTED
    assert second.action_id == first.action_id
    assert first.result_refs == (ObjectRef("historical_replay_run", "replay-20260919-a"),)


def test_start_rejects_identity_conflict_and_production_database_path(
    tmp_path: Path,
) -> None:
    actions, _engine, database = _actions(tmp_path)
    actions.start(_start(database))
    with pytest.raises(ValueError, match="identity conflict"):
        actions.start(
            _start(
                database,
                source_manifest_hash="changed",
                idempotency_key="replay:start:conflict",
            )
        )
    with pytest.raises(ValueError, match="isolated ontology path equals production"):
        actions.start(
            _start(
                database,
                replay_run_id="replay-production",
                isolated_database_identity=database,
                production_database_identity=database,
                idempotency_key="replay:start:production",
            )
        )


@pytest.mark.parametrize(
    ("status", "failure_codes"),
    [("accepted", ()), ("failed", ("result_coverage_gap",))],
)
def test_finish_transitions_once_and_is_replay_stamped(
    tmp_path: Path, status: str, failure_codes: tuple[str, ...]
) -> None:
    actions, engine, database = _actions(tmp_path)
    actions.start(_start(database))
    outcome = actions.finish(
        _finish(database, status=status, failure_codes=failure_codes)
    )
    assert outcome.status is ActionStatus.COMMITTED
    assert outcome.result_refs == (
        ObjectRef("historical_replay_run", "replay-20260919-a"),
    )
    with OntologyUnitOfWork(engine) as uow:
        run = uow.replay.get("replay-20260919-a")
        action = uow.actions.get_by_idempotency_key("replay:finish:20260919:a")
    assert run is not None and run.status == status
    assert action is not None and action.historical_replay
    assert action.replay_run_id == "replay-20260919-a"


def test_finish_rejects_second_terminal_transition(tmp_path: Path) -> None:
    actions, _engine, database = _actions(tmp_path)
    actions.start(_start(database))
    actions.finish(_finish(database))
    with pytest.raises(ValueError, match="not active"):
        actions.finish(
            _finish(
                database,
                status="failed",
                failure_codes=("late",),
                idempotency_key="replay:finish:late",
            )
        )
