from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.permissions import PermissionGuard
from nutmeg.ontology.errors import PermissionDeniedError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations


def test_guard_uses_versioned_database_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.connect() as connection:
        guard = PermissionGuard(connection)
        guard.assert_allowed("governance-v1", "ingest_artifact", ActorRole.CONNECTOR)
        with pytest.raises(PermissionDeniedError, match="ai_analyst.*ingest_artifact"):
            guard.assert_allowed("governance-v1", "ingest_artifact", ActorRole.AI_ANALYST)


def test_unknown_policy_is_denied_not_fallen_back(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.connect() as connection:
        with pytest.raises(PermissionDeniedError, match="unknown-policy"):
            PermissionGuard(connection).assert_allowed(
                "unknown-policy", "ingest_artifact", ActorRole.CONNECTOR
            )
