"""派奖：竞彩复用 `settle_slip`（赔率连乘 × 2 元 × 倍数）+ 过关方式合法性；
足彩任九/胜负彩一二等奖，作废场每个面都算中。缺官方奖金 → 跳过不猜。
"""
from __future__ import annotations

from nutmeg.decision.betslip import BetSlip, SlipSettlement, settle_slip
from nutmeg.gym.board import JczqBoard, ZucaiIssue


def check_jczq_legal(slip: BetSlip, board: JczqBoard) -> str | None:
    """None=合法；否则原因。单关只在该场 poolList.single==1 时允许；串关 2–8 腿。"""
    if slip.channel != "jczq":
        return "not_jczq"
    if not slip.legs:
        return "no_legs"
    for leg in slip.legs:
        if board.lookup(leg.key) is None:
            return f"unknown_leg:{leg.key}"
        if leg.market not in ("had", "hhad", "ttg", "crs", "hafu"):
            return f"unsupported_market:{leg.market}"
        if not leg.selections:
            return f"no_selection:{leg.key}"
    sizes = tuple(slip.combo_sizes or (len(slip.legs),))
    if any(m < 1 or m > 8 or m > len(slip.legs) for m in sizes):
        return "bad_combo_size"
    if board.source == "history_sp":
        if 1 in sizes:
            return "single_not_allowed:history"
        if any(leg.market != "had" for leg in slip.legs):
            return "history_board_had_only"
        return None
    if 1 in sizes:
        for leg in slip.legs:
            match = board.lookup(leg.key)
            if not match.single_allowed.get(leg.market, False):
                return f"single_not_allowed:{leg.key}"
    return None


def settle_jczq(slip: BetSlip, board: JczqBoard) -> SlipSettlement:
    if board.source == "history_sp":
        return settle_sp(slip, board)
    return settle_slip(slip, board.results)


_SP_FACE = {"胜": "home", "平": "draw", "负": "away"}


def settle_sp(slip: BetSlip, board: JczqBoard) -> SlipSettlement:
    """历史板派奖：只有开奖面的 SP——腿中＝所选含开奖面，赔率＝该面 SP；任一腿缺 SP → pending。"""
    from itertools import combinations

    status: dict[str, bool | None] = {}
    odds: dict[str, float] = {}
    detail: list[str] = []
    for leg in slip.legs:
        m = board.lookup(leg.key)
        sp = ((m.sp or {}).get("had") if m else None) or {}
        face = _SP_FACE.get(str(sp.get("outcome") or ""))
        price = sp.get("odds")
        if face is None or price is None:
            status[leg.key] = None
            detail.append(f"? {leg.key} 无开奖 SP")
            continue
        hit = face in set(leg.selections)
        status[leg.key] = hit
        if hit:
            odds[leg.key] = float(price)
        mark = "✓" if hit else "✗"
        detail.append(f"{mark} {leg.key} {'/'.join(leg.selections)} → {face}@{price}")
    idx = list(range(len(slip.legs)))
    combos_total = combos_won = 0
    payout = 0.0
    undecided = False
    for m in (slip.combo_sizes or (len(slip.legs),)):
        for combo in combinations(idx, m):
            combos_total += 1
            marks = [status[slip.legs[i].key] for i in combo]
            if any(v is None for v in marks):
                undecided = True
                continue
            if all(marks):
                combos_won += 1
                product = 1.0
                for i in combo:
                    product *= odds[slip.legs[i].key]
                payout += product * 2 * slip.multiplier
    settled = sum(1 for v in status.values() if v is not None)
    won = sum(1 for v in status.values() if v)
    final = None if undecided else round(payout, 2)
    return SlipSettlement(slip_id=slip.slip_id, settled_legs=settled,
                          pending_legs=len(slip.legs) - settled, won_legs=won,
                          combos_total=combos_total, combos_won=combos_won, payout_yuan=final,
                          pnl_yuan=(final - slip.stake_yuan) if final is not None else None,
                          detail=detail)


def zucai_winning_notes(faces: dict[str, str], results: dict[str, str], *,
                        void: set[int]) -> tuple[int, int]:
    """复式票 → (全对注数, 恰差一场注数)。作废场每个面都算中。

    每场：中面数 w＝作废场为全部所选面数，否则 actual∈所选 ? 1 : 0；错面数 l＝所选面数−w。
    全对注数＝Π w；差一场注数＝Σ_j l_j × Π_{k≠j} w_k。
    """
    winners: list[int] = []
    losers: list[int] = []
    for no, chosen in faces.items():
        chosen = str(chosen)
        k = len(chosen)
        w = k if int(no) in void else (1 if results.get(str(no)) in chosen else 0)
        winners.append(w)
        losers.append(k - w)
    first = 1
    for w in winners:
        first *= w
    second = 0
    for j, lose in enumerate(losers):
        rest = 1
        for i, w in enumerate(winners):
            if i != j:
                rest *= w
        second += lose * rest
    return first, second


def settle_zucai(slip: BetSlip, issue: ZucaiIssue) -> dict:
    """{stake, payout, first_notes, second_notes, skipped_reason?}。缺奖金/赛果 → payout None。"""
    faces = {str(k): str(v) for k, v in slip.faces.items()}
    if slip.channel == "renjiu" and len(faces) != 9:
        return {"stake": None, "payout": None,
                "skipped_reason": f"renjiu_needs_9_matches:{len(faces)}"}
    if slip.channel == "shengfucai" and len(faces) != 14:
        return {"stake": None, "payout": None,
                "skipped_reason": f"shengfucai_needs_14_matches:{len(faces)}"}
    stake = slip.stake_yuan
    if not issue.prizes or not issue.results:
        return {"stake": stake, "payout": None, "skipped_reason": "no_official_prize"}
    results = {str(i + 1): c for i, c in enumerate(issue.results.split())}
    first, second = zucai_winning_notes(faces, results, void=issue.void)
    if slip.channel == "renjiu":
        per = (issue.prizes.get("renjiu") or {}).get("stake_amount")
        if per is None:
            return {"stake": stake, "payout": None, "skipped_reason": "no_renjiu_prize"}
        return {"stake": stake, "payout": first * per * slip.multiplier,
                "first_notes": first, "second_notes": 0}
    p1 = (issue.prizes.get("sfc_first") or {}).get("stake_amount") or 0.0
    p2 = (issue.prizes.get("sfc_second") or {}).get("stake_amount") or 0.0
    return {"stake": stake, "payout": (first * p1 + second * p2) * slip.multiplier,
            "first_notes": first, "second_notes": second}
