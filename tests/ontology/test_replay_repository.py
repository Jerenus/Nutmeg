from pathlib import Path

import pytest

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _uow(tmp_path: Path) -> OntologyUnitOfWork:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return OntologyUnitOfWork(engine)


def _running():
    from nutmeg.ontology.repository.replay import HistoricalReplayRunRecord

    return HistoricalReplayRunRecord(
        replay_run_id="replay-20260919-a",
        business_date="2026-09-19",
        source_root_fingerprint="source-fingerprint",
        source_manifest_hash="manifest-hash",
        isolated_database_identity="/isolated/ontology.db",
        schema_version=35,
        status="running",
        started_at="2026-09-20T00:00:00+00:00",
        finished_at=None,
        production_before={"tree": "before"},
        production_after=None,
        report_sha256=None,
        failure_codes=(),
    )


def test_replay_repository_inserts_and_finishes_a_run_once(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    with uow as active:
        active.replay.insert_running(_running())

    with uow as active:
        stored = active.replay.get("replay-20260919-a")
        assert stored == _running()
        active.replay.finish(
            "replay-20260919-a",
            status="accepted",
            finished_at="2026-09-20T00:30:00+00:00",
            production_after={"tree": "before"},
            report_sha256="a" * 64,
            failure_codes=(),
        )

    with uow as active:
        finished = active.replay.get("replay-20260919-a")
        assert finished is not None
        assert finished.status == "accepted"
        assert finished.report_sha256 == "a" * 64
        with pytest.raises(ValueError, match="historical replay run is not active"):
            active.replay.finish(
                "replay-20260919-a",
                status="failed",
                finished_at="2026-09-20T00:31:00+00:00",
                production_after={"tree": "changed"},
                report_sha256="b" * 64,
                failure_codes=("late_failure",),
            )
