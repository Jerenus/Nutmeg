from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.analytics.intervention_projection import (
    compute_counterfactual_rows,
    compute_intervention_scorecard_rows,
)
from nutmeg.analytics.scoring import brier
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import RecordAdjudicationRequest
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.ontology.workflow.models import (
    FlagInstanceRow,
    PredictionRow,
    PredictionStatus,
)
from nutmeg.storage.duckdb_utils import connect_analytics_db

EARLY = datetime(2026, 8, 24, 10, tzinfo=UTC)
OUTCOME_AT = datetime(2026, 8, 24, 11, tzinfo=UTC)
LATE = datetime(2026, 8, 24, 12, tzinfo=UTC)
DIST = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _seed(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        for match_id in ("match-settled", "match-open"):
            uow.identity.insert_match_minimal(match_id)
        uow.finance.insert_outcome(
            OutcomeRow(
                outcome_id="outcome-1",
                match_id="match-settled",
                version=1,
                score_90="2-1",
                score_aet=None,
                penalties=None,
                status="final",
                source_artifact_retrieval_ids=[],
                recorded_at=OUTCOME_AT.isoformat(),
                supersedes_outcome_id=None,
            )
        )
        uow.workflow.insert_prediction(
            PredictionRow(
                prediction_id="prediction-confirmed",
                match_id="match-settled",
                claim="home will win",
                falsifier="home does not win",
                status=PredictionStatus.CONFIRMED,
                outcome="home",
                registered_at=EARLY.isoformat(),
                settled_at=OUTCOME_AT.isoformat(),
            )
        )
        uow.workflow.insert_prediction(
            PredictionRow(
                prediction_id="prediction-pending",
                match_id="match-open",
                claim="home will win",
                falsifier="home does not win",
                status=PredictionStatus.PENDING,
                outcome=None,
                registered_at=EARLY.isoformat(),
                settled_at=None,
            )
        )
        uow.workflow.insert_flag_instance(
            FlagInstanceRow(
                flag_instance_id="flag-linked",
                flag_type="anchor_shield_out",
                match_id="match-settled",
                direction="draw",
                strength=0.8,
                evidence_refs=[],
                predicted_face="draw",
                status="active",
                created_at=EARLY.isoformat(),
            )
        )
        uow.workflow.insert_flag_instance(
            FlagInstanceRow(
                flag_instance_id="flag-open",
                flag_type="venue_abnormal",
                match_id="match-open",
                direction=None,
                strength=0.5,
                evidence_refs=[],
                predicted_face=None,
                status="active",
                created_at=EARLY.isoformat(),
            )
        )

    def adjudicate(key: str, at: datetime, match_id: str, alternative: dict):
        return kernel.workflow.record_adjudication(
            RecordAdjudicationRequest(
                subject_type="match",
                subject_id=match_id,
                decision="reject",
                reason="registered alternative for review",
                evidence_rejected=[
                    {"object_type": "claim", "object_id": f"claim-{key}"}
                ],
                alternative=alternative,
                supersedes_adjudication_id=None,
                actor_id="operator:jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"m5:adjudication:{key}",
                requested_at=at,
            )
        ).result_refs[0].object_id

    eligible = adjudicate(
        "eligible",
        EARLY,
        "match-settled",
        {
            "counterfactual": {
                "market_definition_id": "md-had",
                "distribution": DIST,
                "label": "keep market prior",
            }
        },
    )
    late = adjudicate(
        "late",
        LATE,
        "match-settled",
        {
            "counterfactual": {
                "market_definition_id": "md-had",
                "distribution": DIST,
                "label": "late alternative",
            }
        },
    )
    invalid = adjudicate(
        "invalid",
        EARLY,
        "match-settled",
        {
            "counterfactual": {
                "market_definition_id": "md-had",
                "distribution": {"home": 0.8, "draw": 0.3, "away": 0.2},
                "label": "invalid alternative",
            }
        },
    )
    missing = adjudicate(
        "missing",
        EARLY,
        "match-open",
        {
            "counterfactual": {
                "market_definition_id": "md-had",
                "distribution": DIST,
                "label": "awaiting outcome",
            }
        },
    )
    extra = adjudicate(
        "extra",
        EARLY,
        "match-settled",
        {
            "counterfactual": {
                "market_definition_id": "md-had",
                "distribution": DIST,
                "label": "shape has an undeclared key",
                "comment": "must not be ignored",
            }
        },
    )
    coerced = adjudicate(
        "coerced",
        EARLY,
        "match-settled",
        {
            "counterfactual": {
                "market_definition_id": "md-had",
                "distribution": {"home": "0.5", "draw": 0.3, "away": 0.2},
                "label": "string probability must not be coerced",
            }
        },
    )
    return kernel, {
        "eligible": eligible,
        "late": late,
        "invalid": invalid,
        "missing": missing,
        "extra": extra,
        "coerced": coerced,
    }


def test_counterfactual_scores_only_preregistered_valid_distribution(
    tmp_path: Path,
) -> None:
    kernel, ids = _seed(tmp_path)
    rows = {row["adjudication_id"]: row for row in compute_counterfactual_rows(kernel.engine)}

    assert rows[ids["eligible"]]["eligibility_code"] == "eligible"
    assert rows[ids["eligible"]]["brier"] == brier(
        DIST, {"home": 1.0, "draw": 0.0, "away": 0.0}
    )
    assert rows[ids["late"]]["eligibility_code"] == "recorded_after_outcome"
    assert rows[ids["invalid"]]["eligibility_code"] == "invalid_distribution"
    assert rows[ids["missing"]]["eligibility_code"] == "missing_outcome"
    assert rows[ids["extra"]]["eligibility_code"] == "invalid_counterfactual"
    assert rows[ids["coerced"]]["eligibility_code"] == "invalid_distribution"
    assert rows[ids["late"]]["brier"] is None


def test_intervention_scorecards_report_counts_and_coverage_before_rates(
    tmp_path: Path,
) -> None:
    kernel, _ids = _seed(tmp_path)
    rows = {
        (row["object_type"], row["metric"]): row
        for row in compute_intervention_scorecard_rows(kernel.engine)
    }

    assert rows[("prediction", "total")]["count"] == 2
    assert rows[("prediction", "settled_coverage")]["numerator"] == 1
    assert rows[("prediction", "settled_coverage")]["denominator"] == 2
    assert rows[("prediction", "confirmed")]["count"] == 1
    assert rows[("flag_instance", "outcome_coverage")]["rate"] == 0.5
    assert rows[("adjudication", "rejected_evidence_coverage")]["rate"] == 1.0
    assert rows[("counterfactual", "eligible_coverage")]["numerator"] == 1
    assert rows[("counterfactual", "eligible_coverage")]["denominator"] == 6


def test_calibrate_registers_intervention_projection(tmp_path: Path) -> None:
    kernel, _ids = _seed(tmp_path)

    result = kernel.calibrate.build(
        CalibrateRequest(
            as_of=LATE.isoformat(),
            built_at="2026-08-24T13:00:00+00:00",
        )
    )

    assert result.status == "succeeded"
    with connect_analytics_db(kernel.paths.analytics) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        eligible = connection.execute(
            "SELECT count(*) FROM counterfactual_replays "
            "WHERE eligibility_code = 'eligible'"
        ).fetchone()[0]
    assert {"intervention_scorecards", "counterfactual_replays"} <= tables
    assert eligible == 1
