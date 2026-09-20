import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import insert, select

from nutmeg.ontology.actions.service import ActionService, ReplayActionContext
from nutmeg.ontology.evidence.models import VerificationMethod
from nutmeg.ontology.repository import schema, schema_decision, schema_workflow
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.replay import HistoricalReplayRunRecord
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.jczq_replay_adjudication import (
    ReplayAdjudicationInput,
    ReplayAdjudicator,
)


def _setup(tmp_path: Path):
    database = (tmp_path / "ontology.db").resolve()
    engine = build_ontology_engine(database)
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.replay.insert_running(
            HistoricalReplayRunRecord(
                replay_run_id="run-1", business_date="2026-09-19",
                source_root_fingerprint="source", source_manifest_hash="manifest",
                isolated_database_identity=str(database), schema_version=35,
                status="running", started_at="2026-09-20T00:00:00+00:00",
                finished_at=None, production_before={}, production_after=None,
                report_sha256=None, failure_codes=(),
            )
        )
        for index in range(1, 4):
            match_id = f"match-{index}"
            uow.identity.insert_match_minimal(match_id)
            source_run_id = f"source-{index}"
            artifact_id = f"artifact-{index}"
            retrieval_id = f"retrieval-{index}"
            observation_id = f"observation-{index}"
            uow.connection.execute(insert(schema.source_runs).values(
                source_run_id=source_run_id, source_name="replay", source_type="media",
                started_at="2026-09-19T04:00:00+00:00",
                finished_at="2026-09-19T04:00:00+00:00", status="succeeded",
                error_code=None, error_detail=None,
            ))
            uow.connection.execute(insert(schema.source_artifacts).values(
                artifact_id=artifact_id, first_recorded_at="2026-09-19T04:00:00+00:00",
                content_type="application/json", storage_path=f"research/{index}.json",
                byte_size=2, content_hash=f"{index:064x}",
            ))
            uow.connection.execute(insert(schema.artifact_retrievals).values(
                artifact_retrieval_id=retrieval_id, artifact_id=artifact_id,
                source_run_id=source_run_id, source_name="replay", source_type="media",
                reported_content_type="application/json", canonical_url=None,
                requested_url=None, published_at="2026-09-19T04:00:00+00:00",
                retrieved_at="2026-09-19T04:00:00+00:00", status="stored",
            ))
            uow.evidence.insert_observation(ObservationRow(
                observation_id=observation_id, observation_type="replay_research",
                subject_type="match", subject_id=match_id, scope_match_id=match_id,
                value={"draft": True}, schema_version="1",
                valid_from="2026-09-19T04:00:00+00:00", valid_to=None,
                observed_at="2026-09-19T04:00:00+00:00",
                recorded_at="2026-09-19T04:00:00+00:00",
                verification_method=VerificationMethod.CORROBORATED.value, quality={},
            ), (retrieval_id,))
            uow.market.insert_snapshot(SnapshotRow(
                market_snapshot_id=f"snapshot-{index}", match_id=match_id,
                market_definition_id="md-had", snapshot_kind="replay_cutoff",
                as_of="2026-09-19T05:00:00+00:00",
                fair_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
                devig_method="proportional", method_version="1",
                source_coverage={"providers": 1}, freshness={}, disagreement={},
            ))
    service = ActionService(
        lambda: OntologyUnitOfWork(engine),
        replay_context=ReplayActionContext("run-1", "2026-09-19", str(database)),
    )
    return ReplayAdjudicator(service, replay_run_id="run-1"), engine


def _input(index: int, branch: str) -> ReplayAdjudicationInput:
    return ReplayAdjudicationInput(
        read_id=f"read-{index}", match_id=f"match-{index}",
        made_at=datetime(2026, 9, 19, 6, tzinfo=UTC), origin="ai-read",
        branch=branch, reason=f"fixture-{branch}", market_definition_id="md-had",
        market_snapshot_id=f"snapshot-{index}",
        prior_distribution={"home": 0.4, "draw": 0.3, "away": 0.3},
        belief_distribution={"home": 0.5, "draw": 0.25, "away": 0.25},
        revised_belief_distribution={"home": 0.45, "draw": 0.3, "away": 0.25},
        citation_refs=({"object_type": "observation", "object_id": f"observation-{index}"},),
        candidate_observation_ids=(f"observation-{index}",),
    )


def test_replay_adjudication_exercises_all_branches_and_commits_forecasts(tmp_path: Path):
    adjudicator, engine = _setup(tmp_path)
    results = adjudicator.adjudicate(
        (_input(1, "approve"), _input(2, "revise"), _input(3, "reject"))
    )

    assert [result.branch for result in results] == ["approve", "revise", "reject"]
    assert results[0].original_proposal_id == results[0].committed_proposal_id
    assert results[1].original_proposal_id != results[1].committed_proposal_id
    assert results[2].original_proposal_id != results[2].committed_proposal_id
    assert all(result.forecast_revision_id for result in results)

    with engine.connect() as connection:
        proposals = connection.execute(select(schema_workflow.agent_proposals)).mappings().all()
        adjudications = connection.execute(select(schema_workflow.adjudications)).mappings().all()
        actions = connection.execute(select(schema.actions)).mappings().all()
        forecast_count = connection.execute(select(schema_decision.forecast_revisions)).all()
        lineage_count = connection.exec_driver_sql("""
            SELECT COUNT(DISTINCT eb.evidence_bundle_id)
            FROM evidence_bundle_items eb
            JOIN observation_sources os ON os.observation_id = eb.observation_id
            JOIN artifact_retrievals ar ON ar.artifact_retrieval_id = os.artifact_retrieval_id
            JOIN source_artifacts sa ON sa.artifact_id = ar.artifact_id
            JOIN source_runs sr ON sr.source_run_id = ar.source_run_id
        """).scalar_one()

    assert len(proposals) == 5
    assert all(json.loads(row["payload_json"])["status"] == "draft" for row in proposals)
    assert {row["decision"] for row in adjudications} >= {"approve", "revise", "reject"}
    assert len(forecast_count) == 3
    assert lineage_count == 3
    replay_actions = [row for row in actions if row["action_type"] != "start_historical_replay"]
    assert replay_actions
    assert {row["replay_run_id"] for row in replay_actions} == {"run-1"}
    assert all(row["historical_replay"] == 1 for row in replay_actions)
    assert {
        row["actor_id"] for row in replay_actions
        if row["action_type"] in {"create_agent_proposal", "record_adjudication", "commit_forecast"}
    } == {"replay:run-1:adjudicator"}
