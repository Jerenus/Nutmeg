import json
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.analytics.integrity_action import compute_integrity_action_rows
from nutmeg.analytics.scoreboard_projection import compute_scoreboard_metric_rows
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest
from nutmeg.ontology.actions.models import ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import RecordScoreboardObservationRequest
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.storage.duckdb_utils import connect_analytics_db

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
BELIEF = {"home": 0.65, "draw": 0.2, "away": 0.15}


def _seed(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    kernel.forecast_actions.commit_forecast(
        CommitForecastRequest(
            match_id="match-1",
            market_definition_id="md-had",
            decision_session_id=None,
            prior_distribution=PRIOR,
            belief_distribution=BELIEF,
            factors=[],
            commitment_tier="commit",
            evidence_bundle_id=None,
            prior_snapshot_id=None,
            falsifier=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m5:forecast:1",
            requested_at=AT,
        )
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.insert_outcome(
            OutcomeRow(
                outcome_id="outcome-1",
                match_id="match-1",
                version=1,
                score_90="2-0",
                score_aet=None,
                penalties=None,
                status="final",
                source_artifact_retrieval_ids=[],
                recorded_at=AT.isoformat(),
                supersedes_outcome_id=None,
            )
        )
    kernel.scoreboard_actions.record_observation(
        RecordScoreboardObservationRequest(
            group_key="licenses",
            metric_key="named_factor",
            tally="1/1",
            detail="manual governance observation",
            status="active",
            numerator=1.0,
            denominator=1.0,
            value=1.0,
            unit="ratio",
            evidence_refs=[ObjectRef("forecast_revision", "manual-evidence-1")],
            effective_at=AT,
            supersedes_observation_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m5:manual:1",
            requested_at=AT,
        )
    )
    return kernel


def test_scoreboard_projection_keeps_planes_separate_and_reuses_finance_card(
    tmp_path: Path,
) -> None:
    kernel = _seed(tmp_path)
    rows = compute_scoreboard_metric_rows(kernel.engine, as_of=AT.isoformat())
    by_key = {
        (row["plane"], row["group_key"], row["metric_key"]): row for row in rows
    }

    assert {row["plane"] for row in rows} == {
        "forecast",
        "money",
        "intervention",
        "lifecycle",
        "manual",
    }
    finance_card = next(
        row
        for row in compute_integrity_action_rows(kernel.engine)
        if row["scorecard"] == "action_finance"
    )
    finance = json.loads(finance_card["metrics_json"])
    assert by_key[("money", "ledger", "ticket_count")]["value"] == finance[
        "ticket_count"
    ]
    assert by_key[("money", "ledger", "stake_total")]["value"] == finance[
        "stake_total"
    ]
    assert by_key[("manual", "licenses", "named_factor")]["value"] == 1.0
    assert by_key[("manual", "licenses", "named_factor")]["tally"] == "1/1"
    assert by_key[("forecast", "forecast_truth:md-had", "coverage")][
        "denominator"
    ] == 1


def test_calibrate_writes_scoreboard_rows_with_projection_provenance(
    tmp_path: Path,
) -> None:
    kernel = _seed(tmp_path)

    result = kernel.calibrate.build(
        CalibrateRequest(
            as_of=AT.isoformat(),
            built_at="2026-08-24T11:00:00+00:00",
        )
    )

    assert result.status == "succeeded"
    with connect_analytics_db(kernel.paths.analytics) as connection:
        row = connection.execute(
            "SELECT plane, projection_name, projection_version, "
            "source_high_watermark, metric_version FROM scoreboard_metrics "
            "WHERE plane = 'manual' AND group_key = 'licenses'"
        ).fetchone()
    assert row[0] == "manual"
    assert row[1] == "scoreboard"
    assert row[2] == "sb-v1"
    assert row[3] == result.high_watermark
    assert row[4] == "scoring-v1"
