from pathlib import Path

import pytest
from sqlalchemy import text

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def test_engine_enables_foreign_keys_wal_and_busy_timeout(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000


def test_unit_of_work_rolls_back_the_whole_transaction(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value TEXT NOT NULL)"))

    with pytest.raises(RuntimeError, match="rollback probe"):
        with OntologyUnitOfWork(engine) as uow:
            uow.connection.execute(text("INSERT INTO probe(value) VALUES ('written')"))
            raise RuntimeError("rollback probe")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one() == 0
