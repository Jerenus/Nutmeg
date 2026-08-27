from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.workflow.models import PredictionRow, PredictionStatus

AT = "2026-08-27T10:00:00+00:00"


def _engine(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def test_issue_scoped_prediction_row_roundtrip(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.workflow.insert_prediction(
            PredictionRow(
                prediction_id="pred-1",
                match_id=None,
                subject_type="issue",
                subject_id="26111",
                claim="悬置持平4场至少2平",
                falsifier="≤1场平→o条降级",
                status=PredictionStatus.PENDING,
                outcome=None,
                registered_at=AT,
                settled_at=None,
            )
        )
        row = uow.workflow.get_prediction("pred-1")
    assert row.subject_type == "issue" and row.subject_id == "26111"
    assert row.match_id is None


def test_migration_15_is_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run_migrations(engine)  # 二跑无 drift、无异常
    with engine.connect() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(predictions)")}
    assert {"subject_type", "subject_id", "match_id"} <= cols


def test_grade_permission_granted_to_judge_only(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT actor_role FROM action_permissions WHERE action_type='grade_prediction'"
        ).fetchall()
    assert {r[0] for r in rows} == {"judge_operator"}
