import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, run_migrations
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
        assert uow.rsi.amendments("F2")[0].acted_by == "Jun Zheng"
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


def test_attribution_migration_marks_historical_rows_unattributed(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, MIGRATIONS[:37])
    with engine.begin() as connection:
        for table_name in ("rsi_experiments", "rsi_amendments", "rsi_deployments"):
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DROP COLUMN acted_by")
        connection.exec_driver_sql(
            "INSERT INTO rsi_experiments "
            "(exp_id,claim,mechanism,tier,layer,population,min_tier,window_json,"
            "falsifier_json,stop_rule,quota_slot,buckets_json,rule_ids_json,source_doc,"
            "registered_at,frozen_hash,created_at) VALUES "
            "('F2','c','m','observation','judgment','zucai','price_only','{}','{}','s',"
            "0,'[]','[]','x','2026-09-18','h','2026-09-18')"
        )
        connection.exec_driver_sql(
            "INSERT INTO rsi_amendments "
            "(amendment_id,exp_id,what,why,rule_check,mechanism_note,amended_at) VALUES "
            "('a1','F2','w','y','r',NULL,'2026-09-18')"
        )
        connection.exec_driver_sql(
            "INSERT INTO rsi_deployments "
            "(deployment_id,exp_id,decision,rule_id,reason,adjudication_ref,"
            "extend_to_exp_id,actor_id,decided_at) VALUES "
            "('d1','F2','hold',NULL,'r',NULL,NULL,'operator:rsi','2026-09-18')"
        )

    run_migrations(engine)

    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT acted_by FROM rsi_experiments WHERE exp_id='F2'"
        ).scalar_one() == "unattributed"
        assert connection.exec_driver_sql(
            "SELECT acted_by FROM rsi_amendments WHERE amendment_id='a1'"
        ).scalar_one() == "unattributed"
        assert connection.exec_driver_sql(
            "SELECT acted_by FROM rsi_deployments WHERE deployment_id='d1'"
        ).scalar_one() == "unattributed"
