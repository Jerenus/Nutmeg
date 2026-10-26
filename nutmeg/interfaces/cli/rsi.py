"""`nutmeg rsi …`：RSI 实验对象的命令面。每条命令 = 一个 Action，没有绕过 Action 写表的路径。

人 = judge_operator（register/amend/deploy）；
系统 = deterministic_system（schedule/fulfill/grade/verdict）。
`rsi verdict` 以系统身份调用——人从终端敲它也只是触发按冻结判据的判定，不是人在判。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.decision.bj_time import BJ, bj_iso
from nutmeg.decision.faces import FACE_OF
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
_DAY_OPT = typer.Option(None, "--day")
_ISSUE = typer.Option(None, "--issue")
_NOW = typer.Option(None, "--now", help="测试用；默认当前时刻")
_DUTY = typer.Option(..., "--duty")
_ARTIFACT = typer.Option(..., "--artifact")
_N_ROWS = typer.Option(..., "--n-rows")
_STRATUM = typer.Option(None, "--stratum")
_MATCH = typer.Option("", "--match")
_MODE = typer.Option("prospective", "--mode")
_REGISTRY_DIR = typer.Option(Path("experiments/registry"), "--registry-dir",
                             help="CR 人群假说登记原件目录（结账前核冻结指纹）")
_REASON = typer.Option(..., "--reason")
_RULE = typer.Option(None, "--rule")
_HOLD = typer.Option(False, "--hold")
_RETIRE = typer.Option(False, "--retire")
_EXTEND = typer.Option(None, "--extend", help="另立的新 exp_id")
_WHAT = typer.Option(..., "--what")
_WHY = typer.Option(..., "--why")
_RULE_CHECK = typer.Option("", "--rule-check")
_MECHANISM_NOTE = typer.Option(None, "--mechanism-note")
_BY = typer.Option(..., "--by")
_FORK_FROM = typer.Option(None, "--fork-from")
_POPULATION = typer.Option(None, "--population")
_WINDOW_FROM = typer.Option(None, "--window-from")
_PRESCREEN = typer.Option(None, "--prescreen",
                          help="两段式：structure_align.py --indicator 的预筛 JSON；不过地板拒登记")
_N_MIN_OVERRIDE = typer.Option(None, "--n-min", help="与 --prescreen 同用，覆盖 n_min（≥60）")
_DRY_RUN_REG = typer.Option(False, "--dry-run", help="只打印改写后的原件 / 将发生的动作，不登记")
_REGISTER_WINNER = typer.Option(
    False, "--register-winner", help="write a candidate registry draft for the winner"
)
_HUMAN = dict(actor_id="operator:rsi", actor_role=ActorRole.JUDGE_OPERATOR)
_SYSTEM = dict(actor_id="system:rsi", actor_role=ActorRole.DETERMINISTIC_SYSTEM)


def _kernel(data_dir: Path):
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=Path(data_dir).expanduser().resolve()))
    kernel.initialize()
    return kernel


def _now() -> datetime:
    return datetime.now().astimezone()


def _business_day(at: datetime) -> str:
    local = at.astimezone(BJ)
    if local.hour < 7:
        local -= timedelta(days=1)
    return local.date().isoformat()


_CORPUS_V2 = Path(__file__).resolve().parents[3] / "experiments" / "corpus-v2.json"
# 样本账（2026-10-05）：前瞻样本首次入选即冻结，语料重建只能加样本、不能换值或丢样本。
_SAMPLES = Path(__file__).resolve().parents[3] / "experiments" / "rsi-samples.json"
_SAMPLES_OPT = typer.Option(_SAMPLES, "--samples", help="样本账路径（测试用）")
_RETRACT = typer.Option(None, "--retract", help="剔除的成员（语料键或身份）；须带 --reason/--by")
_REASON_OPT = typer.Option(None, "--reason")
_BY_OPT = typer.Option(None, "--by")


def _corpus_rows(path: Path | None = None) -> list[dict]:
    doc = json.loads((path or _CORPUS_V2).read_text("utf-8"))
    return doc["rows"] if isinstance(doc, dict) else doc


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
    kos = [bj_iso(str(m["kickoff_bj"])) for m in matches if m.get("kickoff_bj")]
    return min(kos) if kos else None


def _jczq_match_kickoffs(data_dir: Path, day: str) -> dict[str, str]:
    path = data_dir / "jczq" / "daily" / day / "jczq-legs-base.json"
    if not path.exists():
        return {}
    legs = json.loads(path.read_text(encoding="utf-8")).get("legs") or {}
    return {
        str(leg["match_id"]): bj_iso(str(leg["kickoff_bj"]))
        for leg in legs.values()
        if leg.get("match_id") and leg.get("kickoff_bj")
    }


def _zucai_match_kickoffs(data_dir: Path, issue: str | None) -> dict[str, str]:
    if issue is None:
        return {}
    issue_path = data_dir / "zucai" / f"{issue}-issue.json"
    ids_path = data_dir / "zucai" / f"{issue}-store-ids.json"
    if not issue_path.exists() or not ids_path.exists():
        return {}
    matches = json.loads(issue_path.read_text(encoding="utf-8")).get("matches") or []
    kickoff_by_no = {
        int(match["match_no"]): bj_iso(str(match["kickoff_bj"]))
        for match in matches
        if match.get("match_no") is not None and match.get("kickoff_bj")
    }
    payload = json.loads(ids_path.read_text(encoding="utf-8"))
    rows = payload.values() if isinstance(payload, dict) else payload
    return {
        str(row["match_id"]): kickoff_by_no[int(row["match_no"])]
        for row in rows
        if row.get("match_id") and int(row["match_no"]) in kickoff_by_no
    }


def _population_match_kickoffs(
    data_dir: Path,
    *,
    day: str,
    issue: str | None,
    populations: set[str],
    kernel=None,
) -> dict[str, dict[str, str]]:
    from nutmeg.decision.rsi_population import matches_for_population

    jczq = _jczq_match_kickoffs(data_dir, day)
    zucai = _zucai_match_kickoffs(data_dir, issue)
    kickoff_by_match = {**zucai, **jczq}
    out = {
        population: {
            row["match_id"]: kickoff_by_match[row["match_id"]]
            for row in matches_for_population(
                population, day=day, issue=issue, data_dir=data_dir
            )
            if row["match_id"] in kickoff_by_match
        }
        for population in populations
    }
    if kernel is not None and "both" in out and issue:
        out["both"] = _keep_scheduled_identity(kernel, data_dir, day=day, issue=issue,
                                               kickoffs=out["both"])
    return out


def _scheduled_zucai_alias(kernel, data_dir: Path, *, day: str, issue: str) -> dict[str, str]:
    """{竞彩侧 match_id: 这一天已按足彩侧 id 排过义务的 match_id}。

    并集池里竞彩/足彩重叠的场在内核有两个 Match id（足彩 `<期>-store-ids` 一套、竞彩
    legs-base 一套），对号靠 channel-map。只返回两侧 id 不同且足彩侧已排义务的场。"""
    from nutmeg.decision.zucai_identity import load_channel_map

    zdir = Path(data_dir) / "zucai"
    mapping = load_channel_map(zdir, issue)
    if not mapping:
        return {}
    store_path = zdir / f"{issue}-store-ids.json"
    store = json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        scheduled = {
            row.match_id
            for duty in uow.rsi.all_duties()
            for row in uow.rsi.duty_instances_for_day(duty.duty_id, day)
        }
    out: dict[str, str] = {}
    for jczq_id, match_no in mapping.items():
        zucai_id = (store.get(str(match_no)) or {}).get("match_id")
        if zucai_id and zucai_id != jczq_id and zucai_id in scheduled:
            out[jczq_id] = zucai_id
    return out


def _channel_twins(data_dir: Path, issue: str) -> dict[str, str]:
    """{竞彩侧 id: 足彩侧 id} ∪ {足彩侧 id: 竞彩侧 id}：同一场在内核的两个身份
    （channel-map × store-ids）。"""
    from nutmeg.decision.zucai_identity import load_channel_map

    zdir = Path(data_dir) / "zucai"
    store_path = zdir / f"{issue}-store-ids.json"
    store = json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {}
    out: dict[str, str] = {}
    for jczq_id, match_no in load_channel_map(zdir, issue).items():
        zucai_id = (store.get(str(match_no)) or {}).get("match_id")
        if zucai_id and zucai_id != jczq_id:
            out[jczq_id] = zucai_id
            out[zucai_id] = jczq_id
    return out


def _scheduled_duty_identities(kernel, data_dir: Path, *, duty_id: str, day: str, match: str,
                               issue: str | None) -> list[str]:
    """履约认两侧身份（2026-10-14）。重叠场的义务可能按足彩侧 id 排（_keep_scheduled_identity）、
    也可能两侧各一条；研究只按竞彩板的 id 履约 → 足彩侧那条到开球即过期：R1 自 10-10 起每天
    5–7 个假缺口（26140 六场、26141 六场），同 F9 10-12 的死法。
    返回这一天排过的身份（本 id、对上的另一侧 id），都没排过就原样返回让动作照旧报错。"""
    with OntologyUnitOfWork(kernel.engine) as uow:
        rows = uow.rsi.duty_instances_for_day(duty_id, day)
    scheduled = {row.match_id for row in rows}
    issues = {row.issue for row in rows if row.issue}
    resolved = issue or (next(iter(issues)) if len(issues) == 1 else None)
    twin = _channel_twins(data_dir, resolved).get(match) if resolved else None
    found = [m for m in (match, twin) if m and m in scheduled]
    return found or [match]


def _keep_scheduled_identity(kernel, data_dir: Path, *, day: str, issue: str,
                             kickoffs: dict[str, str]) -> dict[str, str]:
    """并集池同一场比赛只排一条义务（2026-10-05）。channel-map 18:30 才落地：之前足彩场按
    足彩侧 id 排过并已履约，对上竞彩后又按竞彩侧 id 排一条——永远空着，10-05 R1 七个假缺口。
    这一天已按足彩侧 id 排过的场，继续用足彩侧 id。"""
    out = dict(kickoffs)
    for jczq_id, zucai_id in _scheduled_zucai_alias(
        kernel, data_dir, day=day, issue=issue
    ).items():
        if jczq_id in out and zucai_id not in out:
            out[zucai_id] = out.pop(jczq_id)
    return out


_SCHEDULE_SEMANTICS = "explicit-cross-channel-identity-v2"


def _schedule_targets_fingerprint(
    earliest_kickoff: str, match_kickoffs: dict, population_match_kickoffs: dict
) -> str:
    """同日板面变了（新增场次/最早开球位移）就是新请求：键上带目标集指纹。

    2026-09-22 的死法：after_am 在 00:00 用当时的板面排过一次；周二001 后来才进板，
    最早开球位移 → 同键异请求 → IdempotencyConflictError，R0 义务排不进去。
    """
    material = {
        "earliest_kickoff": earliest_kickoff,
        "match_kickoffs": match_kickoffs,
        "population_match_kickoffs": population_match_kickoffs,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]


def _duty_schedule_context(kernel) -> tuple[set[str], str]:
    with OntologyUnitOfWork(kernel.engine) as uow:
        duties = uow.rsi.all_duties()
        experiments = {
            duty.exp_id: uow.rsi.experiment(duty.exp_id) for duty in duties
        }
    populations = {
        experiments[duty.exp_id].population
        for duty in duties
        if duty.scope == "match" and experiments[duty.exp_id] is not None
    }
    material = [
        {
            "duty_id": duty.duty_id,
            "scope": duty.scope,
            "deadline_rule": duty.deadline_rule,
            "instrument": duty.instrument,
            "artifact_glob": duty.artifact_glob,
            "status": duty.status,
            "population": experiments[duty.exp_id].population,
        }
        for duty in duties
        if experiments[duty.exp_id] is not None
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            {"semantics": _SCHEDULE_SEMANTICS, "duties": material},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return populations, fingerprint


def _fork_registry_doc(
    *,
    kernel,
    target_path: Path,
    fork_from: str,
    population: str,
    window_from: str,
) -> dict:
    from nutmeg.ontology.rsi.models import Population

    Population(population)
    with OntologyUnitOfWork(kernel.engine) as uow:
        source = uow.rsi.experiment(fork_from)
        if source is None:
            raise ValueError(f"{fork_from} 未登记")
        if uow.rsi.latest_verdict(fork_from) is not None:
            raise ValueError(f"{fork_from} 已结账，不得 fork")
        duties = uow.rsi.duties(fork_from)
    if target_path.exists():
        raise ValueError(f"目标原件已存在：{target_path}")
    try:
        datetime.strptime(window_from, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("--window-from 必须是 YYYY-MM-DD") from exc
    falsifier = {**source.falsifier}
    falsifier["stratum"] = "pooled" if population == "both" else population
    doc = _doc_from_source(
        source, duties, exp_id=target_path.stem, population=population,
        window={"date_from": window_from, "n_min": falsifier["n_min"]}, falsifier=falsifier,
        registered_at=source.registered_at, forked_from=fork_from)
    _write_registry_doc(target_path, doc)
    return doc


def _doc_from_source(source, duties, *, exp_id: str, population: str, window: dict,
                     falsifier: dict, registered_at: str, **extra) -> dict:
    """内核里的实验 + 义务 → 一份登记原件（fork 与 epoch 共用；spec 字段原样复制）。"""
    doc = {
        "exp_id": exp_id,
        "claim": source.claim,
        "mechanism": source.mechanism,
        "tier": source.tier,
        "layer": source.layer,
        "population": population,
        "min_tier": source.min_tier,
        "window": window,
        "falsifier": falsifier,
        "stop_rule": source.stop_rule,
        "quota_slot": source.quota_slot,
        "buckets": source.buckets,
        "rule_ids": source.rule_ids,
        "source_doc": source.source_doc,
        "registered_at": registered_at,
        **extra,
        "duties": [
            {
                "name": duty.duty_id.split(":", 1)[1],
                "scope": duty.scope,
                "deadline_rule": duty.deadline_rule,
                "instrument": duty.instrument,
                "artifact_glob": duty.artifact_glob,
                "description": duty.description,
            }
            for duty in duties
        ],
    }
    for key in ("replay_spec", "dream_ref", "variants_tried"):
        if getattr(source, key) is not None:
            doc[key] = getattr(source, key)
    return doc


def _write_registry_doc(target_path: Path, doc: dict) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


@rsi_app.command("register")
def register(
    doc_path: Path,
    by: str = _BY,
    data_dir: Path = _DATA_DIR,
    fork_from: str | None = _FORK_FROM,
    population: str | None = _POPULATION,
    window_from: str | None = _WINDOW_FROM,
    prescreen: Path | None = _PRESCREEN,
    n_min: int | None = _N_MIN_OVERRIDE,
    dry_run: bool = _DRY_RUN_REG,
) -> None:
    """摄入登记原件（人）。同一 exp_id 二次登记拒绝。

    --prescreen（两段式 2026-10-26）：读回溯预筛结果——不过地板拒登记；过地板但 |效应| <10pp
    → role=display_only 只做展示列；否则 n_min=60（--n-min 可抬高）。改写后的原件回写文件。"""
    from nutmeg.decision.rsi_prereg import apply_prescreen, load_registry_doc

    k = _kernel(data_dir)
    try:
        fork_values = (fork_from, population, window_from)
        if any(value is not None for value in fork_values):
            if not all(value is not None for value in fork_values):
                raise ValueError(
                    "fork 模式必须同时提供 --fork-from/--population/--window-from"
                )
            _fork_registry_doc(
                kernel=k,
                target_path=doc_path,
                fork_from=str(fork_from),
                population=str(population),
                window_from=str(window_from),
            )
        doc = load_registry_doc(doc_path)
        if prescreen is not None:
            doc = apply_prescreen(doc, json.loads(prescreen.read_text(encoding="utf-8")),
                                  n_min=n_min)
            if not dry_run:
                _write_registry_doc(doc_path, doc)
        elif n_min is not None:
            raise ValueError("--n-min 只配 --prescreen")
    except ValueError as exc:
        _fail(str(exc))
    if dry_run:
        typer.echo(json.dumps({k_: v for k_, v in doc.items() if k_ != "prescreen"},
                              ensure_ascii=False, indent=1))
        typer.echo(f"[dry-run] 未登记；role={doc.get('role')} n_min={doc['window'].get('n_min')}")
        return
    # 键上调用时刻而非文件 mtime：同一原件二次登记必须落到 handler 的「已登记」拒绝，
    # 不能被幂等重放吞成成功。
    now = _now()
    _run(k.rsi_actions.register_experiment, RegisterExperimentRequest(
        doc=doc, acted_by=by,
        idempotency_key=f"rsi-reg:{doc['exp_id']}:{now.isoformat()}",
        requested_at=now, **_HUMAN))
    with OntologyUnitOfWork(k.engine) as uow:
        e = uow.rsi.experiment(doc["exp_id"])
    typer.echo(f"已登记 {e.exp_id}  tier={e.tier} layer={e.layer} population={e.population}\n"
               f"  frozen_hash={e.frozen_hash[:16]}…  duties={len(doc.get('duties') or [])}")
    from nutmeg.decision.rsi_prereg import is_observation_only

    if is_observation_only(doc):
        typer.echo("  观察型：没写出口（exits），照样登记、作为正样本积累；判决不改任何开关")
    else:
        typer.echo("  出口：" + "；".join(f"{k}={v}" for k, v in doc["exits"].items()))
    if doc.get("role") == "display_only":
        typer.echo("  展示中：预筛过地板但 |效应| <10pp，只做分析包列，不 grade / 不 verdict")
    elif doc.get("prescreen"):
        ps = doc["prescreen"]
        typer.echo(f"  两段式：预筛 {ps['id']} 残差 {ps['residual_pp']:+.1f}pp 过地板 → "
                   f"前瞻 n_min={doc['window']['n_min']}")


_EPOCH_REASON = typer.Option(..., "--reason", help="口径变更是什么（SOP 哪条、哪天）")


@rsi_app.command("epoch")
def epoch(exp: str = _EXP, reason: str = _EPOCH_REASON, by: str = _BY,
          data_dir: Path = _DATA_DIR, registry_dir: Path = _REGISTRY_DIR,
          dry_run: bool = _DRY_RUN_REG) -> None:
    """口径变更＝新 epoch（2026-10-26 RULEBOOK「〇」④）：现 epoch 按 v2 结一次账（未到期则只记
    最新 grade）、退役并标 epoch_closed；复制登记为 `<exp>.v2`（registered_at=今天、窗口从今天、
    spec 不变、epoch_of/reason），status 两行并列。不自动触发，只做命令。"""
    from nutmeg.decision.rsi_prereg import load_registry_doc, next_epoch_id

    k = _kernel(data_dir)
    now = _now()
    today = now.date().isoformat()
    new_id = next_epoch_id(exp)
    target = Path(registry_dir) / f"{new_id}.json"
    with OntologyUnitOfWork(k.engine) as uow:
        source = uow.rsi.experiment(exp)
        if source is None:
            _fail(f"{exp} 未登记")
        if uow.rsi.experiment(new_id) is not None or target.exists():
            _fail(f"{new_id} 已存在（登记或原件）")
        duties = uow.rsi.duties(exp)
        deployment = uow.rsi.latest_deployment(exp)
        latest = uow.rsi.latest_grade(exp, mode="prospective",
                                      stratum=Falsifier.from_dict(source.falsifier).stratum)
    if deployment is not None and deployment.decision == "retire":
        _fail(f"{exp} 已退役，没有可关的 epoch")
    doc = _doc_from_source(
        source, duties, exp_id=new_id, population=source.population,
        window={**(source.window or {}), "date_from": today},
        falsifier=dict(source.falsifier), registered_at=today,
        epoch_of=exp, epoch_reason=reason)
    doc["window"].pop("date_to", None)
    close_note = (f"最新 grade n={latest.n_cum} "
                  f"CI[{latest.ci_low_pp:+.1f},{latest.ci_high_pp:+.1f}]" if latest else "无 grade")
    if dry_run:
        typer.echo(f"[dry-run] {exp} → epoch_closed（{close_note}；先试 v2 结账，未到期则只记）")
        typer.echo(f"[dry-run] 将写 {target} 并登记 {new_id}：")
        typer.echo(json.dumps(doc, ensure_ascii=False, indent=1))
        return
    # 1) 现 epoch 结一次账：到期就按 v2 判，未到期只记最新 grade（不改判决语义）
    settled = _run_quiet(k.rsi_actions.record_verdict, RecordVerdictRequest(
        exp_id=exp, idempotency_key=f"rsi-verdict-v2:{exp}:{now.isoformat()}",
        requested_at=now, **_SYSTEM))
    # 2) 退役并标 epoch_closed（status 显示为 epoch_closed）
    _run(k.rsi_actions.approve_deployment, ApproveDeploymentRequest(
        exp_id=exp, decision="retire", rule_id=None, adjudication_ref=None, extend_to_exp_id=None,
        reason=f"epoch_closed → {new_id}：{reason}（{close_note}）", acted_by=by,
        keep_duties=False, idempotency_key=f"rsi-epoch-close:{exp}:{now.isoformat()}",
        requested_at=now, **_HUMAN))
    # 3) 新 epoch：写原件 + 登记
    _write_registry_doc(target, doc)
    load_registry_doc(target)
    _run(k.rsi_actions.register_experiment, RegisterExperimentRequest(
        doc=doc, acted_by=by, idempotency_key=f"rsi-reg:{new_id}:{now.isoformat()}",
        requested_at=now, **_HUMAN))
    typer.echo(f"{exp} → epoch_closed（{'v2 已结账' if settled else '未到期，只记'}："
               f"{close_note}）")
    typer.echo(f"{new_id} 已登记  window.date_from={today}  n_min={doc['window'].get('n_min')}"
               f"  duties={len(doc['duties'])}  原件 {target}")


def _run_quiet(fn, request) -> bool:
    """同 _run，但「未到期 / 已结账」类 ValueError 不算失败（epoch 关账时的预期分支）。"""
    try:
        outcome = fn(request)
    except ValueError:
        return False
    return outcome.status is not ActionStatus.REJECTED


@rsi_app.command("schedule")
def schedule(day: str = _DAY, issue: str | None = _ISSUE, data_dir: Path = _DATA_DIR) -> None:
    """为当天所有 observing 实验的 duty 生成实例（系统；备料链调）。"""
    k = _kernel(data_dir)
    match_kickoffs = _jczq_match_kickoffs(data_dir, day) if issue is None else {}
    ko = _earliest_kickoff(data_dir, issue)
    if ko is None and match_kickoffs:
        ko = min(match_kickoffs.values())
    if ko is None:
        board = data_dir / "jczq" / "daily" / day / "jczq-legs-base.json"
        if issue is None and not board.exists():
            # 空盘 / 未开售（RUNBOOK A1）：没有板就没有义务可排，不是错误
            typer.echo(f"{day} 空盘：跳过排义务（无竞彩 legs-base 且未指定足彩期）")
            return
        _fail(f"{day} 找不到最早开球（需要足彩 issue 或竞彩 legs-base）")
    populations, duty_fingerprint = _duty_schedule_context(k)
    population_match_kickoffs = _population_match_kickoffs(
        data_dir,
        day=day,
        issue=issue,
        populations=populations,
        kernel=k,
    )
    _run(k.rsi_actions.schedule_duties, ScheduleDutiesRequest(
        day=day, earliest_kickoff=ko, issue=issue, match_kickoffs=match_kickoffs,
        population_match_kickoffs=population_match_kickoffs,
        idempotency_key=(
            f"rsi-sched:{day}:{issue or 'jczq'}:{duty_fingerprint}:"
            + _schedule_targets_fingerprint(ko, match_kickoffs, population_match_kickoffs)
        ),
        requested_at=_now(), **_SYSTEM))
    typer.echo(f"已排 {day} 的义务，截止 {ko}")


@rsi_app.command("due")
def due(
    day: str = _DAY,
    issue: str | None = _ISSUE,
    data_dir: Path = _DATA_DIR,
    now: str | None = _NOW,
) -> None:
    """列出当天还没落的义务：几点前、跑哪条命令。"""
    from nutmeg.decision.rsi_prereg import render_instrument

    k = _kernel(data_dir)
    now_iso = now or _now().isoformat(timespec="seconds")
    duties, instances = _duty_ledger(k, day)
    pend = sorted(
        (
            row
            for row in instances
            if row.fulfilled_at is None
            and row.due_at > now_iso
            and duties[row.duty_id].status == "active"
        ),
        key=lambda row: (row.due_at, row.duty_id),
    )
    if not pend:
        typer.echo(f"{day}：无待办义务")
        return
    for p in pend:
        d = duties[p.duty_id]
        resolved_issue = issue or p.issue
        if resolved_issue is None and any("{issue}" in arg for arg in d.instrument):
            command = "<需 --issue> " + " ".join(d.instrument)
            note = "  # 需 --issue"
        else:
            argv = render_instrument(d.instrument, issue=resolved_issue, day=day)
            command = " ".join(argv)
            note = ""
        typer.echo(f"{p.due_at}  {p.duty_id}\n    $ {command}{note}")


def _duty_ledger(kernel, day: str):
    with OntologyUnitOfWork(kernel.engine) as uow:
        duties = {duty.duty_id: duty for duty in uow.rsi.all_duties()}
        instances = [
            row
            for duty_id in duties
            for row in uow.rsi.duty_instances_for_day(duty_id, day)
        ]
    return duties, instances


def _concluded_experiments(kernel) -> set[str]:
    """已结账（协议 v2 单次判决）或已退役的实验——与 `rsi status` 同一口径。

    它们的义务若仍 active，是 `--keep-duties` 留下的观察仪（F5 价格带 / F9 位移账 / F16 损耗
    台账：day_brief 与分析包在读产物），sweep 照跑；但实验不再有前瞻资格要守，产物落了
    却没登记到某条实例（该场 reads 未到、台账行缺 kickoff、排程占位将被清理）不再算失败。
    2026-10-12→26 巡检 33 次红灯里 22 次是这一类 DUTY_NOT_FULFILLED / DUTY_EXPIRED。"""
    from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL

    out: set[str] = set()
    with OntologyUnitOfWork(kernel.engine) as uow:
        for e in uow.rsi.experiments():
            v = uow.rsi.latest_verdict(e.exp_id)
            d = uow.rsi.latest_deployment(e.exp_id)
            settled = v is not None and v.criterion_snapshot.get("protocol") == VERDICT_PROTOCOL
            if settled or (d is not None and d.decision == "retire"):
                out.add(e.exp_id)
    return out


def _is_balance_instrument(argv: list[str]) -> bool:
    return argv[:5] == ["uv", "run", "nutmeg", "rsi", "balance"]


def _research_deferred_count(argv: list[str], stdout: str) -> int:
    if argv[:5] != ["uv", "run", "nutmeg", "research", "run"]:
        return 0
    deferred = {
        "skipped_backoff",
        "skipped_permanent",
        "skipped_retry_limit",
        "skipped_budget",
        # 同日另一轮研究正在跑（2026-10-07 加锁）：下一次 sweep 再看
        "skipped_busy",
        # 已研过 / 入库拒收：义务留作 gap，不该每小时报成命令失败（2026-09-30）
        "skipped_done",
        "rejected",
    }
    return sum(
        len(parts) >= 2 and parts[1] in deferred
        for line in stdout.splitlines()
        if (parts := line.strip().split())
    )


def _balance_reads_ready(
    data_dir: Path, *, day: str, issue: str | None
) -> bool:
    jczq_reads = data_dir / "jczq" / "daily" / day / "reads.json"
    zucai_reads = data_dir / "zucai" / f"{issue}-reads.json" if issue else None
    return jczq_reads.exists() or (zucai_reads is not None and zucai_reads.exists())


@rsi_app.command("sweep")
def sweep(
    day: str | None = _DAY_OPT,
    issue: str | None = _ISSUE,
    data_dir: Path = _DATA_DIR,
    now: str | None = _NOW,
) -> None:
    """Run due RSI instruments without backfilling expired duty instances."""
    from nutmeg.decision.rsi_prereg import render_instrument

    k = _kernel(data_dir)
    now_iso = now or _now().isoformat(timespec="seconds")
    resolved_day = day or _business_day(datetime.fromisoformat(now_iso))
    warn_after = (datetime.fromisoformat(now_iso) - timedelta(minutes=65)).isoformat(
        timespec="seconds")
    counts = {
        "ran": 0,
        "skipped_fulfilled": 0,
        "skipped_pending": 0,
        "skipped_not_ready": 0,
        "skipped_manual": 0,
        "observer_unregistered": 0,
        "expired": 0,
        "failed": 0,
    }
    duties, day_instances = _duty_ledger(k, resolved_day)
    concluded = _concluded_experiments(k)
    instances = {
        duty_id: [row for row in day_instances if row.duty_id == duty_id]
        for duty_id in duties
    }

    def _err(message: str) -> None:
        typer.echo(f"[{now_iso}] {message}", err=True)

    ordered = sorted(duties.values(), key=lambda d: d.duty_id)
    for duty in ordered:
        if duty.status == "retired":
            # 实验已废止：义务不再跑（2026-10-05：F4 退役后 sweep 每小时跑已删除的 `nutmeg plan`，
            # 退出码 1 把状态页染红）
            continue
        # 已结账/已退役实验留下的观察仪：照跑、不守前瞻资格（见 _concluded_experiments）
        observer = duty.exp_id in concluded
        rows = instances[duty.duty_id]
        fulfilled = [row for row in rows if row.fulfilled_at is not None]
        open_rows = [row for row in rows if row.fulfilled_at is None]
        counts["skipped_fulfilled"] += len(fulfilled)
        if duty.status == "pending_instrument" or (
            duty.instrument and duty.instrument[0] == "TODO"
        ):
            counts["skipped_pending"] += len(open_rows)
            continue
        if duty.status == "manual":
            # 人做的动作（F4=plan commit）：只排不跑，履行走该命令自己的钩子。
            counts["skipped_manual"] += len(open_rows)
            continue

        expired = [row for row in open_rows if row.due_at <= now_iso]
        runnable = [row for row in open_rows if row.due_at > now_iso]
        counts["expired"] += len(expired)
        # 只在过期后的第一次巡检告警（巡检每小时一次）：2026-10-19 前同一批过期实例每小时刷一遍
        fresh = [row for row in expired if row.due_at > warn_after]
        if fresh and not observer:
            _err(
                f"⚠️DUTY_EXPIRED: {duty.duty_id} {len(fresh)} 条已过开球"
                "（前瞻资格已失）")
        if not runnable:
            continue
        if not duty.instrument or duty.instrument[0] != "uv":
            counts["failed"] += len(runnable)
            _err(
                f"UNSAFE_INSTRUMENT: {duty.duty_id} 只允许 argv[0]=uv")
            continue

        row_issues = {row.issue for row in runnable if row.issue}
        resolved_issue = issue or (next(iter(row_issues)) if len(row_issues) == 1 else None)
        if len(row_issues) > 1 and issue is None:
            counts["failed"] += len(runnable)
            _err(f"rsi error: {duty.duty_id} 同日绑定多个 issue")
            continue
        if resolved_issue is None and any("{issue}" in arg for arg in duty.instrument):
            counts["skipped_not_ready"] += len(runnable)
            _err(
                f"DUTY_NOT_READY: {duty.duty_id}: 当天没有足彩期")
            continue
        try:
            argv = render_instrument(
                duty.instrument, issue=resolved_issue, day=resolved_day
            )
        except ValueError as exc:
            counts["failed"] += len(runnable)
            _err(f"rsi error: {duty.duty_id}: {exc}")
            continue
        if _is_balance_instrument(argv) and not _balance_reads_ready(
            data_dir, day=resolved_day, issue=resolved_issue
        ):
            counts["skipped_not_ready"] += len(runnable)
            _err(
                f"DUTY_NOT_READY: {duty.duty_id}: reads 尚未落盘")
            continue
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
        if completed.stdout:
            typer.echo(completed.stdout.rstrip())
        if completed.stderr:
            _err(completed.stderr.rstrip())
        if completed.returncode != 0:
            counts["failed"] += len(runnable)
            _err(
                f"rsi error: {duty.duty_id} instrument exit={completed.returncode}")
            continue
        with OntologyUnitOfWork(k.engine) as uow:
            after = [
                uow.rsi.duty_instance(row.duty_id, row.day, row.match_id)
                for row in runnable
            ]
        fulfilled_now = sum(
            row is not None and row.fulfilled_at is not None for row in after
        )
        not_fulfilled = len(runnable) - fulfilled_now
        counts["ran"] += fulfilled_now
        deferred = min(
            not_fulfilled, _research_deferred_count(argv, completed.stdout)
        )
        if deferred:
            counts["skipped_not_ready"] += deferred
            not_fulfilled -= deferred
        if not_fulfilled and observer:
            counts["observer_unregistered"] += not_fulfilled
        elif not_fulfilled:
            counts["failed"] += not_fulfilled
            _err(
                f"DUTY_NOT_FULFILLED: {duty.duty_id} {not_fulfilled} 条命令成功但未登记")

    typer.echo(
        f"{resolved_day} sweep: "
        + " ".join(f"{key}={value}" for key, value in counts.items())
    )
    if counts["failed"] > 0:
        raise typer.Exit(code=1)


def _day_scoped_duty_day(k, duty_id: str, day: str, issue: str) -> str:
    """日级义务排在备料业务日（停售日），观察仪却按「最早开球日」登记——期次首场
    过了午夜就对不上（2026-09-28 26134 首场 9/29 00:00：F2/F1c 整天「命令成功但
    未登记」）。给定日查不到时按期号找；期号唯一对到一天才改用它，否则照旧报错。"""
    with OntologyUnitOfWork(k.engine) as uow:
        if uow.rsi.duty_instance(duty_id, day) is not None:
            return day
        days = uow.rsi.day_scoped_days_for_issue(duty_id, issue)
    if len(days) == 1:
        typer.echo(f"ℹ️{duty_id} 按期号 {issue} 对到业务日 {days[0]}（传入 {day}）")
        return days[0]
    return day


@rsi_app.command("fulfill")
def fulfill(exp: str = _EXP, duty: str = _DUTY, day: str = _DAY, artifact: Path = _ARTIFACT,
            n_rows: int = _N_ROWS, stratum: str | None = _STRATUM, issue: str | None = _ISSUE,
            match: str = _MATCH, data_dir: Path = _DATA_DIR) -> None:
    """观察仪产物落盘后登记（系统）。采样时刻取产物文件 mtime。"""
    k = _kernel(data_dir)
    ko = _earliest_kickoff(data_dir, issue)
    if match:
        ko = (_jczq_match_kickoffs(data_dir, day).get(match)
              or _zucai_match_kickoffs(data_dir, issue).get(match))
    if ko is None:
        _fail("需要 --issue 或 --match 以解析开球（前瞻性判定依赖它）")
    identities = _scheduled_duty_identities(
        k, data_dir, duty_id=f"{exp}:{duty}", day=day, match=match, issue=issue
    ) if match else [match]
    if not match and issue:
        day = _day_scoped_duty_day(k, f"{exp}:{duty}", day, issue)
    raw = artifact.read_bytes()
    captured = datetime.fromtimestamp(artifact.stat().st_mtime).astimezone()
    for identity in identities:
        _run(k.rsi_actions.fulfill_duty, FulfillDutyRequest(
            exp_id=exp, duty_name=duty, day=day, artifact_path=str(artifact),
            artifact_bytes=raw, n_rows=n_rows, population_stratum=stratum,
            judgment_tier_hist={"deep_research" if match else "price_only": n_rows},
            captured_at=captured, earliest_kickoff=ko, match_id=identity,
            # 键带产物 hash：研究被驳回后重做是新请求（旧观测被取代），字节相同才是 no-op
            idempotency_key=(
                f"rsi-ful:{exp}:{duty}:{day}:{identity}:"
                f"{hashlib.sha256(raw).hexdigest()[:16]}"
            ),
            requested_at=_now(), **_SYSTEM))
    prospective = captured < datetime.fromisoformat(ko)
    twin_note = f"（含另一侧身份 {len(identities) - 1} 条）" if len(identities) > 1 else ""
    typer.echo(f"已登记 {exp}/{duty}@{day}  n_rows={n_rows}  "
               f"{'前瞻' if prospective else '⚠️非前瞻（该日仍是 gap）'}{twin_note}")


def _official_zucai_outcomes(data_dir: Path, issue: str, reads: list[dict]) -> dict | None:
    path = data_dir / "zucai" / "official-results.json"
    if not path.exists():
        return None
    result = json.loads(path.read_text(encoding="utf-8")).get(issue)
    if not isinstance(result, str):
        return None
    face = FACE_OF
    codes = result.split()
    outcomes: dict[str, str] = {}
    for index, read in enumerate(reads):
        if index >= len(codes) or codes[index] not in face:
            continue
        actual = face[codes[index]]
        for key in (
            read.get("match_id"),
            read.get("read_id"),
            read.get("match_no"),
            index + 1,
        ):
            if key is not None:
                outcomes[str(key)] = actual
    return outcomes or None


@rsi_app.command("balance")
def balance(
    issue: str | None = _ISSUE,
    day: str | None = _DAY_OPT,
    data_dir: Path = _DATA_DIR,
) -> None:
    """Write and fulfill one F9 balance row per match in the frozen population."""
    from nutmeg.decision.balance_ledger import balance_ledger, balance_row
    from nutmeg.decision.rsi_population import matches_for_population

    if issue is None and day is None:
        _fail("需要 --issue 或 --day")
    k = _kernel(data_dir)
    kickoff = _earliest_kickoff(data_dir, issue)
    resolved_day = day or (kickoff[:10] if kickoff else None)
    if resolved_day is None:
        _fail("找不到最早开球，无法登记 F9 duty")

    if issue is None:
        with OntologyUnitOfWork(k.engine) as uow:
            scheduled = uow.rsi.duty_instances_for_day(
                "F9:balance-ledger", resolved_day
            )
        scheduled_issues = {row.issue for row in scheduled if row.issue}
        if len(scheduled_issues) > 1:
            _fail(f"{resolved_day} 的 F9 duty 绑定了多个 issue")
        issue = next(iter(scheduled_issues), None)

    day_dir = data_dir / "jczq" / "daily" / resolved_day
    jczq_reads_path = day_dir / "reads.json"
    zucai_reads_path = data_dir / "zucai" / f"{issue}-reads.json" if issue else None
    jczq_reads = (
        json.loads(jczq_reads_path.read_text(encoding="utf-8"))
        if jczq_reads_path.exists()
        else []
    )
    zucai_reads = (
        json.loads(zucai_reads_path.read_text(encoding="utf-8"))
        if zucai_reads_path is not None and zucai_reads_path.exists()
        else []
    )
    if not jczq_reads and not zucai_reads:
        _fail(f"reads 不存在：{jczq_reads_path}")

    population_kickoffs = _population_match_kickoffs(
        data_dir,
        day=resolved_day,
        issue=issue,
        populations={"both"},
        kernel=k,
    )
    kickoffs = population_kickoffs["both"]
    if not kickoffs:
        _fail("找不到逐场开球，无法登记 F9 duty")
    kickoff = min(kickoffs.values())

    read_by_match = {
        str(read["match_id"]): read
        for read in zucai_reads
        if read.get("match_id")
    }
    read_by_match.update(
        {
            str(read["match_id"]): read
            for read in jczq_reads
            if read.get("match_id")
        }
    )
    # 重叠场的义务按足彩侧 id 排（_keep_scheduled_identity），而 Read 落在竞彩侧 id 上：
    # 两个 id 都认，行按义务那一侧的 id 记。2026-10-12 之前这里只认竞彩侧 id，重叠场
    # 从不进 rows → F9 义务永不履行（10-10 丢 11、10-11 丢 2、10-12 丢 8），sweep 每小时报红。
    alias = (
        _scheduled_zucai_alias(k, data_dir, day=resolved_day, issue=issue) if issue else {}
    )
    rows: list[dict] = []
    selected_reads: list[dict] = []
    for target in matches_for_population(
        "both", day=resolved_day, issue=issue, data_dir=data_dir
    ):
        match_id = target["match_id"]
        duty_match_id = match_id if match_id in kickoffs else alias.get(match_id)
        read = read_by_match.get(match_id) or (
            read_by_match.get(duty_match_id) if duty_match_id else None
        )
        if read is None or duty_match_id is None:
            continue
        selected_reads.append({**read, "match_no": target.get("match_no")})
        rows.append(
            {
                **target,
                "match_id": duty_match_id,
                "prior": read.get("prior"),
                "belief": read.get("belief"),
                "judgment_tier": read.get("judgment_tier") or "price_only",
                **balance_row(read),
            }
        )
    if not rows:
        _fail("并集场次没有可登记的 Read")

    outcomes = (
        _official_zucai_outcomes(data_dir, issue, zucai_reads) if issue else None
    )
    ledger = balance_ledger(selected_reads, outcomes=outcomes)
    ledger_hash = hashlib.sha256(
        json.dumps(
            {"rows": rows, "ledger": ledger},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    payload = {"issue": issue, "day": resolved_day, "rows": rows, **ledger}
    artifact = day_dir / "balance.json"
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if artifact.exists() and artifact.read_text(encoding="utf-8") == text:
        # 同内容重跑：幂等键只含账本 hash，而 captured_at 每次不同，重登记会撞键
        typer.echo(f"F9 天平无变化（已登记）\n  → {artifact}")
        return
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(text, encoding="utf-8")

    now = _now()
    _, duty_fingerprint = _duty_schedule_context(k)
    balance_match_kickoffs = _jczq_match_kickoffs(data_dir, resolved_day)
    _run(
        k.rsi_actions.schedule_duties,
        ScheduleDutiesRequest(
            day=resolved_day,
            earliest_kickoff=kickoff,
            issue=issue,
            match_kickoffs=balance_match_kickoffs,
            population_match_kickoffs=population_kickoffs,
            idempotency_key=(
                f"rsi-balance-sched:{issue or resolved_day}:{duty_fingerprint}:"
                + _schedule_targets_fingerprint(
                    kickoff, balance_match_kickoffs, population_kickoffs
                )
            ),
            requested_at=now,
            **_SYSTEM,
        ),
    )
    raw = artifact.read_bytes()
    for row, read in zip(rows, selected_reads, strict=True):
        match_id = row["match_id"]
        tier = str(row["judgment_tier"])
        actual = None
        if outcomes is not None:
            for key in (read.get("match_id"), read.get("match_no")):
                if key is not None and str(key) in outcomes:
                    actual = outcomes[str(key)]
                    break
        qualified_n = int(bool(row["moved"] and actual is not None))
        _run(
            k.rsi_actions.fulfill_duty,
            FulfillDutyRequest(
                exp_id="F9",
                duty_name="balance-ledger",
                day=resolved_day,
                artifact_path=str(artifact),
                artifact_bytes=raw,
                n_rows=qualified_n,
                population_stratum="pooled",
                judgment_tier_hist={tier: 1},
                captured_at=now,
                earliest_kickoff=kickoffs[match_id],
                match_id=match_id,
                idempotency_key=(
                    "rsi-ful:F9:balance-ledger:v3:"
                    f"{resolved_day}:{match_id}:{ledger_hash}"
                ),
                requested_at=now,
                **_SYSTEM,
            ),
        )
    right = ledger["direction_right_n"]
    wrong = ledger["direction_wrong_n"]
    direction = "未开奖" if right is None else f"方向 {right}/{wrong}"
    typer.echo(
        f"F9 天平 {ledger['n_moved']}/{ledger['n_matches']} 拨动 · "
        f"平均偏移 {ledger['mean_abs_shift_pp']:.2f}pp · {direction}\n"
        f"  → {artifact}"
    )


@rsi_app.command("price-band")
def price_band(
    day: str = _DAY, issue: str | None = _ISSUE, data_dir: Path = _DATA_DIR
) -> None:
    """Write one mechanical opening-to-current price observation per match (JCZQ + 足彩)."""
    from nutmeg.decision.price_band import (
        write_price_band_artifacts,
        write_zucai_price_band_artifacts,
    )

    k = _kernel(data_dir)
    captured = _now()
    if issue is None:
        # sweep 只渲染 --day：足彩期号从当天已排的 F5 实例里取（schedule --issue 写进去的）
        with OntologyUnitOfWork(k.engine) as uow:
            rows = uow.rsi.duty_instances_for_day("F5:price-band-observation", day)
        issues = sorted({row.issue for row in rows if row.issue})
    else:
        issues = [issue]
    lines: list[str] = []
    try:
        report = write_price_band_artifacts(
            day=day,
            data_dir=data_dir,
            captured_at=captured.isoformat(timespec="seconds"),
        )
        lines.append(
            f"price-band {day}: written={report['written']} "
            f"missing_opening={report['missing_opening']}"
        )
    except ValueError as exc:
        if not issues:
            _fail(str(exc))
        lines.append(f"price-band {day}: 竞彩跳过（{exc}）")
    kickoffs = _jczq_match_kickoffs(data_dir, day)
    for one in issues:
        try:
            z = write_zucai_price_band_artifacts(
                issue=one,
                day=day,
                data_dir=data_dir,
                captured_at=captured.isoformat(timespec="seconds"),
            )
        except ValueError as exc:
            _fail(str(exc))
        lines.append(
            f"price-band {one}: written={z['written']} "
            f"missing_opening={z['missing_opening']}"
        )
        kickoffs = {**_zucai_match_kickoffs(data_dir, one), **kickoffs}
    day_dir = data_dir / "jczq" / "daily" / day
    for artifact in sorted(day_dir.glob("price-band-*.json")):
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        match_id = str(payload.get("match_id") or "")
        kickoff = kickoffs.get(match_id)
        if not match_id or kickoff is None:
            continue
        with OntologyUnitOfWork(k.engine) as uow:
            instance = uow.rsi.duty_instance(
                "F5:price-band-observation", day, match_id
            )
        if instance is None or instance.fulfilled_at is not None:
            continue
        raw = artifact.read_bytes()
        _run(
            k.rsi_actions.fulfill_duty,
            FulfillDutyRequest(
                exp_id="F5",
                duty_name="price-band-observation",
                day=day,
                artifact_path=str(artifact),
                artifact_bytes=raw,
                n_rows=1,
                population_stratum=None,
                judgment_tier_hist={"price_only": 1},
                captured_at=captured,
                earliest_kickoff=kickoff,
                match_id=match_id,
                idempotency_key=(
                    f"rsi-ful:F5:price-band-observation:{day}:{match_id}:"
                    f"{hashlib.sha256(raw).hexdigest()[:16]}"
                ),
                requested_at=captured,
                **_SYSTEM,
            ),
        )
    for line in lines:
        typer.echo(line)


@rsi_app.command("team-load")
def team_load(day: str = _DAY, data_dir: Path = _DATA_DIR) -> None:
    """F16（2026-10-09）：写当天两渠道损耗台账，并为已排的逐场义务履约。

    与 price-band 同一模式；已开球的场不调用履约（开球后写的不是前瞻，每小时巡检重跑也不该
    往观测链里塞非前瞻版本）。F16 没登记 / 当天没排义务时只写台账。"""
    from nutmeg.decision.team_load import write_day_ledgers

    k = _kernel(data_dir)
    captured = _now()
    out = write_day_ledgers(data_dir, day, now=captured.isoformat(timespec="seconds"))
    paths = [p for p in [out["jczq"], *out["zucai"].values()] if p]
    fulfilled = 0
    for path in paths:
        raw = Path(path).read_bytes()
        for row in (json.loads(raw).get("rows") or {}).values():
            match_id, kickoff = row.get("match_id"), row.get("kickoff")
            if not match_id or not kickoff or datetime.fromisoformat(kickoff) <= captured:
                continue
            with OntologyUnitOfWork(k.engine) as uow:
                instance = uow.rsi.duty_instance("F16:team-load-ledger", day, match_id)
            if instance is None or instance.fulfilled_at is not None:
                continue
            _run(k.rsi_actions.fulfill_duty, FulfillDutyRequest(
                exp_id="F16", duty_name="team-load-ledger", day=day,
                artifact_path=str(path), artifact_bytes=raw, n_rows=1,
                population_stratum=None, judgment_tier_hist={"price_only": 1},
                captured_at=captured, earliest_kickoff=kickoff, match_id=match_id,
                idempotency_key=(f"rsi-ful:F16:team-load-ledger:{day}:{match_id}:"
                                 f"{hashlib.sha256(raw).hexdigest()[:16]}"),
                requested_at=captured, **_SYSTEM))
            fulfilled += 1
    typer.echo(f"team-load {day}: 台账 {len(paths)} 份，履约 {fulfilled} 场")


@rsi_app.command("grade")
def grade(exp: str = _EXP, mode: str = _MODE, data_dir: Path = _DATA_DIR,
          samples: Path = _SAMPLES_OPT, registry_dir: Path = _REGISTRY_DIR) -> None:
    """Run an experiment's deterministic grading adapter."""
    from nutmeg.decision.rsi_grading import PROSPECTIVE_ADAPTERS
    from nutmeg.decision.rsi_loop import MONITORS
    from nutmeg.decision.rsi_prereg import base_exp_id, registry_role
    from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL

    role = registry_role(registry_dir, exp)
    if role == "display_only":
        typer.echo(f"{exp} 展示中（预筛过地板但 |效应| <10pp）：只做分析包列，不结账")
        return
    base = base_exp_id(exp)          # epoch 副本沿用原实验的适配器
    k = _kernel(data_dir)
    with OntologyUnitOfWork(k.engine) as uow:
        e = uow.rsi.experiment(exp)
        deployment = uow.rsi.latest_deployment(exp) if e is not None else None
        settled = [v for v in (uow.rsi.verdicts(exp) if e is not None else [])
                   if v.criterion_snapshot.get("protocol") == VERDICT_PROTOCOL]
    if e is None:
        _fail(f"{exp} 未登记")
    if deployment is not None and deployment.decision == "retire":
        typer.echo(f"{exp} 已退役（{deployment.decided_at[:10]}），不再结账")
        return
    if settled and exp not in MONITORS and role != "monitor":
        last = settled[-1]
        typer.echo(f"{exp} 已结账（{VERDICT_PROTOCOL}）→ {last.verdict} @ {last.decided_at[:10]}，"
                   "不再结账（非监测实验）")
        return
    if exp.startswith("CR"):
        # 人群假说（2026-10-07）：判据在登记原件里（trigger/crowd_bias/窗口），内核只存冻结指纹。
        from nutmeg.decision.crowd_model import grade_crowd
        from nutmeg.ontology.rsi.models import frozen_hash

        doc_path = Path(registry_dir) / f"{exp}.json"
        if not doc_path.exists():
            _fail(f"{exp} 登记原件不在 {doc_path}")
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        if frozen_hash(doc) != e.frozen_hash:
            _fail(f"{exp} 原件与内核冻结指纹不符——改判据请走 rsi amend")
        if mode not in ("replay", "prospective"):
            _fail(f"{exp} 只支持 --mode replay|prospective")
        g = grade_crowd(doc, Path(data_dir) / "zucai", mode=mode)
    elif base in PROSPECTIVE_ADAPTERS and base not in ("G1", "N0") and mode == "prospective":
        # N0 是 F14b 的噪音地板，沿用 F14b 的入选行，不另立样本账（2026-10-25）
        from nutmeg.decision import rsi_samples

        with rsi_samples.locked(samples):
            ledger = rsi_samples.load(samples)
            g, events = rsi_samples.grade(ledger, exp, _corpus_rows(), PROSPECTIVE_ADAPTERS[base],
                                          window=e.window,
                                          at=_now().isoformat(timespec="seconds"))
            if events:
                rsi_samples.save(samples, ledger)
        if events:
            kinds: dict[str, int] = {}
            for event in events:
                kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
            typer.echo(f"{exp} 样本账：" + "、".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    elif base in PROSPECTIVE_ADAPTERS:
        rows = _corpus_rows()
        g = PROSPECTIVE_ADAPTERS[base](rows, window=e.window)
    else:
        _fail(f"{exp} 的结账适配器尚未接入（replay_spec.harness={e.replay_spec})")
    f = Falsifier.from_dict(e.falsifier)
    with OntologyUnitOfWork(k.engine) as uow:
        latest = uow.rsi.latest_grade(exp, mode=mode, stratum=g.stratum)
    if latest is not None and _same_grade(latest, g):
        # 输入与结果都没变：每日闭环重跑时这是常态。2026-10-19 前键只含 inputs_hash——
        # 适配器改了照样重放旧 grade、输入 A→B→A 时判决读到 B；现在比对最新一份再决定插不插。
        typer.echo(f"{exp} [{mode}] 输入未变（{g.inputs_hash[:16]}），沿用已有 grade")
    else:
        now = _now()
        _run(k.rsi_actions.grade_experiment, GradeExperimentRequest(
            exp_id=exp, mode=mode, stratum=g.stratum, n_cum=g.n_cum,
            metric_value_pp=g.metric_value_pp, ci_low_pp=g.ci_low_pp, ci_high_pp=g.ci_high_pp,
            cost_axis_pp=g.cost_axis_pp, as_of_policy=g.as_of_policy, computed_by=g.computed_by,
            inputs_hash=g.inputs_hash,
            idempotency_key=f"rsi-grade:{exp}:{mode}:{g.inputs_hash[:16]}:{now.isoformat()}",
            requested_at=now, **_SYSTEM))
    with OntologyUnitOfWork(k.engine) as uow:
        floor_note = _n0_floor_note(uow, exp) if mode == "prospective" else ""
    typer.echo(f"{exp} [{mode}] n={g.n_cum}  残差 {g.metric_value_pp:+.2f}pp  "
               f"CI[{g.ci_low_pp:+.2f}, {g.ci_high_pp:+.2f}]  距 n_min {max(0, f.n_min - g.n_cum)}"
               + floor_note)


def _n0_floor_note(uow, exp: str) -> str:
    """F14b 的结账文本并排 N0 噪音地板（2026-10-26）：N0 与 F14b 同窗同入选行，
    metric = 观测 − 地板 p97.5，>0 才算过地板。只对 F14b 生效；N0 还没 grade 时不加。"""
    if exp != "F14b":
        return ""
    n0 = uow.rsi.latest_grade("N0", mode="prospective", stratum="pooled")
    if n0 is None:
        return ""
    passed = n0.metric_value_pp > 0
    return (f"  ‖ N0 地板 CI[{n0.ci_low_pp:+.1f},{n0.ci_high_pp:+.1f}] "
            f"{'过' if passed else '不过'}地板（n={n0.n_cum} 同窗）")


def _same_grade(row, g) -> bool:
    return (row.inputs_hash == g.inputs_hash and row.computed_by == g.computed_by
            and row.n_cum == g.n_cum
            and all(abs(float(a) - float(b)) < 1e-9 for a, b in (
                (row.metric_value_pp, g.metric_value_pp), (row.ci_low_pp, g.ci_low_pp),
                (row.ci_high_pp, g.ci_high_pp))))


@rsi_app.command("samples")
def samples_cmd(exp: str | None = _EXP_OPT, retract: str | None = _RETRACT,
                reason: str | None = _REASON_OPT, by: str | None = _BY_OPT,
                samples: Path = _SAMPLES_OPT) -> None:
    """样本账：各实验冻结成员数与漂移事件；--retract 由人剔除一个成员（留痕）。"""
    from nutmeg.decision import rsi_samples

    if retract:
        if not exp or not reason or not by:
            _fail("--retract 须同时给 --exp、--reason、--by")
        with rsi_samples.locked(samples):
            ledger = rsi_samples.load(samples)
            try:
                gone = rsi_samples.retract(ledger, exp, retract, reason=reason, by=by,
                                           at=_now().isoformat(timespec="seconds"))
            except KeyError as exc:
                _fail(str(exc))
            rsi_samples.save(samples, ledger)
        typer.echo(f"{exp} 剔除 {gone['key']}（{reason}，{by}）")
        return
    ledger = rsi_samples.load(samples)
    for name, info in rsi_samples.summary(ledger).items():
        if exp and name != exp:
            continue
        kinds = "、".join(f"{k} {v}" for k, v in sorted(info["events"].items())) or "无"
        typer.echo(f"{name}: 成员 {info['members']}  剔除 {info['retracted']}  事件 {kinds}")
    if exp:
        for event in [e for e in ledger["events"] if e["exp"] == exp][-20:]:
            detail = f"  {json.dumps(event['detail'], ensure_ascii=False)}" if event.get(
                "detail") else ""
            typer.echo(f"  {event['at'][:16]}  {event['kind']:<16} {event['key']}{detail}")


@rsi_app.command("verdict")
def verdict(exp: str = _EXP, data_dir: Path = _DATA_DIR,
            registry_dir: Path = _REGISTRY_DIR) -> None:
    """按冻结判据判 falsified / survived / inconclusive（系统身份；未到期拒绝）。

    协议 v2（2026-10-19）：在首次 n ≥ n_min 的结算 grade 上判一次；已结账再调 → 拒绝。
    role=display_only / monitor（2026-10-26）不判决。"""
    from nutmeg.decision.rsi_prereg import registry_role

    role = registry_role(registry_dir, exp)
    if role in ("display_only", "monitor"):
        why = "展示中不结账" if role == "display_only" else "监测只 grade 不判决"
        _fail(f"{exp} role={role}：{why}")
    k = _kernel(data_dir)
    now = _now()
    _run(k.rsi_actions.record_verdict, RecordVerdictRequest(
        exp_id=exp, idempotency_key=f"rsi-verdict-v2:{exp}:{now.isoformat()}",
        requested_at=now, **_SYSTEM))
    with OntologyUnitOfWork(k.engine) as uow:
        v = uow.rsi.latest_verdict(exp)
        g = uow.rsi.grade(v.grade_id)
        floor_note = _n0_floor_note(uow, exp)
    typer.echo(f"{exp} → {v.verdict}（结算 n={g.n_cum} CI[{g.ci_low_pp:+.2f},{g.ci_high_pp:+.2f}]"
               f" @ {g.graded_at[:10]}；判据快照 {v.criterion_snapshot}）" + floor_note)


_KEEP_DUTIES = typer.Option(False, "--keep-duties",
                            help="退役但义务照跑（观察仪产物另有读者；理由里写明谁在读）")


@rsi_app.command("deploy")
def deploy(exp: str = _EXP, reason: str = _REASON, rule: str | None = _RULE, hold: bool = _HOLD,
           retire: bool = _RETIRE, extend: str | None = _EXTEND,
           keep_duties: bool = _KEEP_DUTIES,
           by: str = _BY,
           data_dir: Path = _DATA_DIR) -> None:
    """上线 / 搁置 / 废止 / 延续（只许人）。"""
    decision = "hold" if hold else "retire" if retire else "extend" if extend else "deploy"
    if keep_duties and decision != "retire":
        _fail("--keep-duties 只配 --retire")
    k = _kernel(data_dir)
    _run(k.rsi_actions.approve_deployment, ApproveDeploymentRequest(
        exp_id=exp, decision=decision, reason=reason, rule_id=rule, adjudication_ref=None,
        extend_to_exp_id=extend, acted_by=by, keep_duties=keep_duties,
        idempotency_key=f"rsi-deploy:{exp}:{decision}:{_now().date()}",
        requested_at=_now(), **_HUMAN))
    typer.echo(f"{exp} → {decision}" + (f" (rule {rule})" if rule else "")
               + ("（义务照跑）" if keep_duties else ""))


@rsi_app.command("amend")
def amend(exp: str = _EXP, what: str = _WHAT, why: str = _WHY, rule_check: str = _RULE_CHECK,
          mechanism_note: str | None = _MECHANISM_NOTE, by: str = _BY,
          data_dir: Path = _DATA_DIR) -> None:
    """追加修正案（人）。碰冻结字段的修改不走这里——另立新实验。"""
    k = _kernel(data_dir)
    _run(k.rsi_actions.amend_experiment, AmendExperimentRequest(
        exp_id=exp, what=what, why=why, rule_check=rule_check, mechanism_note=mechanism_note,
        touches={}, acted_by=by,
        idempotency_key=f"rsi-amend:{exp}:{hashlib.sha256(what.encode()).hexdigest()[:12]}",
        requested_at=_now(), **_HUMAN))
    typer.echo(f"{exp} 修正案已追加")


weights_app = typer.Typer(help="T13 因子权重通路：只出提案，不写权重（改权重仍只许 rsi deploy）")
rsi_app.add_typer(weights_app, name="weights")


def _factor_registry():
    import importlib.util

    path = Path(__file__).resolve().parents[3] / "experiments" / "factor_registry.py"
    spec = importlib.util.spec_from_file_location("factor_registry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_W_FACTOR = typer.Option(None, "--factor", help="因子 id；不给则 --all")
_W_ALL = typer.Option(False, "--all")
_W_CORPUS = typer.Option(None, "--corpus", help="默认 experiments/corpus-v2.json")
_W_NPERM = typer.Option(1000, "--n-perm")
_W_LOG = typer.Option(False, "--log", help="追加结论到 experiments/attempts.log")


@weights_app.command("propose")
def weights_propose(
    factor: str | None = _W_FACTOR,
    all_factors: bool = _W_ALL,
    corpus: Path | None = _W_CORPUS,
    n_perm: int = _W_NPERM,
    log: bool = _W_LOG,
) -> None:
    """按冻结的变更规则对因子出提案（propose_change / propose_zero / hold）。⛔不写权重。"""
    if not factor and not all_factors:
        _fail("需要 --factor <id> 或 --all")
    registry_mod = _factor_registry()
    registry = registry_mod.load_registry()
    problems = registry_mod.validate(registry)
    if problems:
        _fail("因子注册表无效：" + "; ".join(problems))
    from experiments.noise_floor import _load_corpus

    rows = _load_corpus(corpus or registry_mod.ROOT / "experiments" / "corpus-v2.json")
    ids = [f["factor_id"] for f in registry["factors"]] if all_factors else [factor]
    if factor and factor not in {f["factor_id"] for f in registry["factors"]}:
        _fail(f"未登记的因子 {factor}")
    before = registry_mod.REGISTRY.read_bytes()
    outputs = [registry_mod.propose(registry, fid, rows, n_perm=n_perm) for fid in ids]
    if registry_mod.REGISTRY.read_bytes() != before:
        _fail("propose 改动了注册表——这不该发生")
    for item in outputs:
        typer.echo(json.dumps(item, ensure_ascii=False, sort_keys=True))
    if log:
        from experiments.attempts import log_attempt

        for item in outputs:
            strict = item["strict"]
            log_attempt(
                f"rsi weights propose {item['factor_id']}",
                f"strict n={strict['n']} n_min={item.get('n_min')} n_perm={n_perm}",
                f"obs={strict.get('observed_pp')}pp p={strict.get('p_value')} "
                f"verdict={strict.get('verdict')}",
                f"{item['decision']} → {item['proposed_weight_pp']}pp (not written)",
            )


_L_DATE = typer.Option(None, "--date", help="报告日期，默认今天")
_L_FORCE = typer.Option(False, "--force", help="同日已有报告也重跑")
_L_SKIP = typer.Option(None, "--skip", help="跳过的步骤名，可重复")
_L_DRY = typer.Option(False, "--dry-run", help="只打印每步命令，不执行")


@rsi_app.command("loop")
def loop(
    date: str | None = _L_DATE,
    force: bool = _L_FORCE,
    skip: list[str] | None = _L_SKIP,
    dry_run: bool = _L_DRY,
    data_dir: Path = _DATA_DIR,
) -> None:
    """每日闭环：补采 → 语料 → 前瞻结账 → 判决 → 因子提案 → 假设 → 实力 → 记分牌 → 报告。

    只编排、只追加：不写权重、不改规则、不登记、不部署；人类动作只进报告。
    """
    from nutmeg.decision.rsi_loop import (
        STEP_ORDER,
        LoopContext,
        default_runner,
        planned_commands,
        run_loop,
    )

    unknown = sorted(set(skip or ()) - set(STEP_ORDER))
    if unknown:
        _fail(f"未知步骤 {unknown}；可用：{', '.join(STEP_ORDER)}")
    ctx = LoopContext(
        root=Path(__file__).resolve().parents[3],
        data_dir=Path(data_dir).expanduser().resolve(),
        date=date or _now().date().isoformat(),
        runner=default_runner,
        skip=frozenset(skip or ()),
    )
    if dry_run:
        for name, commands in planned_commands(ctx).items():
            flag = "skip" if name in ctx.skip else "run"
            typer.echo(f"[{flag}] {name}")
            for cmd in commands:
                typer.echo("    " + " ".join(cmd))
        return
    report = run_loop(ctx, force=force)
    if report is None:
        typer.echo(f"{ctx.date} 已有报告，跳过（--force 重跑）：{ctx.out_dir / f'{ctx.date}.md'}")
        return
    typer.echo(f"RSI 闭环 {report.date}：{len(report.steps)} 步，失败 {len(report.failed_steps)}")
    for action in report.human_actions:
        typer.echo(f"  待人：{action}")
    typer.echo(f"报告 {ctx.out_dir / (report.date + '.md')}")
    if report.failed_steps:
        raise typer.Exit(code=1)


def _evidence_label(e, v, d, g, f) -> str:
    from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL

    if d is not None and d.decision == "retire":
        return "退役"
    if v is not None and v.criterion_snapshot.get("protocol") == VERDICT_PROTOCOL:
        if v.criterion_snapshot.get("expired"):
            return "测不出（到期）"
        return {"survived": "实证", "falsified": "已证伪",
                "inconclusive": "测不出"}.get(v.verdict, v.verdict)
    return f"未证 {g.n_cum if g else 0}/{f.n_min}"


@rsi_app.command("columns")
def columns(data_dir: Path = _DATA_DIR, registry_dir: Path = _REGISTRY_DIR) -> None:
    """分析包各列的实证状态（2026-10-19）：登记出口写了 `packet_column:<列>` 的实验 →
    实证 / 已证伪 / 测不出 / 未证 n/n_min / 退役。分析包 §0 原样抄这一行。"""
    from nutmeg.decision.rsi_prereg import load_registry_doc

    by_column: dict[str, list[str]] = {}
    k = _kernel(data_dir)
    with OntologyUnitOfWork(k.engine) as uow:
        for path in sorted(Path(registry_dir).glob("*.json")):
            if path.name.startswith("_"):
                continue
            doc = load_registry_doc(path)
            cols = sorted({a.split(":", 1)[1] for a in (doc.get("exits") or {}).values()
                           if a.startswith("packet_column:")})
            e = uow.rsi.experiment(doc["exp_id"]) if cols else None
            if e is None:
                continue
            f = Falsifier.from_dict(e.falsifier)
            label = _evidence_label(
                e, uow.rsi.latest_verdict(e.exp_id), uow.rsi.latest_deployment(e.exp_id),
                uow.rsi.latest_grade(e.exp_id, mode="prospective", stratum=f.stratum), f)
            for col in cols:
                by_column.setdefault(col, []).append(f"{e.exp_id} {label}")
    if not by_column:
        typer.echo("列实证：（没有登记出口指向分析包的实验）")
        return
    typer.echo("列实证：" + " ｜ ".join(f"{col} {'·'.join(v)}"
                                       for col, v in sorted(by_column.items()))
               + "（未证的列只是展示或纪律，不是有实证的判据）")


@rsi_app.command("status")
def status(exp: str | None = _EXP_OPT, data_dir: Path = _DATA_DIR,
           registry_dir: Path = _REGISTRY_DIR) -> None:
    """一屏：状态 / n_cum / CI / 距 falsifier / gaps / 下一期义务。"""
    from nutmeg.decision.rsi_loop import GRADED_EXPERIMENTS, UNGRADED
    from nutmeg.decision.rsi_prereg import base_exp_id, registry_role
    from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL

    k = _kernel(data_dir)
    now_iso = _now().isoformat(timespec="seconds")
    unplaced: list[str] = []
    with OntologyUnitOfWork(k.engine) as uow:
        exps = [uow.rsi.experiment(exp)] if exp else uow.rsi.experiments()
        for e in exps:
            if e is None:
                _fail(f"{exp} 未登记")
            f = Falsifier.from_dict(e.falsifier)
            g = uow.rsi.latest_grade(e.exp_id, mode="prospective", stratum=f.stratum)
            v = uow.rsi.latest_verdict(e.exp_id)
            d = uow.rsi.latest_deployment(e.exp_id)
            settled = v is not None and v.criterion_snapshot.get("protocol") == VERDICT_PROTOCOL
            retired = d is not None and d.decision == "retire"
            role = registry_role(registry_dir, e.exp_id)
            if not (settled or retired or e.exp_id.startswith("CR") or role == "display_only"
                    or base_exp_id(e.exp_id) in GRADED_EXPERIMENTS or e.exp_id in UNGRADED):
                unplaced.append(e.exp_id)
            st = project_status(n_observations=uow.rsi.count_observations(e.exp_id),
                                latest_prospective_n=g.n_cum if g else 0, n_min=f.n_min,
                                latest_verdict=v.verdict if v else None,
                                latest_deployment=d.decision if d else None)
            if retired and str(d.reason or "").startswith("epoch_closed"):
                st = "epoch_closed"
            elif role == "display_only" and st == "registered":
                st = "展示中"
            gaps = uow.rsi.gaps(e.exp_id, now=now_iso)
            # n 与判决同源：有 grade 就显示 grade 的 n_cum（判决只认它）。2026-10-03 前
            # F5/F9 显示的是观测行数——F5 显示 148/120 像已到期，判决却按 n_cum=37 拒绝。
            # 没有 grade 的覆盖率实验（R0/R1）才按前瞻观测行数显示。
            obs_n = uow.rsi.prospective_n_rows(e.exp_id, window=e.window, stratum=f.stratum)
            display_n = g.n_cum if g else obs_n
            line = f"{e.exp_id:6} {st:13} n={display_n:>4}/{f.n_min}"
            if g and obs_n and obs_n != display_n:
                line += f"（观测 {obs_n} 行，不计入 n）"
            if g:
                line += (f"  CI[{g.ci_low_pp:+.1f},{g.ci_high_pp:+.1f}]"
                         f" 距falsifier {g.distance_to_falsifier_pp:+.1f}pp")
            if settled:
                sg = uow.rsi.grade(v.grade_id)
                line += (f"  ‖ v2 结账 {v.verdict}：n={sg.n_cum} "
                         f"CI[{sg.ci_low_pp:+.1f},{sg.ci_high_pp:+.1f}] @ {sg.graded_at[:10]}")
            if e.exp_id in UNGRADED:
                line += f"  ‖ 不结账：{UNGRADED[e.exp_id]}"
            if role == "monitor":
                line += "  ‖ 监测：只 grade 不判决"
            elif role == "display_only":
                line += "  ‖ 展示中：预筛过地板、|效应| <10pp，只做分析包列"
            if retired and st == "epoch_closed":
                line += f"  ‖ {d.reason}"
            if g:
                line += _n0_floor_note(uow, e.exp_id)
            if gaps:
                line += f"  gaps={gaps}"
            typer.echo(line)
            orphan_counts: dict[str, int] = {}
            for observation in uow.rsi.observations(e.exp_id):
                if observation.population_stratum == f.stratum:
                    continue
                actual = observation.population_stratum
                orphan_counts[actual] = orphan_counts.get(actual, 0) + 1
            for actual, count in sorted(orphan_counts.items()):
                typer.echo(
                    f"orphan: {e.exp_id} {count} 条观测 stratum={actual}，而 "
                    f"falsifier.stratum={f.stratum}（不计入 n）"
                )
        pending = [
            duty
            for duty in uow.rsi.all_duties()
            if duty.status == "pending_instrument"
            and (exp is None or duty.exp_id == exp)
        ]
        for duty in pending:
            typer.echo(f"pending: {duty.duty_id}（待实现采集器）")
    for exp_id in unplaced:
        typer.echo(f"⚠️未接结账：{exp_id} 未退役、未结账，却既不在结账清单也不在不结账清单"
                   "（nutmeg/decision/rsi_loop.py）")
