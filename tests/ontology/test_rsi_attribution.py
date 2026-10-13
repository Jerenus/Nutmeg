import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.rsi_actions import (
    AmendExperimentRequest,
    ApproveDeploymentRequest,
    RegisterExperimentRequest,
    RsiActions,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository import schema_rsi as sr
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_rsi_actions import F2_DOC

T0 = datetime(2026, 9, 20, 12, tzinfo=UTC)
HUMAN = {"actor_id": "operator:rsi", "actor_role": ActorRole.JUDGE_OPERATOR}
ERROR = "--by 必须是人的标识；这三条动作按 RSI 设计只许人执行"


def _rig(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return RsiActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


@pytest.mark.parametrize(
    "acted_by", ["", " ", "ai", "AI", "claude", "gpt", "codex", "assistant", "system", "auto"]
)
def test_register_rejects_non_human_attribution(tmp_path: Path, acted_by: str):
    actions, _ = _rig(tmp_path)

    with pytest.raises(ValueError, match=ERROR):
        actions.register_experiment(
            RegisterExperimentRequest(
                doc=F2_DOC,
                acted_by=acted_by,
                idempotency_key=f"reg:{acted_by}",
                requested_at=T0,
                **HUMAN,
            )
        )


def test_three_human_actions_persist_acted_by(tmp_path: Path):
    actions, engine = _rig(tmp_path)
    actions.register_experiment(
        RegisterExperimentRequest(
            doc=F2_DOC,
            acted_by="Jun Zheng",
            idempotency_key="reg:F2",
            requested_at=T0,
            **HUMAN,
        )
    )
    actions.amend_experiment(
        AmendExperimentRequest(
            exp_id="F2",
            what="记录采集说明",
            why="审计",
            rule_check="不改冻结字段",
            mechanism_note=None,
            touches={},
            acted_by="Jun Zheng",
            idempotency_key="amend:F2",
            requested_at=T0,
            **HUMAN,
        )
    )
    actions.approve_deployment(
        ApproveDeploymentRequest(
            exp_id="F2",
            decision="hold",
            reason="等待样本",
            rule_id=None,
            adjudication_ref=None,
            extend_to_exp_id=None,
            acted_by="Jun Zheng",
            idempotency_key="hold:F2",
            requested_at=T0,
            **HUMAN,
        )
    )

    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.experiment("F2").acted_by == "Jun Zheng"
        assert uow.connection.execute(
            select(sr.rsi_amendments.c.acted_by).where(sr.rsi_amendments.c.exp_id == "F2")
        ).scalar_one() == "Jun Zheng"
        assert uow.rsi.latest_deployment("F2").acted_by == "Jun Zheng"


def test_amend_and_deploy_reject_non_human_attribution(tmp_path: Path):
    actions, _ = _rig(tmp_path)
    actions.register_experiment(
        RegisterExperimentRequest(
            doc=F2_DOC,
            acted_by="Jun",
            idempotency_key="reg:F2",
            requested_at=T0,
            **HUMAN,
        )
    )

    with pytest.raises(ValueError, match=ERROR):
        actions.amend_experiment(
            AmendExperimentRequest(
                exp_id="F2",
                what="w",
                why="y",
                rule_check="r",
                mechanism_note=None,
                touches={},
                acted_by="assistant",
                idempotency_key="amend:F2",
                requested_at=T0,
                **HUMAN,
            )
        )
    with pytest.raises(ValueError, match=ERROR):
        actions.approve_deployment(
            ApproveDeploymentRequest(
                exp_id="F2",
                decision="hold",
                reason="r",
                rule_id=None,
                adjudication_ref=None,
                extend_to_exp_id=None,
                acted_by="auto",
                idempotency_key="hold:F2",
                requested_at=T0,
                **HUMAN,
            )
        )


def test_register_cli_requires_by_and_rejects_forbidden_value(tmp_path: Path):
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(F2_DOC), encoding="utf-8")
    runner = CliRunner()

    missing = runner.invoke(
        app, ["rsi", "register", str(doc), "--data-dir", str(tmp_path)]
    )
    forbidden = runner.invoke(
        app,
        ["rsi", "register", str(doc), "--by", "Codex", "--data-dir", str(tmp_path)],
    )

    assert missing.exit_code == 2
    assert "--by" in missing.output
    assert forbidden.exit_code == 1
    assert ERROR in forbidden.output
