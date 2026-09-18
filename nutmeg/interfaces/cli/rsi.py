"""`nutmeg rsi …`：RSI 实验对象的命令面。每条命令 = 一个 Action，没有绕过 Action 写表的路径。

人 = judge_operator（register/amend/deploy）；
系统 = deterministic_system（schedule/fulfill/grade/verdict）。
`rsi verdict` 以系统身份调用——人从终端敲它也只是触发按冻结判据的判定，不是人在判。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.rsi_actions import (
    AmendExperimentRequest,
    ApproveDeploymentRequest,
    FulfillDutyRequest,
    GradeExperimentRequest,
    RecordVerdictRequest,
    RegisterExperimentRequest,
    ScheduleDutiesRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.rsi.models import Falsifier, project_status

rsi_app = typer.Typer(help="RSI 实验对象：登记 / 义务 / 采样 / 结账 / 判决 / 上线")
_cli.app.add_typer(rsi_app, name="rsi")

_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
_EXP = typer.Option(..., "--exp")
_EXP_OPT = typer.Option(None, "--exp")
_DAY = typer.Option(..., "--day")
_ISSUE = typer.Option(None, "--issue")
_NOW = typer.Option(None, "--now", help="测试用；默认当前时刻")
_DUTY = typer.Option(..., "--duty")
_ARTIFACT = typer.Option(..., "--artifact")
_N_ROWS = typer.Option(..., "--n-rows")
_STRATUM = typer.Option("zucai", "--stratum")
_MODE = typer.Option("prospective", "--mode")
_REASON = typer.Option(..., "--reason")
_RULE = typer.Option(None, "--rule")
_HOLD = typer.Option(False, "--hold")
_RETIRE = typer.Option(False, "--retire")
_EXTEND = typer.Option(None, "--extend", help="另立的新 exp_id")
_WHAT = typer.Option(..., "--what")
_WHY = typer.Option(..., "--why")
_RULE_CHECK = typer.Option("", "--rule-check")
_MECHANISM_NOTE = typer.Option(None, "--mechanism-note")
_HUMAN = dict(actor_id="operator:rsi", actor_role=ActorRole.JUDGE_OPERATOR)
_SYSTEM = dict(actor_id="system:rsi", actor_role=ActorRole.DETERMINISTIC_SYSTEM)


def _kernel(data_dir: Path):
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=Path(data_dir).expanduser().resolve()))
    kernel.initialize()
    return kernel


def _now() -> datetime:
    return datetime.now().astimezone()


def _fail(msg: str) -> None:
    typer.echo(f"rsi error: {msg}")
    raise typer.Exit(code=1)


def _run(fn, *args, **kwargs):
    try:
        outcome = fn(*args, **kwargs)
    except ValueError as exc:
        _fail(str(exc))
    if outcome.status is ActionStatus.REJECTED:
        _fail(f"权限拒绝：{outcome.error_detail}")
    return outcome


def _earliest_kickoff(data_dir: Path, issue: str | None) -> str | None:
    if not issue:
        return None
    p = data_dir / "zucai" / f"{issue}-issue.json"
    if not p.exists():
        return None
    matches = json.loads(p.read_text("utf-8"))["matches"]
    kos = [_normalise_bj(str(m["kickoff_bj"])) for m in matches if m.get("kickoff_bj")]
    return min(kos) if kos else None


_BJ = timezone(timedelta(hours=8))


def _normalise_bj(raw: str) -> str:
    """北京时间字串 → `YYYY-MM-DDTHH:MM:SS+08:00`。

    真 `<issue>-issue.json` 写的是「2026-09-19 00:30」（空格、无秒）；due_at 与 now 在
    repository 里按字串字典序比较，空格形式会排错位。与 scripts/rsi_migrate_preregs.py::_bj 同口径。
    """
    dt = datetime.fromisoformat(raw.strip().replace(" ", "T"))
    dt = dt.replace(tzinfo=_BJ) if dt.tzinfo is None else dt.astimezone(_BJ)
    return dt.isoformat(timespec="seconds")


@rsi_app.command("register")
def register(doc_path: Path, data_dir: Path = _DATA_DIR) -> None:
    """摄入登记原件（人）。同一 exp_id 二次登记拒绝。"""
    from nutmeg.decision.rsi_prereg import load_registry_doc

    try:
        doc = load_registry_doc(doc_path)
    except ValueError as exc:
        _fail(str(exc))
    k = _kernel(data_dir)
    # 键上调用时刻而非文件 mtime：同一原件二次登记必须落到 handler 的「已登记」拒绝，
    # 不能被幂等重放吞成成功。
    now = _now()
    _run(k.rsi_actions.register_experiment, RegisterExperimentRequest(
        doc=doc, idempotency_key=f"rsi-reg:{doc['exp_id']}:{now.isoformat()}",
        requested_at=now, **_HUMAN))
    with OntologyUnitOfWork(k.engine) as uow:
        e = uow.rsi.experiment(doc["exp_id"])
    typer.echo(f"已登记 {e.exp_id}  tier={e.tier} layer={e.layer} population={e.population}\n"
               f"  frozen_hash={e.frozen_hash[:16]}…  duties={len(doc.get('duties') or [])}")


@rsi_app.command("schedule")
def schedule(day: str = _DAY, issue: str | None = _ISSUE, data_dir: Path = _DATA_DIR) -> None:
    """为当天所有 observing 实验的 duty 生成实例（系统；备料链调）。"""
    k = _kernel(data_dir)
    ko = _earliest_kickoff(data_dir, issue)
    if ko is None:
        _fail(f"{day} 找不到最早开球（需要 zucai/{issue}-issue.json）")
    _run(k.rsi_actions.schedule_duties, ScheduleDutiesRequest(
        day=day, earliest_kickoff=ko, issue=issue, idempotency_key=f"rsi-sched:{day}",
        requested_at=_now(), **_SYSTEM))
    typer.echo(f"已排 {day} 的义务，截止 {ko}")


@rsi_app.command("due")
def due(day: str = _DAY, data_dir: Path = _DATA_DIR, now: str | None = _NOW) -> None:
    """列出当天还没落的义务：几点前、跑哪条命令。"""
    from nutmeg.decision.rsi_prereg import render_instrument

    k = _kernel(data_dir)
    now_iso = now or _now().isoformat(timespec="seconds")
    with OntologyUnitOfWork(k.engine) as uow:
        pend = uow.rsi.pending_duty_instances(day=day, now=now_iso)
        duties = {d.duty_id: d for d in uow.rsi.all_duties()}
    if not pend:
        typer.echo(f"{day}：无待办义务")
        return
    for p in pend:
        d = duties[p.duty_id]
        argv = render_instrument(d.instrument, issue=p.issue, day=day)
        typer.echo(f"{p.due_at}  {p.duty_id}\n    $ {' '.join(argv)}")


@rsi_app.command("fulfill")
def fulfill(exp: str = _EXP, duty: str = _DUTY, day: str = _DAY, artifact: Path = _ARTIFACT,
            n_rows: int = _N_ROWS, stratum: str = _STRATUM, issue: str | None = _ISSUE,
            data_dir: Path = _DATA_DIR) -> None:
    """观察仪产物落盘后登记（系统）。采样时刻取产物文件 mtime。"""
    k = _kernel(data_dir)
    ko = _earliest_kickoff(data_dir, issue)
    if ko is None:
        _fail("需要 --issue 以解析最早开球（前瞻性判定依赖它）")
    raw = artifact.read_bytes()
    captured = datetime.fromtimestamp(artifact.stat().st_mtime).astimezone()
    _run(k.rsi_actions.fulfill_duty, FulfillDutyRequest(
        exp_id=exp, duty_name=duty, day=day, artifact_path=str(artifact), artifact_bytes=raw,
        n_rows=n_rows, population_stratum=stratum, judgment_tier_hist={"price_only": n_rows},
        captured_at=captured, earliest_kickoff=ko, idempotency_key=f"rsi-ful:{exp}:{duty}:{day}",
        requested_at=_now(), **_SYSTEM))
    prospective = captured < datetime.fromisoformat(ko)
    typer.echo(f"已登记 {exp}/{duty}@{day}  n_rows={n_rows}  "
               f"{'前瞻' if prospective else '⚠️非前瞻（该日仍是 gap）'}")


@rsi_app.command("grade")
def grade(exp: str = _EXP, mode: str = _MODE, data_dir: Path = _DATA_DIR) -> None:
    """跑该实验的结账适配器并落 grade（系统）。当前实现 F2；其它实验由 replay_spec.harness 指定。"""
    from nutmeg.decision.rsi_grading import LeakError, grade_f2_prospective

    k = _kernel(data_dir)
    with OntologyUnitOfWork(k.engine) as uow:
        e = uow.rsi.experiment(exp)
    if e is None:
        _fail(f"{exp} 未登记")
    if exp != "F2":
        _fail(f"{exp} 的结账适配器尚未接入（replay_spec.harness={e.replay_spec})；本任务只接 F2")
    try:
        g = grade_f2_prospective(ledger_path=Path("experiments/prereg-26126-F2-ledger.json"),
                                 zucai_dir=data_dir / "zucai", primary_bucket=e.buckets[-1])
    except LeakError as exc:
        _fail(f"泄漏拒收：{exc}")
    _run(k.rsi_actions.grade_experiment, GradeExperimentRequest(
        exp_id=exp, mode=mode, stratum=g.stratum, n_cum=g.n_cum, metric_value_pp=g.metric_value_pp,
        ci_low_pp=g.ci_low_pp, ci_high_pp=g.ci_high_pp, cost_axis_pp=g.cost_axis_pp,
        as_of_policy=g.as_of_policy, computed_by=g.computed_by, inputs_hash=g.inputs_hash,
        idempotency_key=f"rsi-grade:{exp}:{mode}:{g.inputs_hash[:16]}",
        requested_at=_now(), **_SYSTEM))
    f = Falsifier.from_dict(e.falsifier)
    typer.echo(f"{exp} [{mode}] n={g.n_cum}  残差 {g.metric_value_pp:+.2f}pp  "
               f"CI[{g.ci_low_pp:+.2f}, {g.ci_high_pp:+.2f}]  距 n_min {max(0, f.n_min - g.n_cum)}")


@rsi_app.command("verdict")
def verdict(exp: str = _EXP, data_dir: Path = _DATA_DIR) -> None:
    """按冻结判据判 falsified / survived / inconclusive（系统身份；未到期拒绝）。"""
    k = _kernel(data_dir)
    _run(k.rsi_actions.record_verdict, RecordVerdictRequest(
        exp_id=exp, idempotency_key=f"rsi-verdict:{exp}:{_now().date()}",
        requested_at=_now(), **_SYSTEM))
    with OntologyUnitOfWork(k.engine) as uow:
        v = uow.rsi.latest_verdict(exp)
    typer.echo(f"{exp} → {v.verdict}（判据快照 {v.criterion_snapshot}）")


@rsi_app.command("deploy")
def deploy(exp: str = _EXP, reason: str = _REASON, rule: str | None = _RULE, hold: bool = _HOLD,
           retire: bool = _RETIRE, extend: str | None = _EXTEND,
           data_dir: Path = _DATA_DIR) -> None:
    """上线 / 搁置 / 废止 / 延续（只许人）。"""
    decision = "hold" if hold else "retire" if retire else "extend" if extend else "deploy"
    k = _kernel(data_dir)
    _run(k.rsi_actions.approve_deployment, ApproveDeploymentRequest(
        exp_id=exp, decision=decision, reason=reason, rule_id=rule, adjudication_ref=None,
        extend_to_exp_id=extend, idempotency_key=f"rsi-deploy:{exp}:{decision}:{_now().date()}",
        requested_at=_now(), **_HUMAN))
    typer.echo(f"{exp} → {decision}" + (f" (rule {rule})" if rule else ""))


@rsi_app.command("amend")
def amend(exp: str = _EXP, what: str = _WHAT, why: str = _WHY, rule_check: str = _RULE_CHECK,
          mechanism_note: str | None = _MECHANISM_NOTE, data_dir: Path = _DATA_DIR) -> None:
    """追加修正案（人）。碰冻结字段的修改不走这里——另立新实验。"""
    k = _kernel(data_dir)
    _run(k.rsi_actions.amend_experiment, AmendExperimentRequest(
        exp_id=exp, what=what, why=why, rule_check=rule_check, mechanism_note=mechanism_note,
        touches={},
        idempotency_key=f"rsi-amend:{exp}:{hashlib.sha256(what.encode()).hexdigest()[:12]}",
        requested_at=_now(), **_HUMAN))
    typer.echo(f"{exp} 修正案已追加")


@rsi_app.command("status")
def status(exp: str | None = _EXP_OPT, data_dir: Path = _DATA_DIR) -> None:
    """一屏：状态 / n_cum / CI / 距 falsifier / gaps / 下一期义务。"""
    k = _kernel(data_dir)
    now_iso = _now().isoformat(timespec="seconds")
    with OntologyUnitOfWork(k.engine) as uow:
        exps = [uow.rsi.experiment(exp)] if exp else uow.rsi.experiments()
        for e in exps:
            if e is None:
                _fail(f"{exp} 未登记")
            f = Falsifier.from_dict(e.falsifier)
            g = uow.rsi.latest_grade(e.exp_id, mode="prospective", stratum=f.stratum)
            v = uow.rsi.latest_verdict(e.exp_id)
            d = uow.rsi.latest_deployment(e.exp_id)
            st = project_status(n_observations=uow.rsi.count_observations(e.exp_id),
                                latest_prospective_n=g.n_cum if g else 0, n_min=f.n_min,
                                latest_verdict=v.verdict if v else None,
                                latest_deployment=d.decision if d else None)
            gaps = uow.rsi.gaps(e.exp_id, now=now_iso)
            line = f"{e.exp_id:6} {st:13} n={g.n_cum if g else 0:>4}/{f.n_min}"
            if g:
                line += (f"  CI[{g.ci_low_pp:+.1f},{g.ci_high_pp:+.1f}]"
                         f" 距falsifier {g.distance_to_falsifier_pp:+.1f}pp")
            if gaps:
                line += f"  gaps={gaps}"
            typer.echo(line)
