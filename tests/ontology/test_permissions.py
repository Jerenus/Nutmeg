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


def test_replay_adjudicator_has_only_judgment_chain_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.connect() as connection:
        guard = PermissionGuard(connection)
        for action_type in (
            "request_evidence_freeze",
            "record_baseline_envelope",
            "commit_operator_match_judgment",
            "register_prediction",
            "record_no_ticket",
        ):
            guard.assert_allowed(
                "governance-v1", action_type, ActorRole.REPLAY_ADJUDICATOR
            )
        for action_type in (
            "confirm_ticket_placement",
            "record_cash_transaction",
            "rsi_fulfill_duty",
            "rsi_approve_deployment",
            "approve_jczq_ontology_cutover",
        ):
            with pytest.raises(PermissionDeniedError):
                guard.assert_allowed(
                    "governance-v1", action_type, ActorRole.REPLAY_ADJUDICATOR
                )
