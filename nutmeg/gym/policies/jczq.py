"""竞彩策略：板面 → combos 腿 → `enumerate_combos` → 帽内挑票。

体彩多数场次不开单关（poolList.single），所以这里的票一律 ≥2 串 1；单关由运行器的合法性检查拒绝。
"""
from __future__ import annotations

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.jczq_combos import enumerate_combos
from nutmeg.gym.board import FACE_OF, JczqBoard, JczqMatch
from nutmeg.gym.policy import Ctx, register

FACE_SETS = ("3", "1", "0", "31", "30", "10")


def belief_of(m: JczqMatch, ctx: Ctx) -> dict[str, float] | None:
    if ctx.belief_source == "closing" and m.closing_fair:
        return dict(m.closing_fair)
    if ctx.belief_source == "read" and m.read_belief:
        return dict(m.read_belief)
    return m.belief_any


def price_of(m: JczqMatch, face: str, belief: dict[str, float]) -> float:
    """可买价；历史板没有三面全价 → 用 1/p 占位（只用于排序，派奖按开奖 SP）。"""
    if len(m.had) == 3:
        return m.had[face]
    return round(1 / max(belief[FACE_OF[face]], 1e-6), 3)


# enumerate_combos 是 C(n,k)×6^k 的全枚举：20 场板 k=4 近 300 万种，先按最大面裁到 8 场
MAX_LEGS_CONSIDERED = 8


def combo_legs(board: JczqBoard, ctx: Ctx, *, faces_filter=None, match_filter=None,
               max_matches: int = MAX_LEGS_CONSIDERED) -> list[dict]:
    legs: list[dict] = []
    for code, m in sorted(board.matches.items()):
        if match_filter and not match_filter(m):
            continue
        belief = belief_of(m, ctx)
        if belief is None:
            continue
        options = []
        for faces in FACE_SETS:
            if faces_filter and not faces_filter(m, faces, belief):
                continue
            modal = max(faces, key=lambda f: belief[FACE_OF[f]])
            options.append({"market": "had", "faces": faces,
                            "p": sum(belief[FACE_OF[f]] for f in faces),
                            "odds": [price_of(m, f, belief) for f in faces],
                            "modal_odds": price_of(m, modal, belief)})
        if options:
            legs.append({"code": code, "name": m.name, "kickoff": m.kickoff_bj,
                         "belief": belief, "prior": m.belief_any, "options": options})
    # 帽内 max P 的腿几乎只来自最大面最高的场：按最大面降序裁到 max_matches 场再枚举
    legs.sort(key=lambda leg: -max(leg["belief"].values()))
    return legs[:max_matches]


def to_slip(day: str, combo: dict, *, tag: str) -> BetSlip:
    legs = [SlipLeg(key=leg["code"], name=leg["name"], market="had", line=None,
                    selections=tuple(FACE_OF[f] for f in leg["faces"]),
                    odds=tuple(leg["odds"]), fair=None)
            for leg in combo["legs"]]
    return BetSlip(slip_id=f"gym-{tag}-{day}-{'+'.join(leg.key for leg in legs)}",
                   channel="jczq", placed_at=day, legs=legs, multiplier=1,
                   combo_sizes=(len(legs),))


def pick_within_cap(day: str, combos: list[dict], *, cap: int, tag: str,
                    max_slips: int = 3) -> list[BetSlip]:
    picks: list[BetSlip] = []
    spent = 0
    seen: set[str] = set()
    for combo in combos:
        slip = to_slip(day, combo, tag=tag)
        if slip.slip_id in seen or spent + slip.stake_yuan > cap:
            continue
        seen.add(slip.slip_id)
        picks.append(slip)
        spent += slip.stake_yuan
        if len(picks) >= max_slips:
            break
    return picks


@register
class JczqMaxP:
    """帽内 P(全对) 最高的 2–4 串 1（单双选），最多三张。"""
    name = "jczq_max_p"
    version = "v1"
    channels = ("jczq",)

    def decide(self, board: JczqBoard, ctx: Ctx) -> list[BetSlip]:
        legs = combo_legs(board, ctx)
        if len(legs) < 2:
            return []
        combos = enumerate_combos(legs, max_legs=4, max_notes=4, top=30)
        return pick_within_cap(board.day, combos, cap=ctx.cap_jczq_day, tag="maxp")


@register
class JczqEvFilter:
    """只用终盘隐含 EV>0 的单面（#2 的表 2 说它不可靠——放进来被证伪）。"""
    name = "jczq_ev_filter"
    version = "v1"
    channels = ("jczq",)

    def decide(self, board: JczqBoard, ctx: Ctx) -> list[BetSlip]:
        def positive_ev(m: JczqMatch, faces: str, belief: dict) -> bool:
            if len(faces) != 1 or not m.closing_fair or len(m.had) != 3:
                return False                      # 历史板没有三面价，EV 过滤无从算
            return m.closing_fair[FACE_OF[faces]] * m.had[faces] > 1.0

        legs = combo_legs(board, ctx, faces_filter=positive_ev)
        if len(legs) < 2:
            return []
        combos = enumerate_combos(legs, max_legs=3, max_notes=1, top=30)
        return pick_within_cap(board.day, combos, cap=ctx.cap_jczq_day, tag="ev")


@register
class JczqFavPairs:
    """终盘最大面 ≥0.70 的热门两两 2 串 1（#2 的 +15pp 结构化用法）。"""
    name = "jczq_fav_pairs"
    version = "v1"
    channels = ("jczq",)
    threshold = 0.70

    def decide(self, board: JczqBoard, ctx: Ctx) -> list[BetSlip]:
        def is_fav(m: JczqMatch) -> bool:
            fair = m.closing_fair or m.belief_any
            return bool(fair) and max(fair.values()) >= self.threshold

        def fav_face_only(m: JczqMatch, faces: str, belief: dict) -> bool:
            fair = m.closing_fair or m.belief_any
            return bool(fair) and len(faces) == 1 and FACE_OF[faces] == max(fair, key=fair.get)

        legs = combo_legs(board, ctx, faces_filter=fav_face_only, match_filter=is_fav)
        if len(legs) < 2:
            return []
        combos = enumerate_combos(legs, max_legs=2, max_notes=1, top=30)
        return pick_within_cap(board.day, combos, cap=ctx.cap_jczq_day, tag="fav", max_slips=10)


@register
class JczqRuleV3:
    """Dream 评估器 v3（2026-10-01 定位；2026-10-04 迁入 gym）：先排除坏结构，再按期望回报选。

    期望回报率 = P(全中) × 模态赔率连乘 / 注数；< 0.5 的组合否决（审票 V1 同口径）。过线组合里
    取期望回报率最高的一张；最高者仍 < 1.0 → 规则最优＝空仓（不出票）。用 `--belief read`
    就是 Dream 当年的「研究判断 × 体彩价」口径。"""
    name = "jczq_rule_v3"
    version = "v3"
    channels = ("jczq",)
    veto_ratio = 0.5

    def decide(self, board: JczqBoard, ctx: Ctx) -> list[BetSlip]:
        legs = combo_legs(board, ctx)
        if len(legs) < 2:
            return []
        best, best_ratio = None, 0.0
        for combo in enumerate_combos(legs, max_legs=4, max_notes=4, top=10**9):
            ratio = combo["p"] * combo["return_per_yuan"]
            if ratio >= self.veto_ratio and ratio > best_ratio:
                best, best_ratio = combo, ratio
        if best is None or best_ratio < 1.0:
            return []
        return pick_within_cap(board.day, [best], cap=ctx.cap_jczq_day, tag="v3", max_slips=1)

