"""五动词 CLI 实现(spec §3)+ 日循环三段编排(M2 阶段一收尾)。

命令通过 cli/__init__ 的 @app.command 注册。日循环编排(am/close/settle)只串确定性动词,
**不烤判断**;判读(Read)由主循环 Claude 人工插入(见各 run_decision_* docstring)。
"""
from __future__ import annotations

import logging
from pathlib import Path

# 日循环编排复用阶段一新增的自立动词(fetch/express/report)。在此 import 为模块级名,
# 令编排以裸名调用 → 测试可统一 monkeypatch 本模块属性断言调用顺序。三模块顶层 import
# 都很轻(reportlab/体彩 client 均惰性 import),且都不反向 import verbs,无环。
from nutmeg.decision.express import run_express
from nutmeg.decision.fetch import fetch_day, fetch_zucai
from nutmeg.decision.report import run_report

logger = logging.getLogger(__name__)


def run_sense(run_date: str, output_dir: Path, taken_at: str) -> str:
    # M1:用 sense_day(体彩+欧赔读时快照),欧赔是 CLV 先验锚——非 M0 的体彩-only。
    from nutmeg.decision.sense import sense_day
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = sense_day(run_date, output_dir=output_dir,
                  taken_at=taken_at, store=store)
    # 实体种子幂等落库(Tier 2):read 时 Claude 从 store 读联赛/球队画像
    from nutmeg.decision.entities import seed_entities_if_empty
    seeded = seed_entities_if_empty(store)
    msg = f"decision-sense {run_date}: 入库 {n} 场 Match+体彩/欧赔 Snapshot"
    if seeded:
        msg += f" | 实体种子落库 {seeded} 条"
    return msg


def run_backfill(run_date: str, output_dir: Path, made_at: str) -> str:
    # 判读收尾:未判场补市场基线 shadow(belief=prior)。顺序纪律:须在 decision-read 之后。
    from nutmeg.decision.read_ingest import backfill_shadows
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = backfill_shadows(store, run_date=run_date, made_at=made_at)
    return f"decision-backfill {run_date}: 补 {n} 条市场基线 shadow"


def run_read_ingest(reads_file: Path, output_dir: Path) -> str:
    import json

    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.store import DecisionStore

    payloads = json.loads(Path(reads_file).read_text(encoding="utf-8"))
    store = DecisionStore(Path(output_dir) / "decision")
    # 词典：已落库 Factor 优先,否则种子
    factors = store.load(_factor_cls()) or load_seed_factors()
    errs = ingest_reads(payloads, store=store, factors=factors)
    ok = len(payloads) - len(errs)
    msg = f"decision-read: 摄取 {ok}/{len(payloads)} 条 Read"
    if errs:
        msg += " | 拒绝: " + "; ".join(errs)
    return msg


def _factor_cls():
    from nutmeg.decision.ontology import Factor
    return Factor


def run_capture_closing(run_date: str, output_dir: Path, taken_at: str) -> str:
    from nutmeg.decision.closing import capture_closing
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = capture_closing(run_date, output_dir=output_dir, taken_at=taken_at, store=store)
    return f"decision-capture-closing {run_date}: 收盘欧赔快照 {n} 条"


def run_reconcile(run_date: str, output_dir: Path, settled_at: str) -> str:
    from nutmeg.decision.reconcile import settle_day
    from nutmeg.decision.store import DecisionStore
    from nutmeg.services.jczq_results import OkoooJczqResultProvider

    store = DecisionStore(Path(output_dir) / "decision")
    try:
        results = OkoooJczqResultProvider().fetch_results(run_date)
    except Exception:  # noqa: BLE001 — 抓不到赛果 → 全 pending
        results = {}
    n = settle_day(store, run_date=run_date, results=results, settled_at=settled_at)
    return f"decision-reconcile {run_date}: 结算 {n} 条(Read+Ticket)"


def run_sense_zucai(issue: str, output_dir: Path, taken_at: str,
                    zucai_dir: Path) -> str:
    """传统足彩感知:zucai 14场+赔率 → 同一信念层 Match+Snapshot(canonical)。

    决策 store 在 output_dir/decision(与竞彩共库,canonical 去重);
    zucai 源快照(<issue>-issue.json/<issue>-odds*.json)在 zucai_dir。
    """
    from nutmeg.decision.sense_zucai import sense_zucai
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    try:
        n = sense_zucai(issue, output_dir=zucai_dir, taken_at=taken_at, store=store)
    except FileNotFoundError as exc:  # 源快照缺 → 不崩,报清晰
        return f"decision-sense-zucai {issue}: 源快照缺失 — {exc}"
    return f"decision-sense-zucai {issue}: 入库 {n} 场 zucai Match+Snapshot"


_ZUCAI_CODE = {"3": "home", "1": "draw", "0": "away"}


def _zucai_outcomes(issue: str, zucai_dir: Path) -> dict:
    """读 {issue}-issue.json(队名/日期)+ {issue}-outcomes.json(results:{no:code})
    → {canonical_match_id: (outcome_90, score)}。code 3=主胜/1=平/0=客胜
    (zucai.py VALID_CODES);zucai 赛果无比分 → score=None。缺文件抛 FileNotFoundError。"""
    import json

    from nutmeg.decision.identity import canonical_match_id

    base = Path(zucai_dir)
    issue_path = base / f"{issue}-issue.json"
    outcomes_path = base / f"{issue}-outcomes.json"
    if not issue_path.exists():
        raise FileNotFoundError(f"zucai issue 快照缺失: {issue_path}")
    if not outcomes_path.exists():
        raise FileNotFoundError(f"zucai 赛果快照缺失: {outcomes_path}")

    issue_data = json.loads(issue_path.read_text(encoding="utf-8"))
    canon_by_no: dict[int, str] = {}
    for row in issue_data.get("matches") or []:
        no = row.get("match_no")
        date = row.get("match_date")
        if no is None or not date:
            continue
        canon_by_no[int(no)] = canonical_match_id(
            str(row.get("home_team") or ""), str(row.get("away_team") or ""), str(date))

    results = json.loads(outcomes_path.read_text(encoding="utf-8")).get("results") or {}
    outcomes: dict = {}
    for k, code in results.items():
        outcome = _ZUCAI_CODE.get(str(code))
        canonical = canon_by_no.get(int(k))
        if outcome and canonical:
            outcomes[canonical] = (outcome, None)
    return outcomes


def run_reconcile_zucai(issue: str, output_dir: Path, settled_at: str,
                        zucai_dir: Path, outcomes: dict | None = None) -> str:
    """传统足彩结算:zucai 1X2 赛果(3/1/0)→ Settlement(Brier+CLV,canonical 通用)。

    outcomes 可注入(测试/自定义);默认从 zucai_dir 的赛果+期号快照读。
    """
    from nutmeg.decision.reconcile import settle_reads_for_matches
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    if outcomes is None:
        try:
            outcomes = _zucai_outcomes(issue, zucai_dir)
        except FileNotFoundError:  # 赛果未出 → 全跳过(不 clobber)
            outcomes = {}
    n = settle_reads_for_matches(store, outcomes=outcomes, settled_at=settled_at)
    return f"decision-reconcile-zucai {issue}: 结算 {n} 条 Read"


def run_calibrate_panel(output_dir: Path, as_of: str) -> str:
    from nutmeg.decision.calibrate import (
        apply_verdicts,
        participation_precision,
        render_panel,
        run_calibrate,
    )
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    # 幂等纠偏:旧 factors.jsonl 行无 scope(默认 match)→ 按种子对齐(实体层 Task 9)
    from nutmeg.decision.factors import sync_factor_scopes
    sync_factor_scopes(store)
    verdicts = run_calibrate(store, as_of=as_of)
    # 反积累免疫落地:把判决执行成 Factor 状态转换(转正/退休)+ 持久化。
    changes = apply_verdicts(store, verdicts)
    # 参与精度(spec §5 判读核心检验)挂进面板尾部——divergent 是否跑赢 shadow 基线。
    panel = render_panel(verdicts, participation=participation_precision(store))
    out = Path(output_dir) / "decision" / f"calibration-panel-{as_of}.md"
    out.write_text(panel, encoding="utf-8")
    msg = f"decision-calibrate: {len(verdicts)} 因子判决 → {out}"
    if changes["promoted"] or changes["retired"]:
        msg += (f" | 转正 {changes['promoted']} 退休 {changes['retired']}")
    return msg


# ---------------------------------------------------------------------------
# 日循环三段编排(M2 阶段一收尾)—— 映射旧 6 launchd 任务为 am/close/settle 三条。
#
# ⚠️ 编排只串**确定性动词**,绝不含判读(Read)。判读是主循环 Claude 的推理产物,
# 在 am 与 close 之间**人工插入**(decision-read);编排层不烤判断——这是本系统与
# 退役 generator 的根本区别(死规则书 vs 实时判读)。诚实标注见各函数 docstring。
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _compose(header: str, steps: list) -> str:
    """按序跑各步,单步失败只记账不断整日循环(cron 健壮性:best-effort,可见降级)。"""
    lines = [header]
    for label, fn in steps:
        try:
            lines.append(fn())
        except Exception as exc:  # noqa: BLE001 — 单步失败不该拖垮整条日循环
            logger.warning("%s · %s 失败", header, label, exc_info=True)
            lines.append(f"{label}: 失败 — {exc}")
    return "\n".join(lines)


def run_decision_am(run_date: str, output_dir, zucai_dir=None, issue=None) -> str:
    """日循环 · 早段(am):数据入库 + 市场基线。fetch(+可选 zucai)→ sense(+可选 zucai)→ backfill。

    ⚠️ **编排不含判读**:am 只把盘口/欧赔快照入库,并给未判场补市场基线 shadow(belief=prior)。
    主循环 Claude 在 am 与 close 之间**人工插入**判读(decision-read 摄取 Read);close 才据
    判读出票。这样编排层始终确定性,判断永不烤进脚本。
    """
    stamp = _now_iso()
    do_zucai = bool(issue and zucai_dir)
    steps: list = [("fetch", lambda: fetch_day(run_date, output_dir))]
    if do_zucai:
        steps.append(("fetch-zucai", lambda: fetch_zucai(issue, zucai_dir)))
    steps.append(("sense", lambda: run_sense(run_date, output_dir, stamp)))
    if do_zucai:
        steps.append(
            ("sense-zucai", lambda: run_sense_zucai(issue, output_dir, stamp, zucai_dir)))
    steps.append(("backfill", lambda: run_backfill(run_date, output_dir, stamp)))
    return _compose(f"decision-am {run_date} · 数据入库+市场基线(编排不含判读)", steps)


def _express_step(run_date: str, output_dir, stamp: str) -> str:
    """close 的出票步:legs 来自主循环 Claude 判读(daily/<date>/legs.json)。无则空票(合法)。"""
    legs_path = Path(output_dir) / "daily" / run_date / "legs.json"
    if legs_path.exists():
        return run_express(legs_path, "jczq", output_dir, stamp)
    return (f"decision-express: 无 daily/{run_date}/legs.json"
            "(主循环 Claude 未插判读票)→ 空票(合法)")


def run_decision_close(run_date: str, output_dir, *, dispatch: bool = False,
                       dry_run: bool = True) -> str:
    """日循环 · 收盘段(close):收盘捕获 + 出票 + 推日报。capture-closing → express → report。

    ⚠️ express 的 legs 是**主循环 Claude 判读产物**——close 读 daily/<date>/legs.json,
    无该文件即空票(编排不自造腿)。``dispatch``/``dry_run`` 透传给 report(推送闸)。
    """
    stamp = _now_iso()
    steps = [
        ("capture-closing", lambda: run_capture_closing(run_date, output_dir, stamp)),
        ("express", lambda: _express_step(run_date, output_dir, stamp)),
        ("report", lambda: run_report(run_date, output_dir,
                                      dispatch_telegram=dispatch, dry_run=dry_run)),
    ]
    return _compose(f"decision-close {run_date} · 收盘+出票+推日报", steps)


def run_decision_settle(run_date: str, output_dir, *, dispatch: bool = False,
                        dry_run: bool = True, issue=None, zucai_dir=None) -> str:
    """日循环 · 结算段(settle):结算(+可选 zucai)+ 校准 + 复盘日报。

    reconcile(+可选 reconcile-zucai)→ calibrate → report。``dispatch``/``dry_run`` 透传 report。
    """
    stamp = _now_iso()
    do_zucai = bool(issue and zucai_dir)
    steps: list = [("reconcile", lambda: run_reconcile(run_date, output_dir, stamp))]
    if do_zucai:
        steps.append(
            ("reconcile-zucai",
             lambda: run_reconcile_zucai(issue, output_dir, stamp, zucai_dir)))
    steps.append(("calibrate", lambda: run_calibrate_panel(output_dir, run_date)))
    steps.append(("report", lambda: run_report(run_date, output_dir,
                                               dispatch_telegram=dispatch, dry_run=dry_run)))
    return _compose(f"decision-settle {run_date} · 复盘(结算+校准+日报)", steps)
