from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.high_watermark import high_watermark
from nutmeg.ontology.actions.models import ActionCommand, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def test_watermark_monotonic(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    before = high_watermark(engine)
    ActionService(lambda: OntologyUnitOfWork(engine)).execute(
        ActionCommand.create(
            action_type="ingest_artifact", actor_id="source:test",
            actor_role=ActorRole.CONNECTOR, idempotency_key="hw:1", payload={},
            requested_at=datetime(2026, 7, 19, tzinfo=UTC)),
        lambda _uow, _command: ())
    assert high_watermark(engine) > before


def test_analytics_path(tmp_path: Path) -> None:
    paths = OntologyPaths.from_data_dir(tmp_path)
    assert paths.analytics == tmp_path / "ontology" / "analytics.duckdb"
