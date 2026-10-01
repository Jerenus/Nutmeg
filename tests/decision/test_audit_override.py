import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


@pytest.fixture(autouse=True)
def _rule_levels_before_diet(monkeypatch):
    """本文件测规则的检测逻辑与 ERROR/WARN 通道机制本身；2026-09-27 规则瘦身按实证
    重定级是另一层（见 test_legs_audit_strength_v2），这里关掉以保持机制可测。"""
    from nutmeg.decision import legs_audit

    monkeypatch.setattr(legs_audit, "EVIDENCE_POLICY", {})

def _payload(*, complete_override: bool = True) -> dict:
    return {
        "issue": "26111",
        "prescription": {"12": "31"},
        "deviation_registry": [{
            "match_no": 12,
            "rule_ids": ["m-单选", "conf", "p-翻车场"],
            "reason": "Jun knowingly rejects the structural insurance findings.",
            "user_override": complete_override,
        }],
        "legs": {"12": {
            "name": "Real Madrid-Real Sociedad",
            "faces": "3",
            "fair": {"home": 0.70, "draw": 0.18, "away": 0.12},
            "confidence": 3,
            "directional_flags": [["anchor_shield_out", "1"]],
            "anchor_integrity": "fail",
        }},
    }


def _setup(tmp_path: Path, *, complete_override: bool = True):
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    legs_file = tmp_path / "26111-legs.json"
    legs_file.write_text(
        json.dumps(_payload(complete_override=complete_override)),
        encoding="utf-8",
    )
    return kernel, data_dir, legs_file


def _invoke(
    data_dir: Path,
    legs_file: Path,
    *,
    override: bool,
    ticket_batch_token: str | None = None,
):
    args = [
        "decision-audit-legs",
        "--legs-file",
        str(legs_file),
        "--data-dir",
        str(data_dir),
    ]
    if override:
        args.append("--user-override")
    if ticket_batch_token is not None:
        args.extend(("--ticket-batch-token", ticket_batch_token))
    return CliRunner().invoke(app, args)


def test_default_audit_keeps_errors_blocking_and_writes_no_adjudication(tmp_path):
    kernel, data_dir, legs_file = _setup(tmp_path)

    result = _invoke(data_dir, legs_file, override=False)

    assert result.exit_code == 1
    assert "flagged_naked_single" in result.stdout
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 0


def test_user_override_writes_one_adjudication_per_error_without_a_token(tmp_path):
    """2026-10-01 前置片：行权只写 Adjudication，不再需要 operator 票批 token。"""
    kernel, data_dir, legs_file = _setup(tmp_path)

    result = _invoke(data_dir, legs_file, override=True)

    assert result.exit_code == 0, result.stdout
    assert "user override 已入账：1 个 ERROR -> 1 条 Adjudication" in result.stdout
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 1
        [adj] = uow.workflow.iter_adjudications()
    assert adj.subject_id == "26111:12" and adj.decision == "evidence_rejected"
    assert adj.evidence_rejected[0]["code"] == "flagged_naked_single"
    assert adj.alternative["rule_ids"] and adj.alternative["faces"] == "3"
    # 同日再跑同一票：幂等，不重复入账
    again = _invoke(data_dir, legs_file, override=True)
    assert again.exit_code == 0
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 1


def test_user_override_with_incomplete_registration_stays_blocked_and_writes_nothing(tmp_path):
    kernel, data_dir, legs_file = _setup(tmp_path, complete_override=False)

    result = _invoke(data_dir, legs_file, override=True)

    assert result.exit_code == 1
    assert "缺完整 override 登记" in result.stdout
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 0


def test_ticket_batch_token_is_accepted_but_ignored(tmp_path):
    kernel, data_dir, legs_file = _setup(tmp_path)

    result = _invoke(data_dir, legs_file, override=True, ticket_batch_token="stale-token")

    assert result.exit_code == 0, result.stdout
    assert "已不再需要" in result.stdout
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 1


def test_user_override_prevalidates_all_matches_before_any_action(tmp_path):
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    payload = _payload(complete_override=False)
    payload["prescription"]["10"] = "31"
    payload["deviation_registry"].append({
        "match_no": 10,
        "rule_ids": ["conf"],
        "reason": "complete earlier override",
        "user_override": True,
    })
    payload["legs"]["10"] = {
        "name": "Home-Away",
        "faces": "3",
        "fair": {"home": 0.60, "draw": 0.25, "away": 0.15},
        "confidence": 3,
    }
    legs_file = tmp_path / "two-match-legs.json"
    legs_file.write_text(json.dumps(payload), encoding="utf-8")

    result = _invoke(data_dir, legs_file, override=True)

    assert result.exit_code == 1
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.workflow.count_adjudications() == 0
