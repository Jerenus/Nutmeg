"""账房（2026-10-01 定位：目标函数＝少亏多少 + 证伪了几条）。

月报五块：① 本月净值 vs 空仓（记分牌 tickets，分竞彩/足彩）与止损线；② 探索预算用量
（betslips 里 note 以 `EXP:` 开头的实购票）；③ 主指标「实际 vs 规则 v3 vs 空仓」（gym 按 Read
belief 回放本月竞彩板面日）；④ 判断力主/次指标最新结账（F14b/F10 主，F9/F17/F18/K2/CR2 次）；
⑤ 实验判决计数（survived / falsified / 未到期）。只读，不写判断。
"""
from __future__ import annotations

import calendar
import json
from datetime import date as _date
from pathlib import Path

from nutmeg.decision.bankroll import (
    MONTHLY_STOP_LOSS_YUAN,
    STOP_LOSS_HISTORY,
    month_net,
    stop_loss_on,
    ticket_day,
)

EXP_PREFIX = "EXP:"
EXP_BUDGET_PER_DAY = 30
# 2026-10-19 判决协议 v2：F14 证伪由 F14b 接替；G1/F15/F13/F5 退役；F14/F11 留在次表看判决
PRIMARY = ("F14b", "F10")
SECONDARY = ("F9", "F17", "F18", "K2", "CR2", "F14", "F11")
# 宪法三个主指标之一（Dream 2026-10-04 退役后由 gym 承接）：实际出票 vs 规则 v3 vs 空仓
RULE_V3_POLICIES = (("real", "实际出票"), ("jczq_rule_v3", "规则 v3"), ("flat", "空仓"))
# 足彩的同一面镜子（2026-10-06）：人在初稿上改出来的票 vs 机器初稿（处方忠实）vs 空仓
DRAFT_POLICIES = (("real", "实际出票"), ("zucai_draft", "机器初稿"), ("flat", "空仓"))


def exploration_spend(data_dir: Path, month: str) -> dict:
    path = Path(data_dir) / "betslips.jsonl"
    rows: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            slip = json.loads(line)
            note = str(slip.get("note") or "")
            if not slip.get("purchased") or not note.startswith(EXP_PREFIX):
                continue
            if str(slip.get("placed_at") or "")[:7] != month:
                continue
            rows.append({"slip_id": slip.get("slip_id"),
                         "exp": note[len(EXP_PREFIX):].split()[0],
                         "stake": float(slip.get("stake_yuan") or 0),
                         "placed_at": slip.get("placed_at")})
    return {"slips": rows, "stake": round(sum(r["stake"] for r in rows), 2)}


def _scoreboard_tickets(data_dir: Path) -> dict:
    sb = {}
    try:
        sb = json.loads((Path(data_dir) / "scoreboard.json").read_text(encoding="utf-8"))
    except OSError:
        pass  # 没有记分牌＝还没结算过；坏了的记分牌照样抛，不把全部票读成「待结」
    return sb.get("tickets") or {}


def _ledger_floor(tickets: dict) -> tuple[str | None, str | None]:
    """记分牌 tickets 的起点：(竞彩最早日 YYYY-MM-DD, 足彩最小期号)。比起点早的票在 tickets
    之前的散文账里结过（2026-09 的 26122/26126/26128 与 09-25 前竞彩），不是「待结」。"""
    jczq = sorted(f"{k[5:9]}-{k[9:11]}-{k[11:13]}" for k in tickets
                  if k.startswith("jczq-") and len(k) == 13 and k[5:].isdigit())
    zucai = sorted(k for k in tickets if k.isdigit())
    return (jczq[0] if jczq else None), (zucai[0] if zucai else None)


def _pre_ledger(slip, floor: tuple[str | None, str | None]) -> bool:
    jczq_from, zucai_from = floor
    if slip.channel == "jczq":
        return jczq_from is not None and str(slip.placed_at)[:10] < jczq_from
    issue = str(getattr(slip, "issue", "") or "")
    return zucai_from is not None and issue.isdigit() and issue < zucai_from


def _settled_rows(data_dir: Path) -> dict[str, dict]:
    """记分牌 tickets 里结构化的逐票行（slip_id → {stake, payout}）。"""
    settled: dict[str, dict] = {}
    for ticket in _scoreboard_tickets(data_dir).values():
        if not isinstance(ticket, dict):
            continue
        for row in ticket.get("slips") or []:
            # 记分牌早期条目（26131 等）的 slips 是文字描述，不是结构化行：跳过
            if isinstance(row, dict) and row.get("id"):
                settled[str(row["id"])] = row
    return settled


def _month_slips(data_dir: Path, month: str) -> list:
    from nutmeg.decision.betslip import load_slips

    return [s for s in load_slips(data_dir) if s.purchased and str(s.placed_at)[:7] == month]


def _slip_stake(slip, row: dict | None) -> float:
    if row is not None and row.get("stake") is not None:
        return float(row["stake"])            # 已结算：以记分牌的注金为准（与账房同口径）
    try:
        return float(slip.stake_yuan)
    except Exception:  # noqa: BLE001 —— 旧票缺过关方式
        return 0.0


def _is_pending(row: dict | None) -> bool:
    """记分牌还没给这张票派奖＝待结。"""
    return row is None or row.get("payout") is None


def _add(bucket: dict, slip, settled: dict[str, dict]) -> None:
    bucket["n"] += 1
    row = settled.get(slip.slip_id)
    bucket["stake"] += _slip_stake(slip, row)
    if _is_pending(row):
        bucket["pending"] += 1
    else:
        bucket["payout"] += float(row["payout"])


def pending_ledger(data_dir: Path, month: str) -> dict:
    """本月实购、记分牌尚无派奖的票（待结）：{n, stake, slips:[{slip_id, issue, stake}]}。

    「实质余量」把它们按注金全损计（2026-10-26 Tier 1 #6）：26149 两张 8/9 还没官方派奖时
    账房报「余 ¥766」、实际只剩 ¥78；26150 三张 ¥768 同样在账外。余量先算待结票，不再两套数。
    早于 tickets 起点的票（`_ledger_floor`）不算待结，只在 `pre_ledger` 里计数（2026-10-29：
    9 月 21 张散文账旧票被读成永久待结，账房 9 月「实质」点虚降 ¥2,928）。"""
    settled = _settled_rows(Path(data_dir))
    floor = _ledger_floor(_scoreboard_tickets(Path(data_dir)))
    rows, old = [], 0
    for slip in _month_slips(Path(data_dir), month):
        if not _is_pending(settled.get(slip.slip_id)):
            continue
        if _pre_ledger(slip, floor):
            old += 1
            continue
        rows.append({"slip_id": slip.slip_id, "issue": getattr(slip, "issue", None),
                     "stake": _slip_stake(slip, settled.get(slip.slip_id))})
    return {"n": len(rows), "stake": round(sum(r["stake"] for r in rows), 2), "slips": rows,
            "pre_ledger": old}


def _close(bucket: dict) -> dict:
    bucket["net"] = round(bucket["payout"] - bucket["stake"], 2)
    return bucket


def deviation_ledger(data_dir: Path, month: str) -> dict:
    """人相对初稿的偏离，按理由结账：登记簿里带 deviation 的实购票 × 记分牌 tickets 的派奖。

    理由写于票内最早开球之后的（2026-10-06）单列 `after_kickoff`，不进按理由的净值——
    看过结果再写的理由是回看，拿它给理由类记功过会把运气记成判断。"""
    data_dir = Path(data_dir)
    slips = [s for s in _month_slips(data_dir, month) if s.deviation]
    settled = _settled_rows(data_dir)
    by_reason: dict[str, dict] = {}
    late = {"n": 0, "stake": 0.0, "payout": 0.0, "pending": 0, "slips": []}
    for slip in slips:
        if slip.deviation_after_kickoff:
            _add(late, slip, settled)
            late["slips"].append(f"{slip.slip_id}（{slip.deviation}）")
            continue
        bucket = by_reason.setdefault(slip.deviation, {"n": 0, "stake": 0.0, "payout": 0.0,
                                                       "pending": 0, "predictions": []})
        _add(bucket, slip, settled)
        if slip.prediction:
            bucket["predictions"].append(f"{slip.slip_id}: {slip.prediction[:60]}")
    for bucket in by_reason.values():
        _close(bucket)
    return {"by_reason": by_reason, "n": len(slips), "after_kickoff": _close(late)}


def vetoed_ledger(data_dir: Path, month: str) -> dict:
    """审票否决（V1/V2）之后仍买的票（2026-10-06）：登记时随票入账的审票结论 × 派奖。

    否决不拦登记（登记是事实）；这一行是镜子——每月看一次「不听否决」花了多少、回来多少。"""
    data_dir = Path(data_dir)
    settled = _settled_rows(data_dir)
    vetoed = {"n": 0, "stake": 0.0, "payout": 0.0, "pending": 0, "codes": {}}
    unknown = 0
    for slip in _month_slips(data_dir, month):
        review = (slip.diagnosis or {}).get("review")
        if review is None:
            unknown += 1                       # 2026-10-06 之前登记的票没存审票结论
            continue
        if not review.get("vetoed"):
            continue
        _add(vetoed, slip, settled)
        for code in review.get("codes") or []:
            vetoed["codes"][code] = vetoed["codes"].get(code, 0) + 1
    out = _close(vetoed)
    out["unrecorded"] = unknown
    return out


def experiment_board(data_dir: Path) -> dict:
    """内核 rsi 表 → {exp_id: {n, metric_pp, ci, verdict, …}}；内核不可达 → {"_error": …}。"""
    try:
        from nutmeg.config.settings import AppSettings
        from nutmeg.ontology import build_ontology_kernel
        from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

        kernel = build_ontology_kernel(AppSettings(data_dir=Path(data_dir).resolve()))
        kernel.initialize()
        out: dict[str, dict] = {}
        from nutmeg.decision.rsi_loop import MONITORS
        from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL

        with OntologyUnitOfWork(kernel.engine) as uow:
            for exp in uow.rsi.experiments():
                stratum = str((exp.falsifier or {}).get("stratum") or "pooled")
                grade = uow.rsi.latest_grade(exp.exp_id, mode="prospective", stratum=stratum)
                verdict = uow.rsi.latest_verdict(exp.exp_id)
                settled = (verdict is not None and exp.exp_id not in MONITORS
                           and verdict.criterion_snapshot.get("protocol") == VERDICT_PROTOCOL)
                if settled:
                    # 已结账（协议 v2）：显示判决所依的结算 grade；监测实验（F9）照旧看最新读数
                    grade = uow.rsi.grade(verdict.grade_id) or grade
                ci = None
                if grade:
                    ci = [round(grade.ci_low_pp, 2), round(grade.ci_high_pp, 2)]
                out[exp.exp_id] = {
                    "layer": exp.layer, "tier": exp.tier,
                    "n": grade.n_cum if grade else 0,
                    "n_min": int((exp.falsifier or {}).get("n_min") or 0),
                    "metric_pp": round(grade.metric_value_pp, 2) if grade else None,
                    "ci": ci,
                    "verdict": verdict.verdict if verdict else None,
                }
        return out
    except Exception as exc:  # noqa: BLE001 —— 账房不能因内核故障整页空白
        return {"_error": repr(exc)[:200]}


def rule_v3_board(data_dir: Path, month: str) -> dict:
    """本月竞彩板面日按 Read belief 回放三条策略（2026-10-05 补上：此前没有任何地方记这个主指标）。
    规则 v3 是竞彩规则，所以只放竞彩；实际出票也只取竞彩票，足彩在净值块里。gym 不可用 → _error。"""
    try:
        from nutmeg.gym.board import list_days
        from nutmeg.gym.policy import Ctx
        from nutmeg.gym.run import run_gym

        days = [d for d in list_days(Path(data_dir)) if d.startswith(month)]
        result = run_gym(data_dir=Path(data_dir), policies=[p for p, _ in RULE_V3_POLICIES],
                         days=days, issues=[], ctx=Ctx(belief_source="read"),
                         run_id=f"account-{month}")
    except Exception as exc:  # noqa: BLE001 —— 账房不能因回放故障整页空白
        return {"_error": repr(exc)[:200]}
    out: dict = {"days": len(days)}
    for policy, label in RULE_V3_POLICIES:
        row = result.per_policy.get(policy) or {}
        out[policy] = {"label": label, "slips": row.get("slips", 0), "stake": row.get("stake", 0),
                       "net": row.get("net", 0.0), "roi": row.get("roi", 0.0),
                       "keys": row.get("keys", 0), "pending": row.get("pending", 0)}
    return out


def _issue_month(data_dir: Path, issue: str) -> str:
    try:
        doc = json.loads((Path(data_dir) / "zucai" / f"{issue}-issue.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(doc.get("sale_deadline") or "")[:7]


def draft_board(data_dir: Path, month: str) -> dict:
    """本月足彩期次回放：实际出票 vs 机器初稿（`zucai_draft`，帽 ¥400 任九）vs 空仓。

    人性账（2026-10-06）：9 月有处方的 6 期配对里，真票 −4,043、初稿 −423（evidence
    2026-10-05-training-pool §7）。两边都不套月度止损（比的是票面，不是止损）。

    另给两项（2026-10-29 Task 7.3）：by_issue＝逐期 {issue, day, real, draft}（gym ledger 按期加总；
    该期该策略有一行未结 → None；没有行＝没出票 → 0.0；day＝`ticket_day`，与实际曲线同一口径）；
    curve＝反事实累计线（`draft_curve`）：竞彩照实际、足彩逐期换成机器初稿，不套止损。"""
    try:
        from nutmeg.gym.board import list_issues
        from nutmeg.gym.run import run_gym

        issues = [i for i in list_issues(Path(data_dir)) if _issue_month(data_dir, i) == month]
        result = run_gym(data_dir=Path(data_dir), policies=[p for p, _ in DRAFT_POLICIES],
                         days=[], issues=issues, run_id=f"account-draft-{month}",
                         stop_loss=10**9)
        points = daily_curve(data_dir, month)["points"]
    except Exception as exc:  # noqa: BLE001 —— 账房不能因回放故障整页空白
        return {"_error": repr(exc)[:200]}
    out: dict = {"issues": len(issues)}
    for policy, label in DRAFT_POLICIES:
        row = result.per_policy.get(policy) or {}
        out[policy] = {"label": label, "slips": row.get("slips", 0), "stake": row.get("stake", 0),
                       "net": row.get("net", 0.0), "roi": row.get("roi", 0.0),
                       "keys": row.get("keys", 0), "pending": row.get("pending", 0)}
    by_issue = []
    for issue in issues:
        row = {"issue": issue, "day": ticket_day(issue, data_dir)}
        for policy, field in (("real", "real"), ("zucai_draft", "draft")):
            nets = [r.get("net") for r in result.ledger
                    if r.get("issue") == issue and r.get("policy") == policy]
            row[field] = None if None in nets else round(float(sum(nets)), 2)
        by_issue.append(row)
    out["by_issue"] = sorted(by_issue, key=lambda r: (r["day"] or "", r["issue"]))
    out["curve"] = draft_curve(points, out["by_issue"])
    return out


def draft_curve(points: list[dict], by_issue: list[dict]) -> list[dict]:
    """反事实累计线 [{day, net}]：cf(d) = 实际(d) + Σ_{期日 ≤ d}（初稿净 − 实际净）。

    实际(d)＝`daily_curve` 点里 day ≤ d 的最后一点（没有 → 0）；只计 real 与 draft 都已结算的期
    （有一边 None＝待结，不进差额）。日子＝实际点日 ∪ 期日。两条线的竞彩部分相同，差距全来自
    足彩票面。"""
    deltas = [(r["day"], r["draft"] - r["real"]) for r in by_issue
              if r.get("day") and r.get("real") is not None and r.get("draft") is not None]
    days = sorted({p["day"] for p in points} | {r["day"] for r in by_issue if r.get("day")})
    out = []
    for day in days:
        actual = 0.0
        for p in points:
            if p["day"] <= day:
                actual = p["net"]
        out.append({"day": day,
                    "net": round(actual + sum(d for when, d in deltas if when <= day), 2)})
    return out


def daily_curve(data_dir: Path, month: str, *, today: _date | None = None) -> dict:
    """账房曲线（2026-10-28 第 7 阶段）：{points:[{day, net, line}], moves:[{day, from, to}],
    effective:{day, net}|None}。

    points＝`month_net` 的条目按 `ticket_day` 归日、逐日累计（当日净为 0 的日子不出点），末点＝
    `month_net.net`；line＝当日生效的止损线（正数，画在 −line；10-01 前无线为 None）。
    moves＝当月内止损线换档。
    effective＝「实质」点：已结净值减待结注金（`pending_ledger`）；当月取今天（北京），过去的月
    只在仍有待结票时给、取月末；其余 None。"""
    data_dir = Path(data_dir)
    net = month_net(data_dir, month)
    by_day: dict[str, float] = {}
    for key, value in net["entries"]:
        day = ticket_day(key, data_dir) or ""
        by_day[day] = by_day.get(day, 0.0) + value
    points, total = [], 0.0
    for day in sorted(by_day):
        if not by_day[day]:
            continue
        total += by_day[day]
        points.append({"day": day, "net": round(total, 2), "line": stop_loss_on(day)})
    moves = [{"day": since, "from": STOP_LOSS_HISTORY[i - 1][1], "to": value}
             for i, (since, value) in enumerate(STOP_LOSS_HISTORY)
             if i and since[:7] == month]
    if today is None:
        from datetime import datetime

        from nutmeg.decision.bj_time import BJ
        today = datetime.now(BJ).date()
    pending = pending_ledger(data_dir, month)
    this_month, effective = today.strftime("%Y-%m"), None
    if month == this_month or (month < this_month and pending["n"]):
        year, mon = int(month[:4]), int(month[5:7])
        day = (today.isoformat() if month == this_month
               else f"{month}-{calendar.monthrange(year, mon)[1]:02d}")
        effective = {"day": day, "net": round(net["net"] - pending["stake"], 2)}
    return {"points": points, "moves": moves, "effective": effective}


def month_report(data_dir: Path, month: str, *, with_draft: bool = True,
                 with_rule_v3: bool = True) -> dict:
    """两块 gym 回放（沙盒 10 月整份 6.4 s，大头是规则 v3 的 5.8 s，初稿账约 0.2 s）：账房页主接口
    两个都传 False（结果里不出这两个键），初稿账走按需接口。CLI 用默认值，行为不变。"""
    data_dir = Path(data_dir)
    net = month_net(data_dir, month)
    by_channel = {"jczq": 0.0, "zucai": 0.0}
    for key, value in net["entries"]:
        by_channel["jczq" if key.startswith("jczq-") else "zucai"] += value
    spend = exploration_spend(data_dir, month)
    try:
        deviations = deviation_ledger(data_dir, month)
        vetoed = vetoed_ledger(data_dir, month)
        pending = pending_ledger(data_dir, month)
    except Exception as exc:  # noqa: BLE001 —— 两张账缺席要写明，不能读成「0 张」
        deviations = vetoed = {"_error": repr(exc)[:200]}
        pending = {"n": 0, "stake": 0.0, "slips": [], "_error": repr(exc)[:200]}
    effective_net = round(net["net"] - pending["stake"], 2)
    board = experiment_board(data_dir)
    verdicts: dict[str, int] = {}
    for exp, row in board.items():
        if exp.startswith("_"):
            continue
        label = row.get("verdict") or "not_due"
        verdicts[label] = verdicts.get(label, 0) + 1
    report = {
        "month": month, "net": net["net"], "stake": net["stake"],
        "entries": len(net["entries"]), "unknown": net["unknown"],
        "by_channel": {k: round(v, 2) for k, v in by_channel.items()},
        "stop_loss": MONTHLY_STOP_LOSS_YUAN,
        "tripped": net["net"] <= -MONTHLY_STOP_LOSS_YUAN,
        # 实质余量（2026-10-26）：待结票按注金全损计；报余量看这一组，不看上面那组
        "pending": pending, "effective_net": effective_net,
        "effective_room": round(MONTHLY_STOP_LOSS_YUAN + effective_net, 2),
        "effective_tripped": effective_net <= -MONTHLY_STOP_LOSS_YUAN,
        "exploration": spend, "deviations": deviations, "vetoed": vetoed, "experiments": board,
        "verdicts": verdicts,
    }
    if with_rule_v3:
        report["rule_v3"] = rule_v3_board(data_dir, month)
    if with_draft:
        report["draft"] = draft_board(data_dir, month)
    return report


def render_month(report: dict) -> str:
    ch = report["by_channel"]
    brake = ("｜⛔已触发，空仓到月底" if report["tripped"]
             else f"｜余 ¥{report['stop_loss'] + report['net']:,.0f}")
    lines = [f"# 账房 · {report['month']}", "",
             f"**净值 vs 空仓**：{report['net']:+,.0f}（投入 {report['stake']:,.0f}，"
             f"{report['entries']} 条入账；竞彩 {ch['jczq']:+,.0f} / 足彩 {ch['zucai']:+,.0f}）"
             f"｜止损线 −{report['stop_loss']:,}{brake}"]
    pend = report.get("pending") or {"n": 0, "stake": 0.0}
    if pend.get("_error"):
        lines.append(f"**实质余量（含待结票）**：登记簿读不出，待结票未知——{pend['_error']}")
    elif pend["n"]:
        ids = "、".join(str(r["slip_id"]) for r in pend["slips"][:6])
        tail = (f"⛔越线 ¥{-report['effective_room']:,.0f}" if report["effective_tripped"]
                else f"余 ¥{report['effective_room']:,.0f}")
        lines.append(f"**实质余量（含待结票）**：待结 {pend['n']} 张 ¥{pend['stake']:,.0f} "
                     f"按全损计（{ids}）→ {report['effective_net']:+,.0f}｜{tail}")
    else:
        lines.append("**实质余量**：无待结票，同上")
    if report["unknown"]:
        shown = ", ".join(report["unknown"][:6])
        lines.append(f"（{len(report['unknown'])} 条无法归月未计：{shown}）")
    ex = report["exploration"]
    lines += ["", f"**探索预算**：本月 {len(ex['slips'])} 张 EXP 票，¥{ex['stake']:,.0f}"
                  f"（上限 ¥{EXP_BUDGET_PER_DAY}/日；只给预登记实验）"]
    for row in ex["slips"][:10]:
        lines.append(f"  - {row['placed_at']} {row['slip_id']} {row['exp']} ¥{row['stake']:,.0f}")
    if "_error" in (report.get("deviations") or {}):
        lines += ["", "**人的偏离 / 审票否决仍买**：登记簿或记分牌读不出，两张账缺席——"
                      f"{report['deviations']['_error']}"]
    else:
        dev = report.get("deviations") or {"by_reason": {}, "n": 0}
        lines += ["", f"**人的偏离（相对机器初稿，按理由）**：本月 {dev['n']} 张带理由的实购票"]
        for reason, b in sorted(dev["by_reason"].items()):
            pend = f"（待结 {b['pending']}）" if b.get("pending") else ""
            lines.append(f"  - {reason}：{b['n']} 张 投入 ¥{b['stake']:,.0f} "
                         f"净 {b['net']:+,.0f}{pend}")
            for text in b.get("predictions") or []:
                lines.append(f"    · {text}")
        if not dev["by_reason"]:
            lines.append("  - 无（偏离初稿而不登记理由的票不进这张账）")
        late = dev.get("after_kickoff") or {}
        if late.get("n"):
            lines.append(f"  - 开球后才写理由（不计入上面）：{late['n']} 张 "
                         f"投入 ¥{late['stake']:,.0f} 净 {late['net']:+,.0f}："
                         f"{'、'.join(late['slips'][:6])}")
        vt = report.get("vetoed") or {}
        codes = "、".join(f"{c}×{n}" for c, n in sorted((vt.get("codes") or {}).items()))
        lines += ["", f"**审票否决仍买**：本月 {vt.get('n', 0)} 张 投入 ¥{vt.get('stake', 0):,.0f} "
                      f"净 {vt.get('net', 0):+,.0f}" + (f"（{codes}）" if codes else "")
                  + (f"｜待结 {vt['pending']}" if vt.get("pending") else "")
                  + (f"｜{vt['unrecorded']} 张登记时没存审票结论（10-06 前）"
                     if vt.get("unrecorded") else "")]
    rv = report.get("rule_v3") or {}
    lines += ["", f"**主指标：实际出票 vs 规则 v3 vs 空仓**（竞彩，Read belief 回放，"
                  f"本月 {rv.get('days', 0)} 个板面日）", ""]
    if "_error" in rv:
        lines.append(f"回放失败：{rv['_error']}")
    else:
        lines += ["| 口径 | 票数 | 出票日 | 投入 | 净 | ROI | 待结 |",
                  "|---|---|---|---|---|---|---|"]
        for policy, label in RULE_V3_POLICIES:
            row = rv.get(policy) or {}
            lines.append(f"| {label} | {row.get('slips', 0)} | {row.get('keys', 0)} "
                         f"| {row.get('stake', 0):,.0f} | {row.get('net', 0):+,.0f} "
                         f"| {row.get('roi', 0) * 100:+.1f}% | {row.get('pending', 0)} |")
        lines.append("（规则 v3 是平注 ¥2 的决策规则：比的是「该不该出、出什么形状」，"
                     "看 ROI 与相对空仓的符号，不比绝对金额。）")
    dv = report.get("draft") or {}
    lines += ["", f"**足彩：实际出票 vs 机器初稿 vs 空仓**（本月 {dv.get('issues', 0)} 期，"
                  "初稿＝处方忠实任九、帽 ¥400；不套止损）", ""]
    if "_error" in dv:
        lines.append(f"回放失败：{dv['_error']}")
    else:
        lines += ["| 口径 | 票数 | 期数 | 投入 | 净 | ROI | 待结 |",
                  "|---|---|---|---|---|---|---|"]
        for policy, label in DRAFT_POLICIES:
            row = dv.get(policy) or {}
            lines.append(f"| {label} | {row.get('slips', 0)} | {row.get('keys', 0)} "
                         f"| {row.get('stake', 0):,.0f} | {row.get('net', 0):+,.0f} "
                         f"| {row.get('roi', 0) * 100:+.1f}% | {row.get('pending', 0)} |")
        lines.append("（读法：实际减初稿＝这个月「在初稿上改票」的钱；一期一次命中就能翻转，"
                     "看多个月的符号。）")
    board = report["experiments"]
    lines += ["", "**判断力指标（最新前瞻结账）**", "",
              "| 实验 | 层 | n / n_min | 残差 pp | 95% CI | 判决 |", "|---|---|---|---|---|---|"]
    if "_error" in board:
        lines.append(f"| 内核不可达 | — | — | — | — | {board['_error']} |")
    for exp in [*PRIMARY, *SECONDARY]:
        row = board.get(exp)
        if not row:
            continue
        ci = f"[{row['ci'][0]:+.1f}, {row['ci'][1]:+.1f}]" if row["ci"] else "—"
        metric = f"{row['metric_pp']:+.1f}" if row["metric_pp"] is not None else "—"
        tag = "主" if exp in PRIMARY else "次"
        lines.append(f"| {exp}（{tag}） | {row['layer']} | {row['n']} / {row['n_min']} "
                     f"| {metric} | {ci} | {row['verdict'] or '未到期'} |")
    v = report["verdicts"]
    lines += ["", f"**实验判决**：survived {v.get('survived', 0)} · "
                  f"falsified {v.get('falsified', 0)} · 未到期 {v.get('not_due', 0)}",
              "", "> 读法：净值相对空仓是唯一的钱指标；主指标是结构（F14b：表态偏离市场时 vs 市场"
                  " top-k）与热门带（F10），F9 是有害监测（belief≈市场）。判决按登记原文、每个实验"
                  "只判一次。证伪数不是坏消息——它是这套系统的产出。"]
    return "\n".join(lines) + "\n"


def current_month(today: _date | None = None) -> str:
    return (today or _date.today()).strftime("%Y-%m")


def previous_month(today: _date | None = None) -> str:
    first = (today or _date.today()).replace(day=1)
    return (first.replace(year=first.year - 1, month=12) if first.month == 1
            else first.replace(month=first.month - 1)).strftime("%Y-%m")
