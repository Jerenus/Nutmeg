from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.identity.models import ResolutionStatus
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.context import ContextRepository, PersonMatchStatusRow
from nutmeg.ontology.repository.evidence import EvidenceRepository, ObservationRow
from nutmeg.ontology.repository.identity import PersonRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _prepare(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.identity.insert_person(PersonRow(
            person_id="person-1", canonical_name="X", birth_date=None, nationality=None,
            resolution_status=ResolutionStatus.PROVISIONAL,
            created_at=datetime(2026, 7, 21, tzinfo=UTC).isoformat(),
        ))
    return engine


def test_context_and_evidence_rows_persist(tmp_path: Path) -> None:
    engine = _prepare(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        repo_e: EvidenceRepository = uow.evidence
        repo_c: ContextRepository = uow.context
        repo_e.insert_observation(ObservationRow(
            observation_id="obs-1", observation_type="availability", subject_type="person",
            subject_id="person-1", scope_match_id="match-1", value={"availability": "out"},
            schema_version="1", valid_from="2026-07-19T00:00:00+08:00", valid_to=None,
            observed_at="2026-07-19T12:00:00+08:00", recorded_at="2026-07-19T12:05:00+08:00",
            verification_method="official", quality={"source": "club"},
        ), artifact_retrieval_ids=())
        repo_c.insert_person_match_status(PersonMatchStatusRow(
            person_match_status_id="pms-1", match_id="match-1", person_id="person-1",
            team_appearance_id=None, availability="out", status_kind="injury",
            valid_from="2026-07-19T00:00:00+08:00", valid_to=None, observation_id="obs-1",
        ))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.count_observations() == 1
        assert uow.context.person_match_status_ids("match-1") == ("pms-1",)
