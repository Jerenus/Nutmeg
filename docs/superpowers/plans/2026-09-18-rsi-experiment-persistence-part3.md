# RSI 过程持久化 Implementation Plan · Part 3（Task 8–12：结账、CLI、读侧、迁移、接线）

> 续 Part 1（Task 1–3）与 Part 2（Task 4–7）。同一份 header/纪律适用。

---

### Task 8: 结账适配器 + 泄漏拒收 + dream 重放（`rsi_grading.py`）

**Files:**
- Create: `nutmeg/decision/rsi_grading.py`
- Test: `tests/decision/test_rsi_grading.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_rsi_grading.py
import json

import pytest

from nutmeg.decision.rsi_grading import (
    GradeResult,
    LeakError,
    bootstrap_residual_pp,
    dream,
    grade_f2_prospective,
    inputs_hash,
)


def _ledger(tmp_path, *, captured="2026-09-15T19:30:05", issue="26126"):
    led = {"issues": {issue: {"prospective": True, "captured_at": captured, "graded_at": "x",
                              "rows": [
        {"no": "1", "bucket": "向主 ≥+0.5", "fair": {"home": 0.50, "draw": 0.26, "away": 0.24},
         "moved_share": 0.9, "actual": "home"},
        {"no": "2", "bucket": "向主 ≥+0.5", "fair": {"home": 0.55, "draw": 0.24, "away": 0.21},
         "moved_share": 1.0, "actual": "draw"},
        {"no": "3", "bucket": "不动 0", "fair": {"home": 0.40, "draw": 0.30, "away": 0.30},
         "moved_share": 0.1, "actual": "away"},
    ]}}}
    p = tmp_path / "ledger.json"; p.write_text(json.dumps(led), encoding="utf-8")
    (tmp_path / f"{issue}-issue.json").write_text(json.dumps({"issue_id": issue, "matches": [
        {"match_no": 1, "kickoff_bj": "2026-09-16T02:00:00"},
        {"match_no": 2, "kickoff_bj": "2026-09-16T03:00:00"}]}), encoding="utf-8")
    return p


def test_bootstrap_residual_is_deterministic_and_brackets_the_point_estimate():
    rows = [{"fair": {"home": 0.5}, "actual": "home"}] * 30 + [{"fair": {"home": 0.5}, "actual": "draw"}] * 10
    r = bootstrap_residual_pp(rows, face="home", seed=7)
    assert r.n == 40 and abs(r.value_pp - 25.0) < 1e-9          # 实开 75% − 期望 50%
    assert r.ci_low_pp <= r.value_pp <= r.ci_high_pp
    assert bootstrap_residual_pp(rows, face="home", seed=7) == r   # 同 seed 同结果


def test_f2_prospective_grade_uses_only_the_primary_bucket_and_hashes_inputs(tmp_path):
    led = _ledger(tmp_path)
    g = grade_f2_prospective(ledger_path=led, zucai_dir=tmp_path, primary_bucket="向主 ≥+0.5")
    assert isinstance(g, GradeResult) and g.n_cum == 2 and g.stratum == "zucai"
    assert g.inputs_hash == inputs_hash(led.read_bytes())
    assert g.as_of_policy == "earliest_kickoff"


def test_rows_captured_after_earliest_kickoff_are_refused_not_dropped(tmp_path):
    led = _ledger(tmp_path, captured="2026-09-16T02:30:00")   # 首场 02:00 已开
    with pytest.raises(LeakError, match="26126"):
        grade_f2_prospective(ledger_path=led, zucai_dir=tmp_path, primary_bucket="向主 ≥+0.5")


def test_dream_ranks_variants_and_reports_how_many_were_tried():
    corpus = [{"gap": g, "fair": {"home": 0.5}, "actual": "home" if g < 12 else "draw"}
              for g in range(0, 24)]

    def harness(rows, variant):
        lo, hi = variant["band"]
        sub = [r for r in rows if lo <= r["gap"] < hi]
        return bootstrap_residual_pp(sub, face="home", seed=1)

    table = dream(corpus, harness, variants=[{"band": (0, 12)}, {"band": (12, 24)}, {"band": (5, 10)}])
    assert table["variants_tried"] == 3
    assert table["ranked"][0]["variant"] == {"band": (0, 12)}          # 最正残差排第一
    assert all("ci_low_pp" in r for r in table["ranked"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_rsi_grading.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.rsi_grading'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/rsi_grading.py
"""结账算数与重放。只算数：判决在 RsiActions.record_verdict（代码按冻结判据），上线在人。

- bootstrap_residual_pp：每行等权、bootstrap 95%CI；单场无权翻转判决（U6）。
- grade_f2_prospective：F2 的前瞻结账——读 F2 ledger 与当期 issue.json，任何一期的
  captured_at 晚于该期最早开球 → LeakError **拒收并点名期号**，不是静默丢弃（U8-④）。
- dream：在冻结语料上重放一族变体，出排序表并记 variants_tried（U8-⑥）。
"""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class LeakError(ValueError):
    """样本来自开球之后——拒收。"""


@dataclass(frozen=True, slots=True)
class ResidualCI:
    n: int
    value_pp: float
    ci_low_pp: float
    ci_high_pp: float


@dataclass(frozen=True, slots=True)
class GradeResult:
    stratum: str
    n_cum: int
    metric_value_pp: float
    ci_low_pp: float
    ci_high_pp: float
    cost_axis_pp: float | None
    as_of_policy: str
    inputs_hash: str
    computed_by: str


def inputs_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def bootstrap_residual_pp(rows: Sequence[dict], *, face: str, seed: int = 7,
                          boots: int = 4000) -> ResidualCI:
    """(实开率 − 平均 fair) × 100，每行等权；CI 为 bootstrap 2.5/97.5 分位。"""
    n = len(rows)
    if n == 0:
        return ResidualCI(0, 0.0, 0.0, 0.0)
    resid = [(1.0 if r["actual"] == face else 0.0) - float(r["fair"][face]) for r in rows]
    point = statistics.fmean(resid) * 100
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(resid) for _ in resid) * 100 for _ in range(boots))
    return ResidualCI(n, point, means[int(0.025 * boots)], means[int(0.975 * boots) - 1])


def _earliest_kickoff(zucai_dir: Path, issue: str) -> datetime | None:
    p = Path(zucai_dir) / f"{issue}-issue.json"
    if not p.exists():
        return None
    kos = [datetime.fromisoformat(m["kickoff_bj"]) for m in json.loads(p.read_text("utf-8"))["matches"]
           if m.get("kickoff_bj")]
    return min(kos) if kos else None


def grade_f2_prospective(*, ledger_path: Path, zucai_dir: Path, primary_bucket: str,
                         computed_by: str = "nutmeg.decision.rsi_grading.grade_f2_prospective") -> GradeResult:
    raw = Path(ledger_path).read_bytes()
    ledger = json.loads(raw)
    rows: list[dict] = []
    for issue, entry in ledger.get("issues", {}).items():
        if not entry.get("prospective", True):
            continue
        ko = _earliest_kickoff(zucai_dir, issue)
        captured = datetime.fromisoformat(entry["captured_at"])
        if ko is not None and captured >= ko:
            raise LeakError(f"期 {issue} 的观察单采于 {captured.isoformat()}，"
                            f"不早于最早开球 {ko.isoformat()}——拒收（不是丢弃）")
        rows.extend(r for r in entry["rows"] if r.get("bucket") == primary_bucket)
    ci = bootstrap_residual_pp(rows, face="home")
    return GradeResult(stratum="zucai", n_cum=ci.n, metric_value_pp=ci.value_pp,
                       ci_low_pp=ci.ci_low_pp, ci_high_pp=ci.ci_high_pp, cost_axis_pp=None,
                       as_of_policy="earliest_kickoff", inputs_hash=inputs_hash(raw),
                       computed_by=computed_by)


Harness = Callable[[Sequence[dict], dict], ResidualCI]


def dream(corpus: Sequence[dict], harness: Harness, *, variants: Sequence[dict]) -> dict:
    """在冻结语料上重放一族变体。只排序、只记数；不产生任何判决。"""
    ranked = []
    for v in variants:
        ci = harness(corpus, v)
        ranked.append({"variant": v, "n": ci.n, "value_pp": ci.value_pp,
                       "ci_low_pp": ci.ci_low_pp, "ci_high_pp": ci.ci_high_pp})
    ranked.sort(key=lambda r: (-r["value_pp"], -r["n"]))
    return {"variants_tried": len(variants), "ranked": ranked,
            "note": "重放结果只产候选，进不了判决（verdict 只读 prospective 档）"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_rsi_grading.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/rsi_grading.py tests/decision/test_rsi_grading.py
git add nutmeg/decision/rsi_grading.py tests/decision/test_rsi_grading.py
git commit -m "feat(rsi): F2 前瞻结账（泄漏拒收并点名期号）+ dream 重放排序"
```

---

### Task 9: CLI `nutmeg rsi …`

**Files:**
- Create: `nutmeg/interfaces/cli/rsi.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`（底部 import 区按字母序加 `from nutmeg.interfaces.cli import rsi as rsi  # noqa: E402`）
- Test: `tests/test_cli_rsi.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_rsi.py
import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

DOC = {
    "exp_id": "F2", "claim": "c", "mechanism": "m", "tier": "observation", "layer": "judgment",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140", "quota_slot": False, "buckets": ["向主 ≥+0.5"], "rule_ids": [],
    "source_doc": "experiments/prereg-26126-F1c-F2.json", "registered_at": "2026-09-14",
    "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
                "instrument": ["python", "scripts/zucai_f2_observe.py", "record", "--issue", "{issue}"],
                "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json"}],
}


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"; (d / "zucai").mkdir(parents=True)
    (d / "zucai" / "26129-issue.json").write_text(json.dumps({"issue_id": "26129", "matches": [
        {"match_no": 4, "kickoff_bj": "2026-09-19T00:30:00"},
        {"match_no": 1, "kickoff_bj": "2026-09-19T03:00:00"}]}), encoding="utf-8")
    return d


def test_register_schedule_due_status_round_trip(tmp_path):
    d = _data_dir(tmp_path); doc = tmp_path / "F2.json"; doc.write_text(json.dumps(DOC), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    assert "F2" in r.output and "frozen" in r.output
    r = CliRunner().invoke(app, ["rsi", "schedule", "--day", "2026-09-19", "--issue", "26129",
                                 "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(app, ["rsi", "due", "--day", "2026-09-19", "--data-dir", str(d),
                                 "--now", "2026-09-18T20:00:00+08:00"])
    assert "f2-observation" in r.output and "00:30" in r.output
    assert "scripts/zucai_f2_observe.py record --issue 26129" in r.output   # 占位已填
    r = CliRunner().invoke(app, ["rsi", "status", "--data-dir", str(d)])
    assert r.exit_code == 0 and "F2" in r.output and "registered" in r.output


def test_verdict_before_n_min_exits_nonzero_with_the_shortfall(tmp_path):
    d = _data_dir(tmp_path); doc = tmp_path / "F2.json"; doc.write_text(json.dumps(DOC), encoding="utf-8")
    CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "verdict", "--exp", "F2", "--data-dir", str(d)])
    assert r.exit_code == 1 and "prospective" in r.output


def test_register_twice_is_refused(tmp_path):
    d = _data_dir(tmp_path); doc = tmp_path / "F2.json"; doc.write_text(json.dumps(DOC), encoding="utf-8")
    CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "register", str(doc), "--data-dir", str(d)])
    assert r.exit_code == 1 and "已登记" in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_rsi.py -v`
Expected: FAIL — `No such command 'rsi'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/interfaces/cli/rsi.py
"""`nutmeg rsi …`：RSI 实验对象的命令面。每条命令 = 一个 Action，没有绕过 Action 写表的路径。

人 = judge_operator（register/amend/deploy）；系统 = deterministic_system（schedule/fulfill/grade/verdict）。
`rsi verdict` 以系统身份调用——人从终端敲它也只是触发按冻结判据的判定，不是人在判。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
    kos = [m["kickoff_bj"] for m in json.loads(p.read_text("utf-8"))["matches"] if m.get("kickoff_bj")]
    return (min(kos) + "+08:00") if kos else None


@rsi_app.command("register")
def register(doc_path: Path, data_dir: Path = _DATA_DIR) -> None:
    """摄入登记原件（人）。同一 exp_id 二次登记拒绝。"""
    from nutmeg.decision.rsi_prereg import load_registry_doc

    try:
        doc = load_registry_doc(doc_path)
    except ValueError as exc:
        _fail(str(exc))
    k = _kernel(data_dir)
    _run(k.rsi_actions.register_experiment, RegisterExperimentRequest(
        doc=doc, idempotency_key=f"rsi-reg:{doc['exp_id']}:{doc_path.stat().st_mtime_ns}",
        requested_at=_now(), **_HUMAN))
    with OntologyUnitOfWork(k.engine) as uow:
        e = uow.rsi.experiment(doc["exp_id"])
    typer.echo(f"已登记 {e.exp_id}  tier={e.tier} layer={e.layer} population={e.population}\n"
               f"  frozen_hash={e.frozen_hash[:16]}…  duties={len(doc.get('duties') or [])}")


@rsi_app.command("schedule")
def schedule(day: str = typer.Option(..., "--day"), issue: str | None = typer.Option(None, "--issue"),
             data_dir: Path = _DATA_DIR) -> None:
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
def due(day: str = typer.Option(..., "--day"), data_dir: Path = _DATA_DIR,
        now: str | None = typer.Option(None, "--now", help="测试用；默认当前时刻")) -> None:
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
def fulfill(exp: str = typer.Option(..., "--exp"), duty: str = typer.Option(..., "--duty"),
            day: str = typer.Option(..., "--day"), artifact: Path = typer.Option(..., "--artifact"),
            n_rows: int = typer.Option(..., "--n-rows"), stratum: str = typer.Option("zucai", "--stratum"),
            issue: str | None = typer.Option(None, "--issue"), data_dir: Path = _DATA_DIR) -> None:
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
    typer.echo(f"已登记 {exp}/{duty}@{day}  n_rows={n_rows}  "
               f"{'前瞻' if captured.isoformat() < ko else '⚠️非前瞻（该日仍是 gap）'}")


@rsi_app.command("grade")
def grade(exp: str = typer.Option(..., "--exp"), mode: str = typer.Option("prospective", "--mode"),
          data_dir: Path = _DATA_DIR) -> None:
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
        idempotency_key=f"rsi-grade:{exp}:{mode}:{g.inputs_hash[:16]}", requested_at=_now(), **_SYSTEM))
    f = Falsifier.from_dict(e.falsifier)
    typer.echo(f"{exp} [{mode}] n={g.n_cum}  残差 {g.metric_value_pp:+.2f}pp  "
               f"CI[{g.ci_low_pp:+.2f}, {g.ci_high_pp:+.2f}]  距 n_min {max(0, f.n_min - g.n_cum)}")


@rsi_app.command("verdict")
def verdict(exp: str = typer.Option(..., "--exp"), data_dir: Path = _DATA_DIR) -> None:
    """按冻结判据判 falsified / survived / inconclusive（系统身份；未到期拒绝）。"""
    k = _kernel(data_dir)
    _run(k.rsi_actions.record_verdict, RecordVerdictRequest(
        exp_id=exp, idempotency_key=f"rsi-verdict:{exp}:{_now().date()}", requested_at=_now(), **_SYSTEM))
    with OntologyUnitOfWork(k.engine) as uow:
        v = uow.rsi.latest_verdict(exp)
    typer.echo(f"{exp} → {v.verdict}（判据快照 {v.criterion_snapshot}）")


@rsi_app.command("deploy")
def deploy(exp: str = typer.Option(..., "--exp"), reason: str = typer.Option(..., "--reason"),
           rule: str | None = typer.Option(None, "--rule"), hold: bool = typer.Option(False, "--hold"),
           retire: bool = typer.Option(False, "--retire"),
           extend: str | None = typer.Option(None, "--extend", help="另立的新 exp_id"),
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
def amend(exp: str = typer.Option(..., "--exp"), what: str = typer.Option(..., "--what"),
          why: str = typer.Option(..., "--why"), rule_check: str = typer.Option("", "--rule-check"),
          mechanism_note: str | None = typer.Option(None, "--mechanism-note"),
          data_dir: Path = _DATA_DIR) -> None:
    """追加修正案（人）。碰冻结字段的修改不走这里——另立新实验。"""
    k = _kernel(data_dir)
    _run(k.rsi_actions.amend_experiment, AmendExperimentRequest(
        exp_id=exp, what=what, why=why, rule_check=rule_check, mechanism_note=mechanism_note,
        touches={}, idempotency_key=f"rsi-amend:{exp}:{hashlib.sha256(what.encode()).hexdigest()[:12]}",
        requested_at=_now(), **_HUMAN))
    typer.echo(f"{exp} 修正案已追加")


@rsi_app.command("status")
def status(exp: str | None = typer.Option(None, "--exp"), data_dir: Path = _DATA_DIR) -> None:
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
                line += f"  CI[{g.ci_low_pp:+.1f},{g.ci_high_pp:+.1f}] 距falsifier {g.distance_to_falsifier_pp:+.1f}pp"
            if gaps:
                line += f"  gaps={gaps}"
            typer.echo(line)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_rsi.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/interfaces/cli/rsi.py nutmeg/interfaces/cli/__init__.py tests/test_cli_rsi.py
git add nutmeg/interfaces/cli/rsi.py nutmeg/interfaces/cli/__init__.py tests/test_cli_rsi.py
git commit -m "feat(cli): nutmeg rsi——register/schedule/due/fulfill/grade/verdict/deploy/amend/status"
```

---

### Task 10: 读侧三个查询（给②用）

**Files:**
- Modify: `nutmeg/product/repository.py`（import 区加 `from nutmeg.ontology.repository import schema_rsi as sr`；在 `settlements()` 之后加三个方法）
- Test: `tests/product/test_repository_rsi.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/product/test_repository_rsi.py
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.rsi import DutyInstanceRow, DutyRow, ExperimentRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.repository import ProductReadRepository


def test_experiments_timeline_and_duties_due(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db"); run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(ExperimentRow(
            exp_id="F2", claim="c", mechanism="m", tier="observation", layer="judgment",
            population="zucai", min_tier="price_only", window={"issue_from": "26126", "issue_to": "26137"},
            falsifier={"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140, "bound": "ci_upper",
                       "threshold_pp": 2.0, "direction": "lt_means_falsified"},
            stop_rule="s", quota_slot=False, buckets=[], rule_ids=[], replay_spec=None, dream_ref=None,
            variants_tried=None, source_doc="x", registered_at="2026-09-14", frozen_hash="h" * 64,
            created_at="2026-09-18T20:00:00+08:00"))
        uow.rsi.insert_duty(DutyRow(duty_id="F2:obs", exp_id="F2", recurrence="per_day", scope="day",
                                    deadline_rule="earliest_kickoff", instrument=["x", "{issue}"],
                                    artifact_glob="y", description=""))
        uow.rsi.insert_duty_instance(DutyInstanceRow(duty_id="F2:obs", day="2026-09-19", match_id="",
                                                     issue="26129", due_at="2026-09-19T00:30:00+08:00",
                                                     fulfilled_at=None, artifact_path=None, artifact_hash=None))
    repo = ProductReadRepository(engine)
    exps = repo.experiments(as_of="2026-09-18T21:00:00+08:00")
    assert [e["exp_id"] for e in exps] == ["F2"] and exps[0]["status"] == "registered"
    tl = repo.experiment_timeline("F2", as_of="2026-09-18T21:00:00+08:00")
    assert tl[0]["kind"] == "registered" and tl[0]["at"] == "2026-09-18T20:00:00+08:00"
    due = repo.duties_due("2026-09-19", now="2026-09-18T21:00:00+08:00")
    assert [d["duty_id"] for d in due] == ["F2:obs"]
    assert repo.experiments(as_of="2026-09-18T19:00:00+08:00") == []   # 登记之前看不见
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/product/test_repository_rsi.py -v`
Expected: FAIL with `AttributeError: 'ProductReadRepository' object has no attribute 'experiments'`

- [ ] **Step 3: Write minimal implementation**

在 `ProductReadRepository` 的 `settlements()` 之后加：

```python
    # ── RSI 实验（阶段②观察界面的读路径；与工作台同一 as_of 口径）──────────
    def experiments(self, *, as_of: str) -> list[dict]:
        from nutmeg.ontology.repository.rsi import RsiRepository
        from nutmeg.ontology.rsi.models import Falsifier, project_status

        with self._engine.connect() as connection:
            repo = RsiRepository(connection)
            out = []
            for e in repo.experiments():
                if e.created_at > as_of:
                    continue
                f = Falsifier.from_dict(e.falsifier)
                g = repo.latest_grade(e.exp_id, mode="prospective", stratum=f.stratum)
                v = repo.latest_verdict(e.exp_id)
                d = repo.latest_deployment(e.exp_id)
                out.append({
                    "exp_id": e.exp_id, "claim": e.claim, "tier": e.tier, "layer": e.layer,
                    "population": e.population, "registered_at": e.registered_at,
                    "n_min": f.n_min, "n_cum": g.n_cum if g else 0,
                    "ci": [g.ci_low_pp, g.ci_high_pp] if g else None,
                    "distance_to_falsifier_pp": g.distance_to_falsifier_pp if g else None,
                    "verdict": v.verdict if v else None, "deployment": d.decision if d else None,
                    "gaps": repo.gaps(e.exp_id, now=as_of),
                    "status": project_status(
                        n_observations=repo.count_observations(e.exp_id),
                        latest_prospective_n=g.n_cum if g else 0, n_min=f.n_min,
                        latest_verdict=v.verdict if v else None,
                        latest_deployment=d.decision if d else None),
                })
            return out

    def experiment_timeline(self, exp_id: str, *, as_of: str) -> list[dict]:
        """一条实验的全部只追加记录，按时间排成时间线。"""
        with self._engine.connect() as connection:
            rows: list[dict] = []
            e = connection.execute(select(sr.rsi_experiments)
                                   .where(sr.rsi_experiments.c.exp_id == exp_id)).mappings().first()
            if e is None or e["created_at"] > as_of:
                return []
            rows.append({"kind": "registered", "at": e["created_at"], "frozen_hash": e["frozen_hash"]})
            for t, kind, at in ((sr.rsi_observations, "observation", "captured_at"),
                                (sr.rsi_grades, "grade", "graded_at"),
                                (sr.rsi_verdicts, "verdict", "decided_at"),
                                (sr.rsi_deployments, "deployment", "decided_at"),
                                (sr.rsi_amendments, "amendment", "amended_at")):
                for r in connection.execute(select(t).where(t.c.exp_id == exp_id,
                                                            t.c[at] <= as_of)).mappings().all():
                    rows.append({"kind": kind, "at": r[at], **{k: v for k, v in r.items() if k != at}})
            rows.sort(key=lambda r: (r["at"], r["kind"]))
            return rows

    def duties_due(self, day: str, *, now: str) -> list[dict]:
        with self._engine.connect() as connection:
            t = sr.rsi_duty_instances
            rows = connection.execute(select(t).where(t.c.day == day, t.c.fulfilled_at.is_(None),
                                                      t.c.due_at > now)
                                      .order_by(t.c.due_at, t.c.duty_id)).mappings().all()
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/product/test_repository_rsi.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/product/repository.py tests/product/test_repository_rsi.py
git add nutmeg/product/repository.py tests/product/test_repository_rsi.py
git commit -m "feat(rsi): 读侧 experiments/experiment_timeline/duties_due（同 as_of 口径）"
```

（提醒：碰 `nutmeg/product/` 会触发 pre-commit 跑整个 `tests/product/`，数分钟；提交时保证没有别的进程在改文件。）

---

### Task 11: 五份 prereg 归一化摄入

**Files:**
- Create: `experiments/registry/F2.json`、`F1c.json`、`F3.json`、`F4.json`、`F5.json`
- Create: `scripts/rsi_migrate_preregs.py`
- Test: `tests/test_rsi_migrate_preregs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rsi_migrate_preregs.py
import json
from pathlib import Path

from nutmeg.decision.rsi_prereg import load_registry_doc

REG = Path("experiments/registry")


def test_all_five_registry_docs_load_and_keep_their_original_registration_dates():
    docs = {p.stem: load_registry_doc(p) for p in sorted(REG.glob("*.json"))}
    assert set(docs) == {"F1c", "F2", "F3", "F4", "F5"}
    assert docs["F2"]["registered_at"] == "2026-09-14" and docs["F1c"]["registered_at"] == "2026-09-14"
    assert docs["F4"]["registered_at"] == "2026-09-18" and docs["F5"]["registered_at"] == "2026-09-18"
    # 在跑的窗口不重新索引（U9-②）
    assert docs["F2"]["window"] == {"issue_from": "26126", "issue_to": "26137"}
    assert docs["F1c"]["window"] == {"issue_from": "26129", "issue_to": "26140"}
    # 每份都指回旧文件
    for d in docs.values():
        assert Path(d["source_doc"]).exists(), d["source_doc"]
    # F1c/F2 各带一条按日义务；F4/F5 是观察档、无采集义务
    assert [x["name"] for x in docs["F2"]["duties"]] == ["f2-observation"]
    assert [x["name"] for x in docs["F1c"]["duties"]] == ["dispersion-observation"]
    assert docs["F4"]["tier"] == "observation" and not docs["F4"].get("duties")


def test_migration_script_backfills_observations_and_marks_f1c_gaps(tmp_path, monkeypatch):
    import scripts.rsi_migrate_preregs as mig

    d = tmp_path / "data"; (d / "zucai").mkdir(parents=True)
    for issue, ko in (("26126", "2026-09-16T02:00:00"), ("26127", "2026-09-17T02:00:00"),
                      ("26128", "2026-09-18T02:00:00"), ("26129", "2026-09-19T00:30:00")):
        (d / "zucai" / f"{issue}-issue.json").write_text(json.dumps(
            {"issue_id": issue, "matches": [{"match_no": 1, "kickoff_bj": ko}]}), encoding="utf-8")
    ledger = {"issues": {i: {"prospective": True, "captured_at": f"2026-09-{15 + k}T19:30:05",
                             "rows": [{"no": "1", "bucket": "向主 ≥+0.5", "fair": {"home": .5, "draw": .25, "away": .25},
                                       "moved_share": 1, "actual": "home"}]}
                         for k, i in enumerate(("26126", "26127", "26128"))}}
    (tmp_path / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    (tmp_path / "t7-dispersion.json").write_text(json.dumps({"26129": {"1": {}}}), encoding="utf-8")
    report = mig.migrate(data_dir=d, registry_dir=REG, f2_ledger=tmp_path / "ledger.json",
                         dispersion_file=tmp_path / "t7-dispersion.json",
                         now="2026-09-18T20:00:00+08:00")
    assert report["registered"] == ["F1c", "F2", "F3", "F4", "F5"]
    assert report["F2"]["observations"] == 3
    assert report["F1c"]["observations"] == 1
    assert report["F1c"]["gaps"] == ["2026-09-16", "2026-09-17", "2026-09-18"]   # 26125 没有 issue.json 时不造数据
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rsi_migrate_preregs.py -v`
Expected: FAIL — `assert set(docs) == {...}`（registry 目录不存在）

- [ ] **Step 3: Write minimal implementation**

五份登记原件。字段从旧 prereg 搬，`registered_at` 取原登记日，`source_doc` 指回旧文件：

```json
// experiments/registry/F2.json
{
  "exp_id": "F2",
  "claim": "让球线的离散位移（初盘→终盘中位线）朝主队方向移动 → 主胜面残差为正；改线书商占比 = 承诺强度。",
  "mechanism": "改赔率是连续微调、成本近零；改线是把标的换成另一个离散档位，是一次承诺。与已证伪的『赔率位移动量』不是同一个量。",
  "tier": "observation", "layer": "judgment", "population": "zucai", "min_tier": "price_only",
  "window": {"issue_from": "26126", "issue_to": "26137"},
  "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140, "bound": "ci_upper",
                "threshold_pp": 2.0, "direction": "lt_means_falsified"},
  "stop_rule": "12 期累计 n≥140 时结账；期间不得调整阈值、不得改 k、不得中途看结果改口径。",
  "quota_slot": false,
  "buckets": ["向客 ≤-0.25", "不动 0", "向主 +0.25", "向主 ≥+0.5"],
  "rule_ids": [],
  "source_doc": "experiments/prereg-26126-F1c-F2.json",
  "registered_at": "2026-09-14",
  "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
              "instrument": ["uv", "run", "python", "scripts/zucai_f2_observe.py", "record", "--issue", "{issue}"],
              "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json",
              "description": "F2 让球线观察单（最早开球前 12–45 分钟）"}]
}
```

```json
// experiments/registry/F1c.json
{
  "exp_id": "F1c",
  "claim": "150+ 家书商的分歧度越高，模态面（top1）开出率越高于锐盘共识的期望。",
  "mechanism": "⛔无已验证机制。预注册的『分歧=置信度低→向均匀收缩』被证伪（方向相反）；效应集中在书目少的子集，可能是稀薄市场噪音。",
  "tier": "observation", "layer": "judgment", "population": "zucai", "min_tier": "price_only",
  "window": {"issue_from": "26129", "issue_to": "26140"},
  "falsifier": {"metric": "top1_resid_pp_high_dispersion_quartile", "stratum": "zucai", "n_min": 140,
                "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
  "stop_rule": "累计 n≥140 结账；阈值/分档/falsifier 不动。窗口起点由 2026-09-18 修正案从 26126 改为 26129（采集仪从未接上，26125–26128 不可回补）。",
  "quota_slot": false,
  "buckets": ["分歧度 Q1", "分歧度 Q2", "分歧度 Q3", "分歧度 Q4"],
  "rule_ids": [],
  "source_doc": "experiments/prereg-26126-F1c-F2.json",
  "registered_at": "2026-09-14",
  "duties": [{"name": "dispersion-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
              "instrument": ["uv", "run", "python", "scripts/zucai_book_dispersion.py", "--sleep", "1.5"],
              "artifact_glob": ".nutmeg-data/zucai/t7-dispersion.json",
              "description": "F1c 书商分歧度观察单（需先把 {issue} 的 match_id 补进 t7-backfill.json）"}]
}
```

（`instrument` 校验要求含 `{issue}` 或 `{day}` 占位——F1c 的采集仪按 backfill 映射跑、不带期号参数，故 `description` 里写 `{issue}` 不算；把 instrument 改为 `["uv","run","python","scripts/zucai_book_dispersion.py","--sleep","1.5","--issue","{issue}"]` 并在 Task 12 给该脚本加一个只做「把 {issue} 的 match_id 补进 t7-backfill 再采」的 `--issue` 选项。）

```json
// experiments/registry/F3.json
{
  "exp_id": "F3",
  "claim": "policy-top60：top1 ≥60% 的面按固定权重上调，BSS 相对市场为正。",
  "mechanism": "热面被市场低估的校准偏差（在 corpus v2 上足彩 +8.1 / 竞彩 +3.6，竞彩 CI 含 0）。",
  "tier": "deploy_eligible", "layer": "structural", "population": "zucai", "min_tier": "price_only",
  "window": {"issue_from": "26125", "issue_to": "26136"},
  "falsifier": {"metric": "bss_vs_market_pct", "stratum": "zucai", "n_min": 120, "bound": "ci_lower",
                "threshold_pp": 0.0, "direction": "lt_means_falsified"},
  "stop_rule": "n≥120 结账。占用『每期只许 1 个新参数进实盘』配额。",
  "quota_slot": true,
  "buckets": [],
  "rule_ids": [],
  "replay_spec": {"harness": "scripts/zucai_loop.py::evaluate", "corpus": "experiments/corpus-v2.json",
                  "policy_file": "experiments/policy-top60-v1.json"},
  "source_doc": "experiments/prereg-26125-F3.json",
  "registered_at": "2026-09-12"
}
```

```json
// experiments/registry/F4.json
{
  "exp_id": "F4",
  "claim": "审计门（腿级 ERROR + C17 标记≤3）把帽内最大 P(全对) 从声明空间压到合法空间的代价可量化，且该代价与板面 regime 相关。",
  "mechanism": "门是价格纪律：每多一处标记＝在判不动的场次上多排一个更贵的面（26128：31.4%→11.3%→6.9%）。",
  "tier": "observation", "layer": "structural", "population": "zucai", "min_tier": "light_read",
  "window": {"issue_from": "26129", "issue_to": "26140"},
  "falsifier": {"metric": "gate_cost_pp", "stratum": "zucai", "n_min": 8, "bound": "ci_lower",
                "threshold_pp": 0.0, "direction": "gt_means_falsified"},
  "stop_rule": "观察口径，不占配额；8 期后结账，只报告不部署。",
  "quota_slot": false,
  "buckets": [],
  "rule_ids": ["C17"],
  "replay_spec": {"harness": "experiments/exp-strict-space.py", "corpus": ".nutmeg-data/zucai/*-legs-base.json"},
  "source_doc": "experiments/prereg-26129-F4-gate-cost.json",
  "registered_at": "2026-09-18"
}
```

```json
// experiments/registry/F5.json
{
  "exp_id": "F5",
  "claim": "价格带：gap12∈[10,20) 的 top1 残差为负（−7.6pp）；冷面 ≤10% 被高估（−4.8pp）。",
  "mechanism": "corpus v2 上 20 个格 2 个 CI 不含 0 ＝ α=0.05 的随机期望——只入候选，前瞻验证前不得进判读。",
  "tier": "candidate", "layer": "structural", "population": "both", "min_tier": "price_only",
  "window": {"date_from": "2026-09-19", "n_min": 180},
  "falsifier": {"metric": "top1_resid_pp_gap12_10_20", "stratum": "pooled", "n_min": 180, "bound": "ci_upper",
                "threshold_pp": -2.0, "direction": "gt_means_falsified"},
  "stop_rule": "两板各自 n≥90 且合并 n≥180 结账；分层符号相反且 CI 不重叠 → 合并 inconclusive。",
  "quota_slot": false,
  "buckets": ["gap12 [0,5)", "[5,10)", "[10,20)", "[20,+)"],
  "rule_ids": ["C11"],
  "dream_ref": "experiments/exp-price-bands.py@2026-09-18",
  "variants_tried": 20,
  "source_doc": "experiments/prereg-26129-F5-price-bands.json",
  "registered_at": "2026-09-18"
}
```

迁移脚本：

```python
# scripts/rsi_migrate_preregs.py
"""五份旧 prereg 归一化摄入内核 + 回填已有观察。只增不改；可重跑（幂等键按 exp_id）。

- registered_at 取原登记日；
- F2 ledger 里 26126/27/28 → 三条 observation；t7-dispersion 里 26129 → 一条；
- F1c 在 26125–26128 真缺 → 由 schedule + 无 fulfill 自然投影成 gap（不造数据）。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.rsi_prereg import load_registry_doc
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.rsi_actions import (
    FulfillDutyRequest,
    RegisterExperimentRequest,
    ScheduleDutiesRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

HUMAN = dict(actor_id="operator:rsi-migrate", actor_role=ActorRole.JUDGE_OPERATOR)
SYSTEM = dict(actor_id="system:rsi-migrate", actor_role=ActorRole.DETERMINISTIC_SYSTEM)


def _day_of(issue: str, zucai_dir: Path) -> tuple[str, str] | None:
    p = zucai_dir / f"{issue}-issue.json"
    if not p.exists():
        return None
    kos = sorted(m["kickoff_bj"] for m in json.loads(p.read_text("utf-8"))["matches"] if m.get("kickoff_bj"))
    if not kos:
        return None
    ko = kos[0]
    return ko[:10], ko + "+08:00"


def migrate(*, data_dir: Path, registry_dir: Path, f2_ledger: Path, dispersion_file: Path, now: str) -> dict:
    kernel = build_ontology_kernel(AppSettings(data_dir=Path(data_dir).resolve()))
    kernel.initialize()
    zucai_dir = Path(data_dir) / "zucai"
    ts = datetime.fromisoformat(now)
    report: dict = {"registered": []}
    for p in sorted(registry_dir.glob("*.json")):
        doc = load_registry_doc(p)
        with OntologyUnitOfWork(kernel.engine) as uow:
            if uow.rsi.experiment(doc["exp_id"]) is not None:
                report["registered"].append(doc["exp_id"]); continue
        kernel.rsi_actions.register_experiment(RegisterExperimentRequest(
            doc=doc, idempotency_key=f"rsi-migrate-reg:{doc['exp_id']}", requested_at=ts, **HUMAN))
        report["registered"].append(doc["exp_id"])

    # 为 26125–26129 排义务（有 issue.json 的期才排：拿不到开球就不造数据）
    for issue in ("26125", "26126", "26127", "26128", "26129"):
        dk = _day_of(issue, zucai_dir)
        if dk is None:
            continue
        day, ko = dk
        kernel.rsi_actions.schedule_duties(ScheduleDutiesRequest(
            day=day, earliest_kickoff=ko, issue=issue, idempotency_key=f"rsi-migrate-sched:{day}",
            requested_at=ts, **SYSTEM))

    # F2：ledger 里的前瞻期 → observation
    ledger = json.loads(Path(f2_ledger).read_text("utf-8"))
    f2_obs = 0
    for issue, entry in ledger.get("issues", {}).items():
        dk = _day_of(issue, zucai_dir)
        if dk is None or not entry.get("prospective", True):
            continue
        day, ko = dk
        kernel.rsi_actions.fulfill_duty(FulfillDutyRequest(
            exp_id="F2", duty_name="f2-observation", day=day, artifact_path=str(f2_ledger),
            artifact_bytes=json.dumps(entry, ensure_ascii=False).encode(), n_rows=len(entry["rows"]),
            population_stratum="zucai", judgment_tier_hist={"price_only": len(entry["rows"])},
            captured_at=datetime.fromisoformat(entry["captured_at"]).replace(tzinfo=ts.tzinfo),
            earliest_kickoff=ko, idempotency_key=f"rsi-migrate-ful:F2:{day}", requested_at=ts, **SYSTEM))
        f2_obs += 1

    # F1c：t7-dispersion 里有的期 → observation
    disp = json.loads(Path(dispersion_file).read_text("utf-8"))
    f1c_obs = 0
    for issue, cells in disp.items():
        dk = _day_of(issue, zucai_dir)
        if dk is None or issue < "26129":
            continue                        # 26124 及以前不在 F1c 窗口
        day, ko = dk
        kernel.rsi_actions.fulfill_duty(FulfillDutyRequest(
            exp_id="F1c", duty_name="dispersion-observation", day=day, artifact_path=str(dispersion_file),
            artifact_bytes=json.dumps(cells, ensure_ascii=False).encode(), n_rows=len(cells),
            population_stratum="zucai", judgment_tier_hist={"price_only": len(cells)},
            captured_at=datetime.fromisoformat(ko) .replace(tzinfo=ts.tzinfo).replace(hour=19, minute=30),
            earliest_kickoff=ko, idempotency_key=f"rsi-migrate-ful:F1c:{day}", requested_at=ts, **SYSTEM))
        f1c_obs += 1

    with OntologyUnitOfWork(kernel.engine) as uow:
        report["F2"] = {"observations": f2_obs, "gaps": uow.rsi.gaps("F2", now=now)}
        report["F1c"] = {"observations": f1c_obs, "gaps": uow.rsi.gaps("F1c", now=now)}
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path(".nutmeg-data"))
    ap.add_argument("--registry-dir", type=Path, default=Path("experiments/registry"))
    ap.add_argument("--f2-ledger", type=Path, default=Path("experiments/prereg-26126-F2-ledger.json"))
    ap.add_argument("--dispersion-file", type=Path, default=Path(".nutmeg-data/zucai/t7-dispersion.json"))
    a = ap.parse_args()
    rep = migrate(data_dir=a.data_dir, registry_dir=a.registry_dir, f2_ledger=a.f2_ledger,
                  dispersion_file=a.dispersion_file, now=datetime.now().astimezone().isoformat(timespec="seconds"))
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
```

⚠️F1c 的 `captured_at`：t7-dispersion 不记采样时刻，脚本用「该期开球日 19:30」作近似——把这一点写进 `AmendmentRow`：迁移后跑 `uv run nutmeg rsi amend --exp F1c --what "26129 观察时刻为近似值（19:30）" --why "t7-dispersion.json 不记 captured_at" --rule-check "不改判据"`。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rsi_migrate_preregs.py -v`
Expected: 2 passed

- [ ] **Step 5: 对真库跑迁移并核数**

```bash
uv run python scripts/rsi_migrate_preregs.py
uv run nutmeg rsi status
```
Expected：五条实验出现；F2 `n=` 与 ledger 累计一致（26126–26128 三期 ≈ 33 行主格）；F1c `gaps=['2026-09-15','2026-09-16','2026-09-17','2026-09-18']`（26125–26128，以磁盘上存在 issue.json 的期为准）。

- [ ] **Step 6: Commit**

```bash
uv run ruff check scripts/rsi_migrate_preregs.py tests/test_rsi_migrate_preregs.py
git add experiments/registry/F2.json experiments/registry/F1c.json experiments/registry/F3.json experiments/registry/F4.json experiments/registry/F5.json scripts/rsi_migrate_preregs.py tests/test_rsi_migrate_preregs.py
git commit -m "feat(rsi): 五份 prereg 归一化原件 + 迁移脚本（原登记日、真缺记 gap）"
```

---

### Task 12: 接线（备料链 / 观察仪 / RUNBOOK）

**Files:**
- Modify: `nutmeg/interfaces/cli/decision.py`（`zucai_prep` 末尾）
- Modify: `scripts/zucai_f2_observe.py`（`record()` 落盘后）
- Modify: `scripts/zucai_book_dispersion.py`（加 `--issue`，采完后登记）
- Modify: `docs/sop/RUNBOOK.md`
- Test: `tests/decision/test_rsi_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_rsi_wiring.py
"""接线只加一行：备料链跑完 → rsi schedule + due；观察仪落盘 → rsi fulfill。用假 invoker 验参数。"""
from nutmeg.decision.rsi_wiring import after_prep, after_observation_artifact


def test_after_prep_schedules_then_lists_due(tmp_path):
    calls = []
    after_prep(issue="26129", day="2026-09-19", data_dir=tmp_path, invoke=lambda argv: calls.append(argv) or 0)
    assert calls[0][:2] == ["rsi", "schedule"] and "--issue" in calls[0] and "26129" in calls[0]
    assert calls[1][:2] == ["rsi", "due"]


def test_after_observation_artifact_fulfills_with_row_count(tmp_path):
    calls = []
    art = tmp_path / "26129-f2-observation.json"; art.write_text('{"observations": {"1": {}, "2": {}}}')
    after_observation_artifact(exp="F2", duty="f2-observation", issue="26129", day="2026-09-19",
                               artifact=art, n_rows=2, data_dir=tmp_path,
                               invoke=lambda argv: calls.append(argv) or 0)
    assert calls[0][:2] == ["rsi", "fulfill"] and "--n-rows" in calls[0] and "2" in calls[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_rsi_wiring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.rsi_wiring'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/rsi_wiring.py
"""把 RSI 义务接进现有链条的两根线。都是「加一行」，不改被接线方的语义。

失败不抛：备料链与观察仪的主任务不能因为登记失败而失败——但要打印，别静默。
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner


def _cli_invoke(argv: list[str]) -> int:
    from nutmeg.interfaces.cli import app

    result = CliRunner().invoke(app, argv)
    if result.exit_code != 0:
        print(f"⚠️rsi 接线未成功（不影响主任务）：{' '.join(argv)}\n{result.output.strip()[-300:]}")
    return result.exit_code


def after_prep(*, issue: str, day: str, data_dir: Path, invoke=_cli_invoke) -> None:
    invoke(["rsi", "schedule", "--day", day, "--issue", issue, "--data-dir", str(data_dir)])
    invoke(["rsi", "due", "--day", day, "--data-dir", str(data_dir)])


def after_observation_artifact(*, exp: str, duty: str, issue: str, day: str, artifact: Path,
                               n_rows: int, data_dir: Path, invoke=_cli_invoke) -> None:
    invoke(["rsi", "fulfill", "--exp", exp, "--duty", duty, "--day", day, "--issue", issue,
            "--artifact", str(artifact), "--n-rows", str(n_rows), "--data-dir", str(data_dir)])
```

`nutmeg/interfaces/cli/decision.py` 的 `zucai_prep` 末尾（`_cli.typer.echo(result.summary)` 之后）加：

```python
    if result.status == "prepared" and result.issue:
        from nutmeg.decision.rsi_wiring import after_prep

        after_prep(issue=result.issue, day=(run_date or _date.today().isoformat()),
                   data_dir=Path(output_dir).parent)
```
（`_date` 已在该模块内以 `from datetime import date as _date` 引入；若无则加。）

`scripts/zucai_f2_observe.py` 的 `record()` 在 `print(f"观察单 {len(obs)} 场 → {path}")` 之后加：

```python
    from nutmeg.decision.rsi_wiring import after_observation_artifact
    after_observation_artifact(exp="F2", duty="f2-observation", issue=issue,
                               day=(min(kickoffs).date().isoformat() if kickoffs else now.date().isoformat()),
                               artifact=path, n_rows=len(obs), data_dir=Z.parent)
```

`scripts/zucai_book_dispersion.py`：`main()` 加 `ap.add_argument("--issue", default=None, help="先把该期 match_id（取自 <期>-f2-observation.json）补进 t7-backfill 再采，采完登记 F1c 义务")`；`collect()` 前若给了 `--issue`：

```python
def _backfill_issue(issue: str) -> None:
    bf = Z / "t7-backfill.json"
    t7 = json.load(open(bf)) if bf.exists() else {}
    if issue in t7:
        return
    obs = json.loads((Z / f"{issue}-f2-observation.json").read_text("utf-8"))["observations"]
    t7[issue] = {no: {"match_id": r["match_id"], "fair": r["fair"]} for no, r in obs.items()}
    bf.write_text(json.dumps(t7, ensure_ascii=False), "utf-8")
```
并在 `collect()` 结束后：

```python
    if issue:
        from nutmeg.decision.rsi_wiring import after_observation_artifact
        ko = _kickoffs(issue)
        day = min(ko.values()).date().isoformat() if ko else datetime.now().date().isoformat()
        after_observation_artifact(exp="F1c", duty="dispersion-observation", issue=issue, day=day,
                                   artifact=OUT, n_rows=len(done.get(issue, {})), data_dir=Z.parent)
```

RUNBOOK：B0 行末追加「**备料完成后自动 `rsi schedule` + `rsi due`，并按 due 列出的 instrument 执行**（2026-09-18 起）」；在「候选因子观察仪」附录后加一段：

```markdown
> **非决策附录 · RSI 实验对象（2026-09-18）**
> `uv run nutmeg rsi status` 一屏：每条实验的状态 / n_cum / CI / 距 falsifier / gaps / 下一期义务。
> 登记 `rsi register experiments/registry/<id>.json`（原件全冻结，改判据＝另立新 exp_id）；
> `rsi verdict` 由代码按冻结判据判、人不得代判；`rsi deploy` 只许人。重放（`--mode replay` / dream）结果进不了判决。
> 出生事故：F1c 两次断采（08-14 批处理停在 26124；09-18 19:20 才发现采集仪看不见 26129）——义务从此是对象不是散文。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_rsi_wiring.py tests/test_cli_rsi.py -v`
Expected: 全部 passed

- [ ] **Step 5: 活体验证（不碰真判读）**

```bash
uv run nutmeg rsi due --day 2026-09-19        # 应列出 F2/F1c 已 fulfilled → 无待办
uv run nutmeg rsi status                       # 五条实验、F1c 带 gaps
```

- [ ] **Step 6: Commit**

```bash
uv run ruff check nutmeg/decision/rsi_wiring.py nutmeg/interfaces/cli/decision.py scripts/zucai_f2_observe.py scripts/zucai_book_dispersion.py tests/decision/test_rsi_wiring.py
git add nutmeg/decision/rsi_wiring.py nutmeg/interfaces/cli/decision.py scripts/zucai_f2_observe.py scripts/zucai_book_dispersion.py docs/sop/RUNBOOK.md tests/decision/test_rsi_wiring.py
git commit -m "feat(rsi): 接线——备料链自动排义务，观察仪落盘自动登记；RUNBOOK 入册"
```

---

## Self-review（对照 spec）

| spec 章节 | 任务 |
|---|---|
| §4 对象模型 7 类记录 + 字段 | Task 2（表）、3（仓库）、4–6（写入） |
| §4.1 tier/layer/population/min_tier/window/falsifier/frozen_hash/replay_spec/dream_ref | Task 1（枚举、hash、校验）、7（原件校验） |
| §4.2 状态投影、gaps、next_due | Task 1 `project_status`、Task 3 `gaps/pending`、Task 9 `status/due` |
| §5 判定规则十条 | Task 6（prospective-only、n_min、CI、分层、deploy 门）、Task 8（泄漏拒收、等权 bootstrap）、Task 1（inconclusive≠survived） |
| §5.1 权限 | Task 2 种子 + Task 4/6 测试 |
| §6 duty 一生 | Task 5、9、12 |
| §7 Dream-RSI 六条 | ① 属阶段三补丁（本计划外，spec 已注明）；② `replay_spec` + `--mode replay`（Task 4/9）；③ Task 6；④ Task 8；⑤ Task 1/6；⑥ Task 8 `dream` |
| §8 命令面 + 8.1 接线 + 8.2 读侧 | Task 9、12、10 |
| §9 迁移 | Task 11 |
| §10 测试 | 分布在各任务；「两轴不折算」由 GradeRow 无合成字段 + Task 6 `cost_axis_pp` 独立列体现 |
| §11 出口条件 | Task 11 Step 5 + Task 12 Step 5 |

**类型一致性**：`ExperimentRow/DutyRow/DutyInstanceRow/ObservationRow/GradeRow/VerdictRow/DeploymentRow/AmendmentRow` 在 Task 3 定义、4–6/10/11 使用同名同字段；`Falsifier.from_dict/evaluate/distance_pp` 在 Task 1 定义、6/9/10 使用；CLI 选项名 `--exp/--duty/--day/--issue/--artifact/--n-rows/--data-dir` 在 Task 9 定义、12 使用一致。

**已知留白（有意）**：`rsi grade` 只接 F2 适配器；F3/F4/F5 的 harness 经 `replay_spec.harness` 指定但本计划不接——它们的 prospective 结账要等各自的观察产物成形（F3 需 settle 后的 BSS、F4 需候选树、F5 需竞彩深研桥）。`rsi dream` 的 CLI 入口留到接第一个 structural 实验时一起做，避免无消费者的命令。
