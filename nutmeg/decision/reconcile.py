"""reconcile — Read/Ticket + 赛果 + 收盘快照 → Settlement(双轴)。

演进 judge_ledger 对账纪律。赛果缺 → pending(brier/outcome=None);
收盘快照缺 → clv_pp=None(缺数据绝不伪造,spec §4 多源纪律)。
"""
from __future__ import annotations

from dataclasses import replace

from nutmeg.decision.ontology import Settlement
from nutmeg.decision.scoring import brier, clv_pp


def settle_read(read, *, outcome_90, score, closing) -> Settlement:
    b = None if outcome_90 is None else brier(read.belief, outcome_90)
    clv = None
    if closing is not None and not read.shadow:
        closing_fair = (closing.fair or {}).get(read.market, {})
        if closing_fair:
            clv = clv_pp(read.belief, read.prior, closing_fair)
    return Settlement(
        settlement_id=f"SET-read-{read.read_id}",
        ref_type="read", ref_id=read.read_id,
        settled_at=read.made_at,          # 占位;编排层用真实结算时刻覆盖
        outcome_90=outcome_90, score=score,
        closing_snapshot_id=(closing.snapshot_id if closing else None),
        brier=b, clv_pp=clv, hit=None, pnl_yuan=None,
    )


def settle_ticket_leg(*, market: str, pick: str, line: float | None,
                      outcome_90: str | None, goals_h: int | None,
                      goals_a: int | None) -> str | None:
    """票面口径 3 路结果(继承 judge_ledger._grade_ticket_outcome 全部 7/06 修复)。

    had=胜平负;hhad=90' 净胜球+让球线。line=None 且 hhad → None(pending)。
    AET/PEN 90'=平 margin 0。pick 无法规约成 home/draw/away → None(pending,不误判输)。
    赛果缺(outcome_90=None)→ None。
    """
    if pick not in ("home", "draw", "away"):
        return None
    if outcome_90 is None:
        return None
    if market == "had":
        return outcome_90
    if market == "hhad":
        if line is None:
            return None
        if outcome_90 == "draw":
            margin = 0
        elif goals_h is None:
            return None
        else:
            margin = goals_h - goals_a
        adj = margin + line
        return "home" if adj > 0 else "away" if adj < 0 else "draw"
    return None


_HAD_OUTCOME = {"胜": "home", "平": "draw", "负": "away"}


def _result_outcome(result: dict) -> tuple[str | None, str | None, int | None, int | None]:
    """okooo 赛果行 → (outcome_90, score, goals_h, goals_a)。缺 → (None,...)。"""
    had = _HAD_OUTCOME.get(result.get("had", ""))
    score = result.get("score") or None
    gh = ga = None
    if score:
        try:
            gh, ga = (int(x) for x in score.replace("：", ":").split(":"))
        except ValueError:
            gh = ga = None
        if had is None and gh is not None:
            had = "home" if gh > ga else "away" if gh < ga else "draw"
    return had, score, gh, ga


def settle_reads_for_matches(store, *, outcomes: dict, settled_at: str) -> int:
    """通用结算:outcomes={match_id: (outcome_90, score)}。对每个**有结果**的 Read 产
    Settlement(Brier+CLV,复用 settle_read + 收盘快照)。canonical 身份→竞彩/zucai 通用。

    只结算 match_id 命中 outcomes 的 Read;无结果的 Read 跳过(不 clobber 其既有/pending
    结算)——canonical 混库(竞彩+zucai 同一 store)下按通道各自喂 outcomes 才安全。
    返回结算的 Read 数。幂等(upsert-by-id)。
    """
    from nutmeg.decision.ontology import MarketSnapshot, Read

    closing_by_match = {
        s.match_id: s for s in store.load(MarketSnapshot) if s.kind == "closing"
    }
    n = 0
    for read in store.load(Read):
        oc = outcomes.get(read.match_id)
        if oc is None:
            continue
        outcome, score = oc
        s = settle_read(read, outcome_90=outcome, score=score,
                        closing=closing_by_match.get(read.match_id))
        s = replace(s, settlement_id=f"SET-read-{read.read_id}",
                    settled_at=settled_at)
        store.upsert(s)
        n += 1
    return n


def settle_day(store, *, run_date: str, results: dict, settled_at: str) -> int:
    """当日竞彩 Read → Settlement(Brier+CLV)落库。返回结算数。

    赛果按 okooo 口径 {竞彩号: {score, had}}。canonical 迁移后 match_id 不含竞彩号,
    改经 Match.channel_refs.jczq_match_no 映射到 canonical,再走通用 settle_reads_for_matches
    (与 zucai 统一;2026-07-06 canonical 修)。
    """
    from nutmeg.decision.ontology import Match

    # 竞彩号 → canonical match_id(经 Match.channel_refs)
    no_to_canonical: dict[str, str] = {}
    for m in store.load(Match):
        no = m.channel_refs.get("jczq_match_no")
        if no:
            no_to_canonical[no] = m.match_id
    outcomes: dict = {}
    for no, result in results.items():
        canonical = no_to_canonical.get(no)
        outcome, score, _gh, _ga = _result_outcome(result)
        # 只喂有真实结果的场——未终局(outcome None)不产 pending 结算(诚实计数+不占位)。
        if canonical and outcome is not None:
            outcomes[canonical] = (outcome, score)
    return settle_reads_for_matches(store, outcomes=outcomes, settled_at=settled_at)
