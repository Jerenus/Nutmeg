import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

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
from nutmeg.ontology.repository import schema_rsi as sr
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T0 = datetime(2026, 9, 18, 12, tzinfo=UTC)
HUMAN = dict(actor_id="op:jun", actor_role=ActorRole.JUDGE_OPERATOR, acted_by="Jun")
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
        doc={**F2_DOC, "exp_id": "F9"}, acted_by="system",
        idempotency_key="reg:F9", requested_at=T0, **SYSTEM))
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
        assert uow.connection.execute(
            select(func.count()).select_from(sr.rsi_amendments)
            .where(sr.rsi_amendments.c.exp_id == "F2")).scalar_one() == 1


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
        pend = uow.rsi.duty_instances_for_day("F2:f2-observation", "2026-09-19")
        assert [(p.duty_id, p.issue, p.due_at, p.fulfilled_at) for p in pend] == [
            ("F2:f2-observation", "26129", "2026-09-19T00:30:00+08:00", None)]


def test_issue_schedule_binds_the_day_row_left_issueless_by_the_jczq_schedule(tmp_path):
    # 2026-09-24：同日先按竞彩排（issue=None、截止=竞彩最早开球 18:05）再按 26132 排，
    # 第二次看到行已存在就跳过 → F4 整天 issue=NULL，sweep 报「当天没有足彩期」。
    actions, engine = _registered(tmp_path)
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T18:05:00+08:00", issue=None,
        idempotency_key="sch:jczq", requested_at=T0))
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T19:35:00+08:00", issue="26129",
        idempotency_key="sch:26129", requested_at=T0))
    with OntologyUnitOfWork(engine) as uow:
        row = uow.rsi.duty_instance("F2:f2-observation", "2026-09-19")
        assert (row.issue, row.due_at) == ("26129", "2026-09-19T19:35:00+08:00")


def test_schedule_keeps_manual_duties_scheduled(tmp_path):
    actions, engine = _rig(tmp_path)
    doc = {**F2_DOC, "exp_id": "F4",
           "duties": [{**F2_DOC["duties"][0], "name": "capital-plan", "status": "manual"}]}
    actions.register_experiment(RegisterExperimentRequest(
        doc=doc, idempotency_key="reg:F4", requested_at=T0, **HUMAN))
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00", issue="26129",
        idempotency_key="sch:F4", requested_at=T0))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.duty_instance("F4:capital-plan", "2026-09-19") is not None
        assert uow.rsi.duties("F4")[0].status == "manual"


def test_schedule_skips_pending_instrument_duties(tmp_path):
    actions, engine = _rig(tmp_path)
    doc = {
        **F2_DOC,
        "exp_id": "F5",
        "duties": [
            {
                **F2_DOC["duties"][0],
                "name": "price-band-observation",
                "status": "pending_instrument",
                "instrument": ["TODO"],
            }
        ],
    }
    actions.register_experiment(
        RegisterExperimentRequest(
            doc=doc, idempotency_key="reg:F5", requested_at=T0, **HUMAN
        )
    )

    actions.schedule_duties(
        ScheduleDutiesRequest(
            day="2026-09-19",
            earliest_kickoff="2026-09-19T00:30:00+08:00",
            issue="26129",
            idempotency_key="sch:F5",
            requested_at=T0,
        )
    )

    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.duty_instance("F5:price-band-observation", "2026-09-19") is None
        assert uow.rsi.duties("F5")[0].status == "pending_instrument"


def test_schedule_skips_an_issue_before_the_experiment_window(tmp_path):
    actions, engine = _rig(tmp_path)
    doc = {
        **F2_DOC,
        "exp_id": "F4",
        "layer": "structural",
        "window": {"issue_from": "26129", "issue_to": "26140"},
        "duties": [
            {
                "name": "capital-plan",
                "scope": "day",
                "deadline_rule": "earliest_kickoff",
                "instrument": ["nutmeg", "plan", "commit"],
                "artifact_glob": "{issue}-capital-plan.txt",
            }
        ],
    }
    actions.register_experiment(
        RegisterExperimentRequest(
            doc=doc, idempotency_key="reg:F4", requested_at=T0, **HUMAN
        )
    )
    actions.schedule_duties(
        ScheduleDutiesRequest(
            day="2026-09-14",
            earliest_kickoff="2026-09-14T18:00:00+08:00",
            issue="26125",
            idempotency_key="sch:26125",
            requested_at=T0,
        )
    )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.duty_instance("F4:capital-plan", "2026-09-14") is None


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
        exp_id="F2", idempotency_key="v:h", requested_at=T0,
        actor_id="op:jun", actor_role=ActorRole.JUDGE_OPERATOR))
    assert denied.status is ActionStatus.REJECTED                     # 人不能替 falsifier 说话
    ok = actions.record_verdict(RecordVerdictRequest(
        exp_id="F2", idempotency_key="v:s", requested_at=T0, **SYSTEM))
    assert ok.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        v = uow.rsi.latest_verdict("F2")
        assert v.verdict == "falsified" and v.criterion_snapshot["threshold_pp"] == 2.0


def _grade_at(exp_id, key, *, n, lo, hi, at, stratum="zucai"):
    return GradeExperimentRequest(
        exp_id=exp_id, mode="prospective", stratum=stratum, n_cum=n,
        metric_value_pp=(lo + hi) / 2, ci_low_pp=lo, ci_high_pp=hi, cost_axis_pp=None,
        as_of_policy="registry_window_date", computed_by="tests@v2", inputs_hash=key * 8,
        idempotency_key=key, requested_at=at, **SYSTEM)


def test_verdict_v2_judges_once_on_the_first_grade_that_reached_n_min(tmp_path):
    # 2026-10-19 Jun「冻结原文为准」：F14「累计 60 场结账；CI 下界 ≤0 即证伪」——首次够数
    # n=77 CI[−3.61,+14.05] 就是结账那一份；之后 n=132 下界 +0.49 不再改判（可选停止）
    actions, engine = _rig(tmp_path)
    doc = {**F2_DOC, "exp_id": "F14", "population": "both", "window": {"date_from": "2026-10-01"},
           "falsifier": {"metric": "stance_faces_resid_pp", "stratum": "pooled", "n_min": 60,
                         "bound": "ci_lower", "threshold_pp": 0.0,
                         "direction": "lt_means_falsified"}}
    actions.register_experiment(RegisterExperimentRequest(
        doc=doc, idempotency_key="reg:F14", requested_at=T0, **HUMAN))
    day = lambda d: datetime(2026, 10, d, 2, 45, tzinfo=UTC)  # noqa: E731
    actions.grade_experiment(_grade_at("F14", "g1", n=40, lo=-9.0, hi=20.0, at=day(10),
                                       stratum="pooled"))
    actions.grade_experiment(_grade_at("F14", "g2", n=77, lo=-3.61, hi=14.05, at=day(12),
                                       stratum="pooled"))
    actions.grade_experiment(_grade_at("F14", "g3", n=132, lo=0.49, hi=13.75, at=day(16),
                                       stratum="pooled"))
    actions.record_verdict(RecordVerdictRequest(
        exp_id="F14", idempotency_key="v:once", requested_at=day(19), **SYSTEM))
    with OntologyUnitOfWork(engine) as uow:
        v = uow.rsi.latest_verdict("F14")
        settled = uow.rsi.grade(v.grade_id)
    assert v.verdict == "falsified" and settled.n_cum == 77
    assert v.criterion_snapshot["protocol"] == "v2-frozen-text"
    assert v.criterion_snapshot["settlement_n"] == 77
    with pytest.raises(ValueError, match="已结账"):
        actions.record_verdict(RecordVerdictRequest(
            exp_id="F14", idempotency_key="v:twice", requested_at=day(20), **SYSTEM))


def test_verdict_v2_supersedes_legacy_daily_verdict_rows(tmp_path):
    actions, engine = _registered(tmp_path)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    actions.grade_experiment(_grade_at("F2", "g:a", n=140, lo=2.5, hi=9.0, at=at))
    with OntologyUnitOfWork(engine) as uow:          # 旧协议留下的一行（快照不带 protocol）
        from nutmeg.ontology.repository.rsi import VerdictRow

        g = uow.rsi.latest_grade("F2", mode="prospective", stratum="zucai")
        uow.rsi.insert_verdict(VerdictRow(
            verdict_id="rsiv-legacy", exp_id="F2", verdict="inconclusive", grade_id=g.grade_id,
            criterion_snapshot=dict(F2_DOC["falsifier"]), decided_at="2026-10-02T10:45:00+08:00"))
    actions.record_verdict(RecordVerdictRequest(
        exp_id="F2", idempotency_key="v:v2", requested_at=datetime(2026, 10, 19, tzinfo=UTC),
        **SYSTEM))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.latest_verdict("F2").verdict == "survived"
        assert len(uow.rsi.verdicts("F2")) == 2


def test_window_end_without_n_min_settles_once_as_expired(tmp_path):
    """2026-10-19：新登记带 date_to——截止仍未够数＝到期，判一次 inconclusive 并标 expired。"""
    actions, engine = _rig(tmp_path)
    doc = {**F2_DOC, "exp_id": "F14b", "window": {"date_from": "2026-10-20", "n_min": 120,
                                                  "date_to": "2026-12-31"},
           "falsifier": {"metric": "m", "stratum": "pooled", "n_min": 120, "bound": "ci_lower",
                         "threshold_pp": 0.0, "direction": "lt_means_falsified"}}
    actions.register_experiment(RegisterExperimentRequest(
        doc=doc, idempotency_key="reg:F14b", requested_at=T0, **HUMAN))
    actions.grade_experiment(_grade_at("F14b", "gx", n=90, lo=-2.0, hi=9.0,
                                       at=datetime(2026, 12, 30, tzinfo=UTC), stratum="pooled"))
    with pytest.raises(ValueError, match="未到期"):
        actions.record_verdict(RecordVerdictRequest(
            exp_id="F14b", idempotency_key="v:dec", requested_at=datetime(2026, 12, 31, 4,
                                                                          tzinfo=UTC), **SYSTEM))
    actions.record_verdict(RecordVerdictRequest(
        exp_id="F14b", idempotency_key="v:jan", requested_at=datetime(2027, 1, 1, 4, tzinfo=UTC),
        **SYSTEM))
    with OntologyUnitOfWork(engine) as uow:
        v = uow.rsi.latest_verdict("F14b")
    assert v.verdict == "inconclusive" and v.criterion_snapshot["expired"] is True
    assert v.criterion_snapshot["settlement_n"] == 90


def test_frozen_second_look_lets_cr2_be_judged_again_only_after_an_inconclusive_first(tmp_path):
    # 用 bound=ci_upper 的登记才有「跨线」可测（真 CR2 是 ci_lower，下界 <0 首判即证伪）
    actions2, engine2 = _rig(tmp_path)
    doc2 = {**F2_DOC, "exp_id": "CR2", "layer": "structural", "tier": "deploy_eligible",
            "falsifier": {"metric": "gamma_pct", "stratum": "zucai", "n_min": 30,
                          "bound": "ci_upper", "threshold_pp": 0.0,
                          "direction": "lt_means_falsified"}}
    actions2.register_experiment(RegisterExperimentRequest(
        doc=doc2, idempotency_key="reg:CR2b", requested_at=T0, **HUMAN))
    at2 = lambda d: datetime(2026, 11, d, tzinfo=UTC)  # noqa: E731
    actions2.grade_experiment(_grade_at("CR2", "c30", n=31, lo=-60.0, hi=20.0, at=at2(1)))
    actions2.record_verdict(RecordVerdictRequest(
        exp_id="CR2", idempotency_key="v:30", requested_at=at2(2), **SYSTEM))
    with pytest.raises(ValueError, match="差 29"):
        actions2.record_verdict(RecordVerdictRequest(
            exp_id="CR2", idempotency_key="v:31", requested_at=at2(3), **SYSTEM))
    actions2.grade_experiment(_grade_at("CR2", "c60", n=61, lo=-50.0, hi=-5.0, at=at2(20)))
    actions2.record_verdict(RecordVerdictRequest(
        exp_id="CR2", idempotency_key="v:60", requested_at=at2(21), **SYSTEM))
    with OntologyUnitOfWork(engine2) as uow:
        assert [v.verdict for v in uow.rsi.verdicts("CR2")] == ["inconclusive", "falsified"]
    with pytest.raises(ValueError, match="已结账"):
        actions2.record_verdict(RecordVerdictRequest(
            exp_id="CR2", idempotency_key="v:90", requested_at=at2(25), **SYSTEM))


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
        actor_id="sys:rsi" if role is ActorRole.DETERMINISTIC_SYSTEM else "op:jun",
        actor_role=role, acted_by="system" if role is ActorRole.DETERMINISTIC_SYSTEM else "Jun")
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


def test_retire_can_keep_duties_running_when_their_artifacts_have_other_readers(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.approve_deployment(ApproveDeploymentRequest(
        exp_id="F2", decision="retire", reason="窗口到期；观察单仍被日报读", rule_id=None,
        adjudication_ref=None, extend_to_exp_id=None, idempotency_key="d:keep", requested_at=T0,
        keep_duties=True, **HUMAN))
    with OntologyUnitOfWork(engine) as uow:
        assert [d.status for d in uow.rsi.duties("F2")] == ["active"]
        assert uow.rsi.latest_deployment("F2").decision == "retire"


# ── 同日重做：观测版本链 ───────────────────────────────────────────


def _fulfil_f2(actions, content: bytes, key: str, minute: int):
    return actions.fulfill_duty(FulfillDutyRequest(
        exp_id="F2", duty_name="f2-observation", day="2026-09-19",
        artifact_path="x.json", artifact_bytes=content, n_rows=10,
        population_stratum="zucai", judgment_tier_hist={"price_only": 10},
        captured_at=datetime(2026, 9, 18, 11, minute, tzinfo=UTC),
        earliest_kickoff="2026-09-19T00:30:00+08:00", idempotency_key=key,
        requested_at=T0))


def test_refulfilling_with_new_content_supersedes_and_counts_only_the_tip(tmp_path):
    actions, engine = _registered(tmp_path)
    actions.schedule_duties(ScheduleDutiesRequest(
        day="2026-09-19", earliest_kickoff="2026-09-19T00:30:00+08:00", issue="26129",
        idempotency_key="sch:1", requested_at=T0))
    assert _fulfil_f2(actions, b"A", "ful:a", 1).status is ActionStatus.COMMITTED
    assert _fulfil_f2(actions, b"B", "ful:b", 2).status is ActionStatus.COMMITTED
    assert _fulfil_f2(actions, b"A", "ful:a2", 3).status is ActionStatus.COMMITTED
    # 回到 B 的内容：B 那一行已存在，重新成为链尾而不是再插一行
    assert _fulfil_f2(actions, b"B", "ful:b2", 4).status is ActionStatus.COMMITTED
    hash_b = hashlib.sha256(b"B").hexdigest()
    with OntologyUnitOfWork(engine) as uow:
        rows = uow.rsi.observations("F2")
        active = [row for row in rows if row.superseded_by is None]
        assert len(rows) == 2                     # A 与 B 各一行，回到 A 时复用 base 行
        assert [row.artifact_hash for row in active] == [hash_b]
        assert uow.rsi.count_observations("F2") == 1
        assert uow.rsi.prospective_n_rows("F2", stratum="zucai") == 10
        assert uow.rsi.duty_instance("F2:f2-observation", "2026-09-19").artifact_hash == hash_b
