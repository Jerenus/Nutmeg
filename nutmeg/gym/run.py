"""运行器：逐板面日/逐期跑策略 → 精确结算 → ledger → 汇总。

汇总含净额、ROI、最大回撤、按日 bootstrap CI、相对空仓/最优的 regret、regime 分桶。

月度止损（宪法 §4，−¥3,000）由这里按 gym 自己的月账强制：触发后该策略当月余下的板一律空仓，
ledger 记 `forced_flat`。策略拿到的永远是 `board.visible()`。
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from nutmeg.decision.bankroll import MONTHLY_STOP_LOSS_YUAN
from nutmeg.gym.board import (
    JczqBoard,
    ZucaiIssue,
    list_days,
    list_issues,
    load_jczq_board,
    load_zucai_issue,
)
from nutmeg.gym.payout import check_jczq_legal, settle_jczq, settle_zucai
from nutmeg.gym.policy import Ctx, get

FAV = 0.70


@dataclass
class GymResult:
    run_id: str
    policies: list[str]
    ledger: list[dict] = field(default_factory=list)
    per_policy: dict[str, dict] = field(default_factory=dict)
    regimes: dict[str, dict[str, dict]] = field(default_factory=dict)   # policy → regime → summary
    skipped: dict[str, int] = field(default_factory=dict)
    days: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _month(key: str) -> str:
    return key[:7]


def jczq_regime(board: JczqBoard) -> str:
    """当日 ≥0.70 热门场数：0 / 1 / 2+。"""
    n = 0
    for m in board.matches.values():
        fair = m.closing_fair or m.belief_any
        if fair and max(fair.values()) >= FAV:
            n += 1
    return "fav0" if n == 0 else ("fav1" if n == 1 else "fav2+")


def zucai_regimes(issues: list[ZucaiIssue]) -> dict[str, str]:
    """按任九每注奖金三分位：cold / mid / hot（奖金低＝热板）。"""
    amounts = sorted((z.prizes or {}).get("renjiu", {}).get("stake_amount", 0.0) for z in issues)
    if not amounts:
        return {}
    lo, hi = amounts[len(amounts) // 3], amounts[(2 * len(amounts)) // 3]
    out = {}
    for z in issues:
        amt = (z.prizes or {}).get("renjiu", {}).get("stake_amount", 0.0)
        out[z.issue] = "hot" if amt <= lo else ("mid" if amt <= hi else "cold")
    return out


def run_gym(*, data_dir: Path, policies: list[str], days: list[str] | None = None,
            issues: list[str] | None = None, ctx: Ctx | None = None, out_dir: Path | None = None,
            run_id: str = "gym", stop_loss: int = MONTHLY_STOP_LOSS_YUAN) -> GymResult:
    data_dir = Path(data_dir)
    base = ctx or Ctx()
    ctx = Ctx(cap_jczq_day=base.cap_jczq_day, cap_zucai_slip=base.cap_zucai_slip,
              belief_source=base.belief_source, seed=base.seed,
              extra={**base.extra, "data_dir": data_dir})
    include_history = bool(ctx.extra.get("history"))
    days = days if days is not None else list_days(data_dir, include_history=include_history)
    issues = issues if issues is not None else list_issues(data_dir)
    result = GymResult(run_id=run_id, policies=list(policies), days=list(days), issues=list(issues))
    month_net: dict[tuple[str, str], float] = {}

    def tripped(policy: str, key: str) -> bool:
        return month_net.get((policy, _month(key)), 0.0) <= -stop_loss

    def book(row: dict) -> None:
        result.ledger.append(row)
        if row.get("net") is not None:
            k = (row["policy"], _month(row["key"]))
            month_net[k] = month_net.get(k, 0.0) + row["net"]

    events: list[tuple[str, int, object]] = []
    for day in days:
        try:
            events.append((day, 0, load_jczq_board(data_dir, day, allow_history=include_history)))
        except FileNotFoundError:
            result.skipped["jczq_no_board"] = result.skipped.get("jczq_no_board", 0) + 1
    loaded: list[ZucaiIssue] = []
    for issue in issues:
        try:
            loaded.append(load_zucai_issue(data_dir, issue))
        except FileNotFoundError:
            result.skipped["zucai_no_issue"] = result.skipped.get("zucai_no_issue", 0) + 1
    regimes = zucai_regimes(loaded)
    for zi in loaded:
        events.append(((zi.sale_deadline or zi.issue)[:10], 1, zi))
    # 按真实时间线走：月度止损必须按日期触发，不能先跑完所有竞彩日再跑足彩
    for key, _, obj in sorted(events, key=lambda e: (e[0], e[1])):
        if isinstance(obj, JczqBoard):
            _run_jczq_day(obj, policies, ctx, tripped=tripped, book=book)
        else:
            _run_zucai_issue(obj, key, policies, ctx, tripped=tripped, book=book,
                             regime=regimes.get(obj.issue))
    for name in policies:
        rows = [r for r in result.ledger if r["policy"] == name]
        result.per_policy[name] = summarize(rows, seed=ctx.seed)
        result.regimes[name] = {
            regime: summarize([r for r in rows if r.get("regime") == regime], seed=ctx.seed)
            for regime in sorted({r.get("regime") for r in rows if r.get("regime")})
        }
    flat_net = result.per_policy.get("flat", {}).get("net", 0.0)
    best = max((p["net"] for p in result.per_policy.values()), default=0.0)
    for summary in result.per_policy.values():
        summary["regret_vs_flat"] = summary["net"] - flat_net
        summary["regret_vs_best"] = summary["net"] - best
    if out_dir is not None:
        write_result(result, Path(out_dir))
    return result


def _run_jczq_day(board: JczqBoard, policies: list[str], ctx: Ctx, *, tripped, book) -> None:
    day = board.day
    regime = jczq_regime(board)
    for name in policies:
        pol = get(name)
        if "jczq" not in pol.channels:
            continue
        if tripped(name, day):
            # 止损空仓也要留痕，否则报告里的「止损空仓日」永远是 0
            book({"key": day, "channel": "jczq", "policy": name, "regime": regime,
                  "slip_id": None, "stake": None, "payout": None, "net": None,
                  "legal": None, "forced_flat": True})
            continue
        for slip in pol.decide(board.visible(), ctx):
            reason = check_jczq_legal(slip, board)
            if reason:
                book({"key": day, "channel": "jczq", "policy": name, "regime": regime,
                      "slip_id": slip.slip_id, "stake": None, "payout": None, "net": None,
                      "legal": reason, "forced_flat": False})
                continue
            s = settle_jczq(slip, board)
            payout = s.payout_yuan
            book({"key": day, "channel": "jczq", "policy": name, "regime": regime,
                  "slip_id": slip.slip_id, "stake": slip.stake_yuan, "payout": payout,
                  "net": (payout - slip.stake_yuan) if payout is not None else None,
                  "legal": None, "pending_legs": s.pending_legs, "forced_flat": False})


def _run_zucai_issue(zi: ZucaiIssue, key: str, policies: list[str], ctx: Ctx, *, tripped, book,
                     regime: str | None) -> None:
    for name in policies:
        pol = get(name)
        if not ({"renjiu", "shengfucai"} & set(pol.channels)):
            continue
        if tripped(name, key):
            book({"key": key, "issue": zi.issue, "channel": "zucai", "policy": name,
                  "regime": regime, "slip_id": None, "stake": None, "payout": None,
                  "net": None, "legal": None, "forced_flat": True})
            continue
        for slip in pol.decide(zi.visible(), ctx):
            s = settle_zucai(slip, zi)
            payout = s.get("payout")
            book({"key": key, "issue": zi.issue, "channel": slip.channel, "policy": name,
                  "regime": regime, "slip_id": slip.slip_id, "stake": s.get("stake"),
                  "payout": payout,
                  "net": (payout - s["stake"]) if payout is not None else None,
                  "legal": None, "skipped": s.get("skipped_reason"), "forced_flat": False,
                  "first_notes": s.get("first_notes"), "second_notes": s.get("second_notes")})


def summarize(rows: list[dict], *, boots: int = 2000, seed: int = 7) -> dict:
    rows = [r for r in rows if not r.get("forced_flat")] + [r for r in rows if r.get("forced_flat")]
    settled = [r for r in rows if r.get("net") is not None]
    by_key: dict[str, float] = {}
    for r in settled:
        by_key[r["key"]] = by_key.get(r["key"], 0.0) + r["net"]
    daily = [by_key[k] for k in sorted(by_key)]
    stake = sum(r["stake"] for r in settled)
    net = sum(daily)
    rng = random.Random(seed)
    if daily:
        sums = sorted(sum(rng.choice(daily) for _ in daily) for _ in range(boots))
        ci = [sums[int(0.025 * boots)], sums[min(int(0.975 * boots), boots - 1)]]
        p_pos = sum(1 for s in sums if s > 0) / boots
    else:
        ci, p_pos = [0.0, 0.0], 0.0
    return {
        "slips": len(rows), "settled": len(settled), "stake": round(stake, 2), "net": round(net, 2),
        "roi": round(net / stake, 4) if stake else 0.0, "keys": len(daily),
        "ci": [round(ci[0], 2), round(ci[1], 2)], "p_positive": round(p_pos, 3),
        "max_drawdown": round(max_drawdown(daily), 2),
        "illegal": sum(1 for r in rows if r.get("legal")),
        "pending": sum(1 for r in rows if r.get("net") is None and not r.get("legal")
                       and not r.get("forced_flat")),
        "forced_flat_keys": len({r["key"] for r in rows if r.get("forced_flat")}),
    }


def max_drawdown(daily: list[float]) -> float:
    peak = cum = worst = 0.0
    for x in daily:
        cum += x
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return worst


def write_result(result: GymResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ledger.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in result.ledger), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps({
        "run_id": result.run_id, "policies": result.per_policy, "regimes": result.regimes,
        "skipped": result.skipped, "days": len(result.days), "issues": len(result.issues),
        "day_range": [result.days[0], result.days[-1]] if result.days else None,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir
