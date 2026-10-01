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
    if 1 in sizes:
        for leg in slip.legs:
            match = board.lookup(leg.key)
            if not match.single_allowed.get(leg.market, False):
                return f"single_not_allowed:{leg.key}"
    return None


def settle_jczq(slip: BetSlip, board: JczqBoard) -> SlipSettlement:
    return settle_slip(slip, board.results)


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
