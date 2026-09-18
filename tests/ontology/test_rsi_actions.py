from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.rsi_actions import (
    AmendExperimentRequest,
    ApproveDeploymentRequest,
    FulfillDutyRequest,
    GradeExperimentRequest,
    RecordVerdictRequest,
    RegisterExperimentRequest,
    RsiActions,
    ScheduleDutiesRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T0 = datetime(2026, 9, 18, 12, tzinfo=UTC)
HUMAN = dict(actor_id="op:jun", actor_role=ActorRole.JUDGE_OPERATOR)
SYSTEM = dict(actor_id="sys:rsi", actor_role=ActorRole.DETERMINISTIC_SYSTEM)

F2_DOC = {
    "exp_id": "F2", "claim": "让球线向主移动 → 主胜残差为正", "mechanism": "改线是承诺",
    "tier": "observation", "layer": "judgment", "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "累计 n≥140 结账，期间不得调阈值", "quota_slot": False,
    "buckets": ["向客 ≤-0.25", "不动 0", "向主 +0.25", "向主 ≥+0.5"], "rule_ids": [],
    "source_doc": "experiments/prereg-26126-F1c-F2.json", "registered_at": "2026-09-14",
    "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
                "instrument": ["python", "scripts/zucai_f2_observe.py", "record",
                               "--issue", "{issue}"],
                "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json",
                "description": "F2 让球线观察单"}],
}


def _rig(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    return RsiActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def test_register_freezes_the_doc_and_generates_duties(tmp_path):
    actions, engine = _rig(tmp_path)
    out = actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    assert out.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        e = uow.rsi.experiment("F2")
        assert e.registered_at == "2026-09-14" and len(e.frozen_hash) == 64
        assert [d.duty_id for d in uow.rsi.duties("F2")] == ["F2:f2-observation"]


def test_register_twice_is_refused_and_system_cannot_register(tmp_path):
    actions, _ = _rig(tmp_path)
    actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    with pytest.raises(ValueError, match="已登记"):
        actions.register_experiment(RegisterExperimentRequest(
            doc=F2_DOC, idempotency_key="reg:F2:again", requested_at=T0, **HUMAN))
    denied = actions.register_experiment(RegisterExperimentRequest(
        doc={**F2_DOC, "exp_id": "F9"}, idempotency_key="reg:F9", requested_at=T0, **SYSTEM))
    assert denied.status is ActionStatus.REJECTED


def test_judgment_layer_deploy_eligible_is_refused_at_register(tmp_path):
    actions, _ = _rig(tmp_path)
    with pytest.raises(ValueError, match="judgment"):
        actions.register_experiment(RegisterExperimentRequest(
            doc={**F2_DOC, "tier": "deploy_eligible"}, idempotency_key="reg:bad",
            requested_at=T0, **HUMAN))


def test_amend_appends_but_refuses_to_touch_frozen_fields(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    ok = actions.amend_experiment(AmendExperimentRequest(
        exp_id="F2", what="F1c 窗改 26129 起", why="采集仪从未接上", rule_check="不改阈值",
        mechanism_note="改线=承诺，改赔率=微调", touches={}, idempotency_key="am:1",
        requested_at=T0, **HUMAN))
    assert ok.status is ActionStatus.COMMITTED
    with pytest.raises(ValueError, match="冻结"):
        actions.amend_experiment(AmendExperimentRequest(
            exp_id="F2", what="放宽阈值", why="差一点", rule_check="—", mechanism_note=None,
            touches={"falsifier": {"threshold_pp": 1.0}}, idempotency_key="am:2",
            requested_at=T0, **HUMAN))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.experiment("F2").falsifier["threshold_pp"] == 2.0   # 原件不变
        assert len(uow.rsi.amendments("F2")) == 1


# ── Task 5: schedule / fulfill ────────────────────────────────────


def _registered(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_experiment(RegisterExperimentRequest(
        doc=F2_DOC, idempotency_key="reg:F2", requested_at=T0, **HUMAN))
    return actions, engine


def test_schedule_creates_one_instance_per_day_duty_and_is_idempotent(tmp_path):
    actions, engine = _registered(tmp_path)
    req = ScheduleDutiesRequest(day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00",
                                issue="26129", idempotency_key="sch:2026-09-19", requested_at=T0)
    assert actions.schedule_duties(req).status is ActionStatus.COMMITTED
    assert actions.schedule_duties(req).status is ActionStatus.COMMITTED   # 幂等重放
    with OntologyUnitOfWork(engine) as uow:
        pend = uow.rsi.pending_duty_instances(day="2026-09-19", now="2026-09-18T20:00:00+08:00")
        assert [(p.duty_id, p.issue, p.due_at) for p in pend] == [
            ("F2:f2-observation", "26129", "2026-09-19T00:30:00+08:00")]


def test_fulfill_marks_instance_and_writes_prospective_observation(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00", issue="26129",
        idempotency_key="sch:1", requested_at=T0))
    out = actions.fulfill_duty(FulfillDutyRequest(
        exp_id="F2", duty_name="f2-observation", day="2026-09-19",
        artifact_path=".nutmeg-data/zucai/26129-f2-observation.json", artifact_bytes=b"{}",
        n_rows=10, population_stratum="zucai", judgment_tier_hist={"price_only": 10},
        captured_at=datetime(2026, 9, 18, 11, 22, 2, tzinfo=UTC),          # 19:22 北京
        earliest_kickoff="2026-09-19T00:30:00+08:00", idempotency_key="ful:1", requested_at=T0))
    assert out.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        inst = uow.rsi.duty_instance("F2:f2-observation", "2026-09-19")
        assert inst.fulfilled_at is not None and len(inst.artifact_hash) == 64
        obs = uow.rsi.observation("F2:2026-09-19")
        assert obs.prospective is True and obs.n_rows == 10
        assert uow.rsi.gaps("F2", now="2026-09-20T00:00:00+08:00") == []


def test_late_artifact_is_recorded_as_not_prospective_and_the_day_stays_a_gap(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00", issue="26129",
        idempotency_key="sch:1", requested_at=T0))
    actions.fulfill_duty(FulfillDutyRequest(
        exp_id="F2", duty_name="f2-observation", day="2026-09-19",
        artifact_path="x.json", artifact_bytes=b"{}", n_rows=10, population_stratum="zucai",
        judgment_tier_hist={"price_only": 10},
        captured_at=datetime(2026, 9, 18, 17, 0, tzinfo=UTC),               # 01:00 北京，开球后
        earliest_kickoff="2026-09-19T00:30:00+08:00", idempotency_key="ful:late", requested_at=T0))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.observation("F2:2026-09-19").prospective is False
        # 前瞻窗过了不算：这一天仍是 gap
        assert uow.rsi.gaps("F2", now="2026-09-20T00:00:00+08:00") == ["2026-09-19"]


# ── Task 6: grade / verdict / deploy ──────────────────────────────


def _grade(exp_id, key, *, mode, n, lo, hi, stratum="zucai", role=ActorRole.DETERMINISTIC_SYSTEM):
    return GradeExperimentRequest(
        exp_id=exp_id, mode=mode, stratum=stratum, n_cum=n, metric_value_pp=(lo + hi) / 2,
        ci_low_pp=lo, ci_high_pp=hi, cost_axis_pp=None, as_of_policy="earliest_kickoff",
        computed_by="tests@deadbeef", inputs_hash="i" * 64, actor_id="sys:rsi", actor_role=role,
        idempotency_key=key, requested_at=T0)


def test_verdict_refuses_before_n_min_and_ignores_replay_grades(tmp_path):
    actions, _ = _registered(tmp_path)
    actions.grade_experiment(_grade("F2", "g:replay", mode="replay", n=300, lo=5.0, hi=9.0))
    with pytest.raises(ValueError, match="prospective"):
        actions.record_verdict(RecordVerdictRequest(
            exp_id="F2", idempotency_key="v:1", requested_at=T0, **SYSTEM))
    actions.grade_experiment(_grade("F2", "g:p1", mode="prospective", n=120, lo=1.0, hi=4.0))
    with pytest.raises(ValueError, match="差 20"):
        actions.record_verdict(RecordVerdictRequest(
            exp_id="F2", idempotency_key="v:2", requested_at=T0, **SYSTEM))


def test_verdict_is_system_only_and_reads_the_ci_bound(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.grade_experiment(_grade("F2", "g:p", mode="prospective", n=140, lo=-3.0, hi=1.9))
    denied = actions.record_verdict(RecordVerdictRequest(
        exp_id="F2", idempotency_key="v:h", requested_at=T0, **HUMAN))
    assert denied.status is ActionStatus.REJECTED                     # 人不能替 falsifier 说话
    ok = actions.record_verdict(RecordVerdictRequest(
        exp_id="F2", idempotency_key="v:s", requested_at=T0, **SYSTEM))
    assert ok.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        v = uow.rsi.latest_verdict("F2")
        assert v.verdict == "falsified" and v.criterion_snapshot["threshold_pp"] == 2.0


def test_both_population_disagreeing_strata_make_pooled_inconclusive(tmp_path):
    actions, engine = _rig(tmp_path)
    doc = {**F2_DOC, "exp_id": "F6", "population": "both",
           "falsifier": {**F2_DOC["falsifier"], "stratum": "pooled"}}
    actions.register_experiment(RegisterExperimentRequest(
        doc=doc, idempotency_key="reg:F6", requested_at=T0, **HUMAN))
    actions.grade_experiment(_grade("F6", "g:z", mode="prospective", n=140, lo=3.0, hi=8.0,
                                    stratum="zucai"))
    actions.grade_experiment(_grade("F6", "g:j", mode="prospective", n=140, lo=-9.0, hi=-4.0,
                                    stratum="jczq"))
    actions.grade_experiment(_grade("F6", "g:p", mode="prospective", n=280, lo=2.5, hi=6.0,
                                    stratum="pooled"))
    actions.record_verdict(RecordVerdictRequest(
        exp_id="F6", idempotency_key="v:6", requested_at=T0, **SYSTEM))
    with OntologyUnitOfWork(engine) as uow:
        # 合并层看似 survived，被分层否决
        assert uow.rsi.latest_verdict("F6").verdict == "inconclusive"


def test_deploy_is_human_only_and_gated_by_layer_tier_and_verdict(tmp_path):
    actions, engine = _rig(tmp_path)
    doc = {**F2_DOC, "exp_id": "S1", "layer": "structural", "tier": "deploy_eligible"}
    actions.register_experiment(RegisterExperimentRequest(
        doc=doc, idempotency_key="reg:S1", requested_at=T0, **HUMAN))
    dep = lambda key, role, decision="deploy": ApproveDeploymentRequest(  # noqa: E731
        exp_id="S1", decision=decision, reason="C11 带定位已由前瞻窗证实", rule_id="C11",
        adjudication_ref=None, extend_to_exp_id=None, idempotency_key=key, requested_at=T0,
        actor_id="sys:rsi" if role is ActorRole.DETERMINISTIC_SYSTEM else "op:jun", actor_role=role)
    with pytest.raises(ValueError, match="survived"):                    # 没判决不能上线
        actions.approve_deployment(dep("d:0", ActorRole.JUDGE_OPERATOR))
    actions.grade_experiment(_grade("S1", "g:s", mode="prospective", n=140, lo=2.5, hi=9.0))
    actions.record_verdict(RecordVerdictRequest(
        exp_id="S1", idempotency_key="v:s1", requested_at=T0, **SYSTEM))
    sys_out = actions.approve_deployment(dep("d:sys", ActorRole.DETERMINISTIC_SYSTEM))
    assert sys_out.status is ActionStatus.REJECTED
    human_out = actions.approve_deployment(dep("d:h", ActorRole.JUDGE_OPERATOR))
    assert human_out.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.latest_deployment("S1").decision == "deploy"


def test_judgment_layer_survived_still_cannot_deploy(tmp_path):
    actions, _ = _registered(tmp_path)                       # F2 是 judgment 层 / observation 档
    actions.grade_experiment(_grade("F2", "g:f2", mode="prospective", n=140, lo=2.5, hi=9.0))
    actions.record_verdict(RecordVerdictRequest(
        exp_id="F2", idempotency_key="v:f2", requested_at=T0, **SYSTEM))
    with pytest.raises(ValueError, match="structural"):
        actions.approve_deployment(ApproveDeploymentRequest(
            exp_id="F2", decision="deploy", reason="想上", rule_id="C11", adjudication_ref=None,
            extend_to_exp_id=None, idempotency_key="d:f2", requested_at=T0, **HUMAN))
