"""express — 组合枚举 + 赔率算术 + 预算闸(spec §6)。

预算是配置数据(decision_budget.json)非代码规则(数据>代码版本策略)。
复式注数/组合赔率一律代码算(禁嘴算)。M0 为骨架:算术 + 闸门,不含 PDF/推送。
空仓永远合法。
"""
from __future__ import annotations

import json
import math
from functools import reduce
from importlib import resources

_BUDGET_RESOURCE = "decision_budget.json"


def load_budget() -> dict:
    return json.loads(
        resources.files("nutmeg.data").joinpath(_BUDGET_RESOURCE)
        .read_text(encoding="utf-8")
    )


def renjiu_ticket_count(total: int, pick: int) -> int:
    """任九复式注数 = C(total, pick)。"""
    return math.comb(total, pick)


def parlay_odds(odds: list[float]) -> float:
    """串关组合赔率 = 各腿赔率连乘。"""
    return reduce(lambda a, b: a * b, odds, 1.0)


# ---------------------------------------------------------------------------
# M1.5 express — 已声明投注腿 → Ticket(¥400 框架)。
#
# ⚠️「判断永不烤进脚本」：express 不判断押哪个玩法/哪条腿——那是主循环 Claude 的判读,
# 作为**结构化 legs 传入**。本函数只做确定性算术:按 runbook Phase 5 骨架给各 bucket
# 分配注金上限、parlay 连乘合并赔率、channel 总额超 ¥400 硬顶则按比例缩。禁嘴算。
# ---------------------------------------------------------------------------

# leg.bucket(runbook Phase 5 语义桶)→ decision_budget.json 的 cap 键。
_BUCKET_BUDGET_KEY = {
    "main": "had_modal",      # 主方向单关 ≤¥100
    "hedge": "hhad_cover",    # 让球双选对冲 ≤¥100
    "draw": "draw_single",    # 平局单关试运行 ≤¥40
    "parlay": "parlay",       # 复选串关创作票 ≤¥60
    "fushi": "fushi",         # 传统足彩复式(shengfucai_renjiu)
}
# channel → decision_budget.json 的 section。
_CHANNEL_SECTION = {
    "jczq": "jczq",
    "shengfucai": "shengfucai_renjiu",
    "renjiu": "shengfucai_renjiu",
}


def _even_split(total: int, n: int) -> list[int]:
    """把整数 total 尽量均分成 n 份(整数元),余数派给前几份;和恰为 total。"""
    if n <= 0:
        return []
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def _ticket_hit_prob(legs: list[dict]) -> float | None:
    """票命中率 = 各腿 prob 连乘;任一腿无 prob → None(不臆造)。"""
    probs = [leg.get("prob") for leg in legs]
    if any(p is None for p in probs):
        return None
    out = 1.0
    for p in probs:
        out *= float(p)
    return round(out, 6)


def _ticket_id(channel: str, draft: dict) -> str:
    """稳定 id(不含时刻)→ 同 legs 重跑幂等 upsert,不翻倍。"""
    if draft["structure"] == "parlay":
        return f"T-{channel}-parlay-{'+'.join(draft['match_ids'])}"
    leg = draft["legs"][0]
    return f"T-{channel}-{draft['bucket']}-{leg.get('match_id')}-{leg.get('selection')}"


def compose_tickets(legs, budget=None, *, channel, made_at="", store=None) -> dict:
    """已声明投注腿 → Ticket + 注金分配摘要(确定性算术,判断不在此层)。

    legs: list[dict],每腿 ``{match_id, market, selection, odds, bucket, line?, prob?}``;
    bucket ∈ {main, hedge, draw, parlay}。budget: 预算配置(load_budget() 形状;None → 读默认)。
    分配策略(明确):每个有腿的 bucket **占满其 cap**,非串关桶按腿数均分成单关票,
    串关桶所有腿合成一张 parlay 票(连乘赔率)。总额超 period_cap → 整数 floor 按比例缩。
    空 legs → 空票(合法)。store 非空则幂等 upsert Ticket。
    """
    from nutmeg.decision.ontology import Ticket

    if budget is None:
        budget = load_budget()
    section = _CHANNEL_SECTION.get(channel, channel)
    caps = (budget or {}).get(section, {}) or {}
    period_cap = int((budget or {}).get("period_cap_yuan", 0)) or None

    # 0) legs 形状闸 —— 具名拒绝，不让形状错配掉进深处的 AttributeError。
    #
    # 出生事故：`com.nutmeg.decision.close` 2026-08-13 19:00 挂在下面那行
    # `leg.get("bucket")` 上（`AttributeError: 'str' object has no attribute 'get'`），
    # 此后该 agent 一直未加载，2026-09-14 退役移除。根因是 `run_express` /
    # `run_decision_express_v2` 都 `json.loads(...)` 后直接喂进来、零校验：喂进
    # **票面结构 dict**（`{"issue":…,"legs":{…}}`，即 `decision-audit-legs` 的输入）
    # 时迭代出的是字符串键。`decision-audit-legs` 对反向错配早有具名拒绝
    # （`missing_audit_metadata`），这里补上对称的一半。
    if isinstance(legs, dict):
        raise TypeError(
            "compose_tickets 需要**投注腿数组** list[dict]，收到的是 dict"
            f"（顶层键 {sorted(legs)[:5]}）。这看起来是**票面结构**"
            "（`{issue, legs:{场号:…}}`）——那是 `decision-audit-legs` 的输入，"
            "不是 express 的。express 要的是 "
            "`[{match_id, market, selection, odds, bucket}, …]`。")
    if not isinstance(legs, list | tuple):
        raise TypeError(
            f"compose_tickets 需要投注腿数组，收到 {type(legs).__name__}。")
    for index, leg in enumerate(legs, start=1):
        if not isinstance(leg, dict):
            raise TypeError(
                f"compose_tickets：第 {index} 条腿是 {type(leg).__name__} 而非 dict"
                f"（{leg!r:.40}）。每条腿须为 "
                "`{match_id, market, selection, odds, bucket}`。")

    # 1) 按 bucket 保序分组
    by_bucket: dict[str, list[dict]] = {}
    for leg in legs:
        by_bucket.setdefault(str(leg.get("bucket") or ""), []).append(leg)

    # 2) 每 bucket 占满 cap → 草拟票面(未做硬顶缩放)
    drafts: list[dict] = []
    for bucket, blegs in by_bucket.items():
        budget_key = _BUCKET_BUDGET_KEY.get(bucket)
        cap = int(caps.get(budget_key, 0)) if budget_key else 0
        if cap <= 0 or not blegs:
            continue
        if bucket == "parlay":
            odds = [float(leg["odds"]) for leg in blegs]
            drafts.append({
                "bucket": bucket, "budget_key": budget_key, "structure": "parlay",
                "legs": list(blegs), "stake": cap,
                "combined_odds": round(parlay_odds(odds), 6),
                "hit_prob": _ticket_hit_prob(blegs),
                "match_ids": [str(leg.get("match_id") or "") for leg in blegs],
            })
        else:
            for stake, leg in zip(_even_split(cap, len(blegs)), blegs, strict=True):
                drafts.append({
                    "bucket": bucket, "budget_key": budget_key, "structure": "single",
                    "legs": [leg], "stake": stake,
                    "combined_odds": round(float(leg["odds"]), 6),
                    "hit_prob": _ticket_hit_prob([leg]),
                    "match_ids": [str(leg.get("match_id") or "")],
                })

    # 3) channel 硬顶:总额超 period_cap → 按比例缩(整数 floor 除,禁浮点截断意外)
    total = sum(d["stake"] for d in drafts)
    scaled = False
    if period_cap and total > period_cap:
        scaled = True
        for d in drafts:
            d["stake"] = (d["stake"] * period_cap) // total

    # 4) 落 Ticket(丢 stake<=0 的空票)+ 幂等入库 + 摘要
    tickets: list = []
    summary_tickets: list[dict] = []
    for d in drafts:
        if d["stake"] <= 0:
            continue
        tid = _ticket_id(channel, d)
        tickets.append(Ticket(
            ticket_id=tid, channel=channel, made_at=made_at,
            legs=[dict(leg) for leg in d["legs"]], structure=d["structure"],
            stake_yuan=int(d["stake"]), computed_hit_prob=d["hit_prob"],
            tag=d["bucket"], budget_bucket=d["budget_key"],
        ))
        summary_tickets.append({
            "ticket_id": tid, "bucket": d["bucket"], "budget_bucket": d["budget_key"],
            "structure": d["structure"], "stake_yuan": int(d["stake"]),
            "combined_odds": d["combined_odds"], "n_legs": len(d["legs"]),
            "computed_hit_prob": d["hit_prob"],
            # Full legs exposed for the kernel-backed express path (additive; old
            # callers ignore it). Deterministic ¥400 allocation stays in this function.
            "legs": [dict(leg) for leg in d["legs"]],
        })
    if store is not None:
        store.upsert_many(tickets)

    by_bucket_summary: dict[str, dict] = {}
    for st in summary_tickets:
        agg = by_bucket_summary.setdefault(st["bucket"], {
            "cap": int(caps.get(_BUCKET_BUDGET_KEY.get(st["bucket"], ""), 0)),
            "stake": 0, "n_tickets": 0})
        agg["stake"] += st["stake_yuan"]
        agg["n_tickets"] += 1

    return {
        "channel": channel,
        "period_cap_yuan": period_cap,
        "total_stake_yuan": sum(st["stake_yuan"] for st in summary_tickets),
        "scaled": scaled,
        "n_tickets": len(summary_tickets),
        "tickets": summary_tickets,
        "by_bucket": by_bucket_summary,
    }


def run_express(legs_file, channel: str, output_dir, made_at: str) -> str:
    """CLI 胶水:读 legs JSON → compose_tickets → 幂等落 store → 一行摘要。"""
    from pathlib import Path

    from nutmeg.decision.store import DecisionStore

    legs = json.loads(Path(legs_file).read_text(encoding="utf-8"))
    store = DecisionStore(Path(output_dir) / "decision")
    summary = compose_tickets(legs, load_budget(), channel=channel,
                              made_at=made_at, store=store)
    msg = (f"decision-express {channel}: {summary['n_tickets']} 票 / "
           f"总注 ¥{summary['total_stake_yuan']}")
    if summary["scaled"]:
        msg += "(超 ¥400 硬顶已按比例缩)"
    return msg
