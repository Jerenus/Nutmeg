"""竞彩策略：板面 → combos 腿 → `enumerate_combos` → 帽内挑票。

体彩多数场次不开单关（poolList.single），所以这里的票一律 ≥2 串 1；单关由运行器的合法性检查拒绝。
"""
from __future__ import annotations

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.jczq_combos import enumerate_combos
from nutmeg.gym.board import FACE_OF, JczqBoard, JczqMatch
from nutmeg.gym.policy import Ctx, register

FACE_SETS = ("3", "1", "0", "31", "30", "10")


def belief_of(m: JczqMatch, ctx: Ctx) -> dict[str, float]:
    if ctx.belief_source == "closing" and m.closing_fair:
        return dict(m.closing_fair)
    if ctx.belief_source == "read" and m.read_belief:
        return dict(m.read_belief)
    return m.belief_market


def combo_legs(board: JczqBoard, ctx: Ctx, *, faces_filter=None, match_filter=None) -> list[dict]:
    legs: list[dict] = []
    for code, m in sorted(board.matches.items()):
        if match_filter and not match_filter(m):
            continue
        belief = belief_of(m, ctx)
        options = []
        for faces in FACE_SETS:
            if faces_filter and not faces_filter(m, faces, belief):
                continue
            modal = max(faces, key=lambda f: belief[FACE_OF[f]])
            options.append({"market": "had", "faces": faces,
                            "p": sum(belief[FACE_OF[f]] for f in faces),
                            "odds": [m.had[f] for f in faces], "modal_odds": m.had[modal]})
        if options:
            legs.append({"code": code, "name": m.name, "kickoff": m.kickoff_bj,
                         "belief": belief, "prior": m.belief_market, "options": options})
    return legs


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
            if len(faces) != 1 or not m.closing_fair:
                return False
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
            fair = m.closing_fair or m.belief_market
            return max(fair.values()) >= self.threshold

        def fav_face_only(m: JczqMatch, faces: str, belief: dict) -> bool:
            fair = m.closing_fair or m.belief_market
            return len(faces) == 1 and FACE_OF[faces] == max(fair, key=fair.get)

        legs = combo_legs(board, ctx, faces_filter=fav_face_only, match_filter=is_fav)
        if len(legs) < 2:
            return []
        combos = enumerate_combos(legs, max_legs=2, max_notes=1, top=30)
        return pick_within_cap(board.day, combos, cap=ctx.cap_jczq_day, tag="fav", max_slips=10)
