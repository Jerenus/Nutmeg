"""账房（2026-10-01 定位：目标函数＝少亏多少 + 证伪了几条）。

月报四块：① 本月净值 vs 空仓（记分牌 tickets，分竞彩/足彩）与止损线；② 探索预算用量
（betslips 里 note 以 `EXP:` 开头的实购票）；③ 判断力主/次指标最新结账（F14/G1/F15/F10/F9）；
④ 实验判决计数（survived / falsified / 未到期）。只读，不写判断。
"""
from __future__ import annotations

import json
from datetime import date as _date
from pathlib import Path

from nutmeg.decision.bankroll import MONTHLY_STOP_LOSS_YUAN, month_net

EXP_PREFIX = "EXP:"
EXP_BUDGET_PER_DAY = 30
PRIMARY = ("F14", "G1", "F15", "F10")
SECONDARY = ("F9", "F13", "F11", "F5", "F3")


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


def deviation_ledger(data_dir: Path, month: str) -> dict:
    """人相对初稿的偏离，按理由结账：登记簿里带 deviation 的实购票 × 记分牌 tickets 的派奖。"""
    data_dir = Path(data_dir)
    try:
        from nutmeg.decision.betslip import load_slips

        slips = [s for s in load_slips(data_dir) if s.purchased and s.deviation
                 and str(s.placed_at)[:7] == month]
    except Exception:  # noqa: BLE001
        return {"by_reason": {}, "n": 0}
    sb = {}
    try:
        sb = json.loads((data_dir / "scoreboard.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    settled: dict[str, dict] = {}
    for ticket in (sb.get("tickets") or {}).values():
        if not isinstance(ticket, dict):
            continue
        for row in ticket.get("slips") or []:
            # 记分牌早期条目（26131 等）的 slips 是文字描述，不是结构化行：跳过
            if isinstance(row, dict) and row.get("id"):
                settled[str(row["id"])] = row
    by_reason: dict[str, dict] = {}
    for slip in slips:
        bucket = by_reason.setdefault(slip.deviation, {"n": 0, "stake": 0.0, "payout": 0.0,
                                                       "pending": 0, "predictions": []})
        bucket["n"] += 1
        row = settled.get(slip.slip_id)
        if row is not None and row.get("stake") is not None:
            stake = float(row["stake"])            # 已结算：以记分牌的注金为准（与账房同口径）
        else:
            try:
                stake = float(slip.stake_yuan)
            except Exception:  # noqa: BLE001 —— 旧票缺过关方式
                stake = 0.0
        bucket["stake"] += stake
        if row is None or row.get("payout") is None:
            bucket["pending"] += 1
        else:
            bucket["payout"] += float(row["payout"])
        if slip.prediction:
            bucket["predictions"].append(f"{slip.slip_id}: {slip.prediction[:60]}")
    for bucket in by_reason.values():
        bucket["net"] = round(bucket["payout"] - bucket["stake"], 2)
    return {"by_reason": by_reason, "n": len(slips)}


def experiment_board(data_dir: Path) -> dict:
    """内核 rsi 表 → {exp_id: {n, metric_pp, ci, verdict, …}}；内核不可达 → {"_error": …}。"""
    try:
        from nutmeg.config.settings import AppSettings
        from nutmeg.ontology import build_ontology_kernel
        from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

        kernel = build_ontology_kernel(AppSettings(data_dir=Path(data_dir).resolve()))
        kernel.initialize()
        out: dict[str, dict] = {}
        with OntologyUnitOfWork(kernel.engine) as uow:
            for exp in uow.rsi.experiments():
                grade = uow.rsi.latest_grade(exp.exp_id, mode="prospective", stratum="pooled")
                verdict = uow.rsi.latest_verdict(exp.exp_id)
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


def month_report(data_dir: Path, month: str) -> dict:
    data_dir = Path(data_dir)
    net = month_net(data_dir, month)
    by_channel = {"jczq": 0.0, "zucai": 0.0}
    for key, value in net["entries"]:
        by_channel["jczq" if key.startswith("jczq-") else "zucai"] += value
    spend = exploration_spend(data_dir, month)
    deviations = deviation_ledger(data_dir, month)
    board = experiment_board(data_dir)
    verdicts: dict[str, int] = {}
    for exp, row in board.items():
        if exp.startswith("_"):
            continue
        label = row.get("verdict") or "not_due"
        verdicts[label] = verdicts.get(label, 0) + 1
    return {
        "month": month, "net": net["net"], "stake": net["stake"],
        "entries": len(net["entries"]), "unknown": net["unknown"],
        "by_channel": {k: round(v, 2) for k, v in by_channel.items()},
        "stop_loss": MONTHLY_STOP_LOSS_YUAN,
        "tripped": net["net"] <= -MONTHLY_STOP_LOSS_YUAN,
        "exploration": spend, "deviations": deviations, "experiments": board,
        "verdicts": verdicts,
    }


def render_month(report: dict) -> str:
    ch = report["by_channel"]
    brake = ("｜⛔已触发，空仓到月底" if report["tripped"]
             else f"｜余 ¥{report['stop_loss'] + report['net']:,.0f}")
    lines = [f"# 账房 · {report['month']}", "",
             f"**净值 vs 空仓**：{report['net']:+,.0f}（投入 {report['stake']:,.0f}，"
             f"{report['entries']} 条入账；竞彩 {ch['jczq']:+,.0f} / 足彩 {ch['zucai']:+,.0f}）"
             f"｜止损线 −{report['stop_loss']:,}{brake}"]
    if report["unknown"]:
        shown = ", ".join(report["unknown"][:6])
        lines.append(f"（{len(report['unknown'])} 条无法归月未计：{shown}）")
    ex = report["exploration"]
    lines += ["", f"**探索预算**：本月 {len(ex['slips'])} 张 EXP 票，¥{ex['stake']:,.0f}"
                  f"（上限 ¥{EXP_BUDGET_PER_DAY}/日；只给预登记实验）"]
    for row in ex["slips"][:10]:
        lines.append(f"  - {row['placed_at']} {row['slip_id']} {row['exp']} ¥{row['stake']:,.0f}")
    dev = report.get("deviations") or {"by_reason": {}, "n": 0}
    lines += ["", f"**人的偏离（相对机器初稿，按理由）**：本月 {dev['n']} 张带理由的实购票"]
    for reason, b in sorted(dev["by_reason"].items()):
        pend = f"（待结 {b['pending']}）" if b.get("pending") else ""
        lines.append(f"  - {reason}：{b['n']} 张 投入 ¥{b['stake']:,.0f} 净 {b['net']:+,.0f}{pend}")
        for text in b.get("predictions") or []:
            lines.append(f"    · {text}")
    if not dev["by_reason"]:
        lines.append("  - 无（偏离初稿而不登记理由的票不进这张账）")
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
              "", "> 读法：净值相对空仓是唯一的钱指标；主指标是结构（F14/G1）与价格带（F15/F10），"
                  "F9 是程度判断（belief≈市场）。证伪数不是坏消息——它是这套系统的产出。"]
    return "\n".join(lines) + "\n"


def current_month(today: _date | None = None) -> str:
    return (today or _date.today()).strftime("%Y-%m")


def previous_month(today: _date | None = None) -> str:
    first = (today or _date.today()).replace(day=1)
    return (first.replace(year=first.year - 1, month=12) if first.month == 1
            else first.replace(month=first.month - 1)).strftime("%Y-%m")
