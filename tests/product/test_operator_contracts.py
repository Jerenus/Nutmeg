from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nutmeg.product.operator_contracts import (
    BusinessEvidenceSummary,
    JudgeMatchesStep,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    PrescriptionDeviationCommand,
    TaskProgressSummary,
)


def test_operator_task_response_is_discriminated_and_business_facing() -> None:
    task = OperatorTaskSummary(
        task_id="zucai:26112",
        lane=OperatorLane.ZUCAI,
        business_key="26112",
        title="足彩 26112",
        state=OperatorTaskState.JUDGE_MATCHES,
        deadline_at=datetime(2026, 8, 29, 3, tzinfo=UTC),
        is_actionable=True,
        next_action_label="裁决 ADJ-1",
        priority_rank=0,
    )
    response = OperatorTaskResponse(
        as_of=datetime(2026, 8, 28, 10, tzinfo=UTC),
        mutation_token="a" * 64,
        selected=task,
        alternatives=[],
        progress=TaskProgressSummary(completed=3, total=14, label="逐场判断"),
        step=JudgeMatchesStep(
            task_id=task.task_id,
            item_key="ADJ-1",
            title="任九档位",
            prompt="选择本期部署档位",
            options=["V288", "R432"],
            evidence=[BusinessEvidenceSummary(label="资金帽", value="¥400")],
        ),
    )

    assert response.step.kind == "judge_matches"
    assert "schema_version" in response.model_dump(mode="json")
    assert "action_id" not in response.model_dump(mode="json")


def test_operator_contracts_forbid_unknown_and_actor_fields() -> None:
    with pytest.raises(ValidationError):
        OperatorTaskSummary.model_validate({
            "task_id": "zucai:26112",
            "lane": "zucai",
            "business_key": "26112",
            "title": "足彩 26112",
            "state": "judge_matches",
            "is_actionable": True,
            "next_action_label": "裁决",
            "priority_rank": 0,
            "actor_role": "ai_analyst",
        })


def test_prescription_deviation_requires_a_named_rule_per_match() -> None:
    valid = PrescriptionDeviationCommand(
        match_no=13,
        rule_ids=["q-两阶段"],
        reason="场 13 从单选改为双选",
    )
    assert valid.match_no == 13
    with pytest.raises(ValidationError):
        PrescriptionDeviationCommand(
            match_no=13,
            rule_ids=[],
            reason="没有命名规则",
        )
