from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.evidence_day import EvidenceDayIngestRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AVAIL = [{"match_no": "周日001", "team": "哈马比", "players": [
    {"name": "Striker A", "provider_id": "P-1", "availability": "out", "status_kind": "injury"}]}]
WEATHER = [{"match_id": "match-preseeded", "value": {"temp_c": 21},
            "valid_from": "2026-07-19T00:00:00+08:00", "observed_at": "2026-07-19T12:00:00+08:00"}]


def test_ingest_evidence_day_records_person_status(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    # a real match (from a prior market-day ingest) the availability rows attach to;
    # here pre-seed a bare match so the person_match_statuses FK holds.
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-preseeded")
    result = kernel.evidence_day_ingest.ingest(EvidenceDayIngestRequest(
        business_date="2026-07-19",
        match_no_to_id={"周日001": "match-preseeded"},
        availability=AVAIL, weather=WEATHER, news=[],
        actor_id="source:api", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    assert result.person_statuses == 1
    assert result.observations == 1   # one weather observation
    status = kernel.status()
    assert status.person_count >= 1
    assert status.observation_count >= 2   # weather + the person-status backing observation


def test_ingest_evidence_day_skips_unmatched_availability(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    result = kernel.evidence_day_ingest.ingest(EvidenceDayIngestRequest(
        business_date="2026-07-19",
        match_no_to_id={},   # no prior market day: nothing to attach to
        availability=AVAIL, weather=[], news=[],
        actor_id="source:api", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    assert result.person_statuses == 0
    assert result.skipped == 1   # counted, never silently dropped
