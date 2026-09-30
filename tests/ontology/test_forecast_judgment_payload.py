"""判断唯一事实 P0（schema 47）：revision 装下整条 Read，按板投影。"""
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect

from nutmeg.ontology.actions.forecast_actions import DraftForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import ForecastRevisionRow
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def test_v47_adds_judgment_payload_columns(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version == 47
    columns = {c["name"] for c in inspect(engine).get_columns("forecast_revisions")}
    assert {"kind", "board_key", "judgment_json"} <= columns


def _row(series_id: str, no: int, **extra) -> ForecastRevisionRow:
    return ForecastRevisionRow(
        forecast_revision_id=f"fr-{series_id}-{no}", forecast_series_id=series_id,
        decision_session_id=None, revision_no=no, status="draft",
        made_at="2026-10-01T10:00:00+08:00", information_cutoff_at=None, prior_snapshot_id=None,
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        belief_distribution={"home": 0.6, "draw": 0.25, "away": 0.15},
        evidence_bundle_id=None, falsifier=None, actor_id="ai:jczq-analyst", model_name=None,
        model_version=None, policy_version="governance-v1", commitment_tier="lean",
        evidence_coverage=None, evidence_quality=None, forecast_stability=None,
        supersedes_revision_id=None, **extra)


def test_board_revisions_round_trip_payload(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-a")
        uow.identity.insert_match_minimal("match-b")
        series = uow.decision.ensure_series("match-a", "md-had")
        uow.decision.insert_revision(_row(series, 1, kind="research", board_key="jczq:2026-10-01",
                                          judgment={"read_id": "R-1", "code": "周四001"}))
        uow.decision.insert_revision(_row(series, 2, kind="override", board_key="jczq:2026-10-01",
                                          judgment={"read_id": "R-2", "code": "周四001"}))
        other = uow.decision.ensure_series("match-b", "md-had")
        uow.decision.insert_revision(_row(other, 1, kind="market", board_key="jczq:2026-10-02"))
    with OntologyUnitOfWork(engine) as uow:
        rows = list(uow.decision.iter_board_revisions("jczq:2026-10-01"))
        latest = uow.decision.latest_revision(series)
        # 老行（迁移前写入）三列为空，读回不炸
        bare = [r.judgment for r in uow.decision.iter_board_revisions("jczq:2026-10-02")]
    assert [(r.revision_no, r.kind, r.judgment["read_id"]) for r in rows] == [
        (1, "research", "R-1"), (2, "override", "R-2")]
    assert rows[0].board_key == "jczq:2026-10-01"
    assert latest is not None and latest.revision_no == 2
    assert bare == [None]


def _req(key: str, **extra) -> DraftForecastRequest:
    return DraftForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id=None,
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        belief_distribution={"home": 0.55, "draw": 0.3, "away": 0.15}, factors=[],
        commitment_tier="lean", evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None,
        actor_id="ai:jczq-analyst", actor_role=ActorRole.AI_ANALYST, idempotency_key=key,
        requested_at=datetime(2026, 10, 1, 2, tzinfo=UTC), **extra)


def test_draft_carries_payload_and_supersedes_previous_draft(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    actions = ForecastActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    first = actions.draft_forecast(_req("read:R-a", kind="research", board_key="jczq:2026-10-01",
                                        judgment={"read_id": "R-a", "note": "研究转录"}))
    second = actions.draft_forecast(_req("read:R-b", kind="override", board_key="jczq:2026-10-01",
                                         judgment={"read_id": "R-b", "note": "主循环改判"}))
    assert first.status is ActionStatus.COMMITTED and second.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        rows = list(uow.decision.iter_board_revisions("jczq:2026-10-01"))
    assert [r.kind for r in rows] == ["research", "override"]
    assert rows[1].supersedes_revision_id == rows[0].forecast_revision_id
    assert rows[1].judgment == {"read_id": "R-b", "note": "主循环改判"}
    assert rows[0].supersedes_revision_id is None
