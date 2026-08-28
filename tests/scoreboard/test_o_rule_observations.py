import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.analytics.scoreboard_projection import compute_scoreboard_metric_rows
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import RecordScoreboardObservationRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.scoreboard.authority import ScoreboardAuthorityError, ScoreboardAuthorityService

AT = datetime(2026, 8, 27, 15, 30, tzinfo=UTC)
BUILT_AT = datetime(2026, 8, 27, 15, 40, tzinfo=UTC)
GROUP = "chains"
PARENT_KEY = "suspended_tie_sandwich_o"
CHILD_KEY = "suspended_one_goal_margin_o"


def _observation(
    *,
    metric_key: str,
    tally: str,
    detail: str,
    status: str,
    numerator: float,
    denominator: float,
) -> RecordScoreboardObservationRequest:
    return RecordScoreboardObservationRequest(
        group_key=GROUP,
        metric_key=metric_key,
        tally=tally,
        detail=detail,
        status=status,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator,
        unit="ratio",
        evidence_refs=[ObjectRef("prediction", "prediction-26111-p1")],
        effective_at=AT,
        supersedes_observation_id=None,
        actor_id="operator:jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=f"test:o-rule:{metric_key}",
        requested_at=AT,
    )


def _classification() -> list[dict[str, object]]:
    return [
        {
            "group_key": GROUP,
            "metric_key": PARENT_KEY,
            "classification": "formal_manual",
            "target_ref": f"scoreboard_observation:{GROUP}:{PARENT_KEY}",
        }
    ]


def test_o_rule_subtypes_formalize_parent_without_merging_tallies(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    service = ScoreboardAuthorityService(kernel)
    legacy = tmp_path / "scoreboard.json"
    legacy.write_text(
        json.dumps(
            {
                GROUP: {
                    PARENT_KEY: {
                        "tally": "3/6未赢;持平开平分型2/2→3/6已退休",
                        "status": "retired-subpattern",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    empty = kernel.calibrate.build(
        CalibrateRequest(as_of=AT.isoformat(), built_at=AT.isoformat())
    )

    with pytest.raises(ScoreboardAuthorityError, match="formal manual observation missing"):
        service.shadow(
            legacy_path=legacy,
            classification=_classification(),
            projection_version="sb-v1",
            source_high_watermark=empty.high_watermark,
            acknowledge_manual_source=True,
            requested_at=AT,
        )

    parent = kernel.scoreboard_actions.record_observation(
        _observation(
            metric_key=PARENT_KEY,
            tally="3/6开平",
            detail="持平开平分型在26111 P1 falsifier后退休，与1球差分型分离记账。",
            status="retired",
            numerator=3,
            denominator=6,
        )
    )
    child = kernel.scoreboard_actions.record_observation(
        _observation(
            metric_key=CHILD_KEY,
            tally="5/5分胜负",
            detail="首回合1球差分型累计5/5分胜负，独立保留观察。",
            status="watch",
            numerator=5,
            denominator=5,
        )
    )
    assert parent.status.is_success and child.status.is_success

    rebuilt = kernel.calibrate.build(
        CalibrateRequest(as_of=BUILT_AT.isoformat(), built_at=BUILT_AT.isoformat())
    )
    shadow = service.shadow(
        legacy_path=legacy,
        classification=_classification(),
        projection_version="sb-v1",
        source_high_watermark=rebuilt.high_watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        review = uow.scoreboard.shadow_review(shadow.result_refs[0].object_id)
    assert review is not None
    assert review.manual_count == 1
    assert review.unexplained_count == 0

    rows = compute_scoreboard_metric_rows(kernel.engine, as_of=BUILT_AT.isoformat())
    manual = {
        row["metric_key"]: row
        for row in rows
        if row["plane"] == "manual" and row["group_key"] == GROUP
    }
    assert {
        key: (
            manual[key]["numerator"],
            manual[key]["denominator"],
            manual[key]["value"],
            manual[key]["status"],
        )
        for key in (PARENT_KEY, CHILD_KEY)
    } == {
        PARENT_KEY: (3, 6, 0.5, "retired"),
        CHILD_KEY: (5, 5, 1.0, "watch"),
    }
