"""reconcile — Read/Ticket + 赛果 + 收盘快照 → Settlement(双轴)。

演进 judge_ledger 对账纪律。赛果缺 → pending(brier/outcome=None);
收盘快照缺 → clv_pp=None(缺数据绝不伪造,spec §4 多源纪律)。
"""
from __future__ import annotations

_SFC_OUTCOME = {"3": "home", "1": "draw", "0": "away"}


def settle_ticket_leg(*, market: str, pick: str, line: float | None,
                      outcome_90: str | None, goals_h: int | None,
                      goals_a: int | None, ht_h: int | None = None,
                      ht_a: int | None = None) -> str | None:
    """票面腿实际结果(继承 judge_ledger._grade_ticket_outcome 全部 7/06 修复)。

    had=胜平负;hhad=90' 净胜球+让球线(line=None → pending);ttg=总进球桶(7=7+ 封顶,
    镜像体彩玩法);crs=精确比分"H:A"。pick 无法规约 / 赛果缺 → None(pending,不误判输)。
    AET/PEN 90'=平 margin 0。
    """
    if not pick:
        return None
    # results-90.json(day.results 桥)用 3/1/0 写 outcome_90;这里统一成 home/draw/away。
    outcome_90 = _SFC_OUTCOME.get(outcome_90, outcome_90)
    if market in ("had", "hhad"):
        if pick not in ("home", "draw", "away") or outcome_90 is None:
            return None
        if market == "had":
            return outcome_90
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
    if goals_h is None or goals_a is None:
        return None
    if market == "ttg":
        return str(min(goals_h + goals_a, 7))
    if market == "crs":
        return f"{goals_h}:{goals_a}"
    if market == "hafu":
        # 半全场：半场胜平负 + 全场胜平负，键如 "hd"（半场主胜、全场平）；缺半场比分 → pending
        if ht_h is None or ht_a is None:
            return None
        return _HAFU_SYMBOL[_outcome_of(ht_h, ht_a)] + _HAFU_SYMBOL[_outcome_of(goals_h, goals_a)]
    return None


_HAFU_SYMBOL = {"home": "h", "draw": "d", "away": "a"}
_HAFU_CN = {"胜": "h", "平": "d", "负": "a"}


def _outcome_of(gh: int, ga: int) -> str:
    return "home" if gh > ga else ("draw" if gh == ga else "away")


def normalize_hafu(selection: str | None) -> str | None:
    """"胜胜"/"负平"/"hh"/"ad" → "hh".."aa"；不可规约 → None。"""
    s = (selection or "").strip().replace("・", "·").split("·", 1)[0].strip()
    if len(s) == 2 and all(c in _HAFU_CN for c in s):
        return _HAFU_CN[s[0]] + _HAFU_CN[s[1]]
    if len(s) == 2 and all(c in "hda" for c in s.lower()):
        return s.lower()
    return None


_HAD_OUTCOME = {"胜": "home", "平": "draw", "负": "away"}

# 票面 selection 可读名 → 3 路键(7/07 修:7/06 起 legs 用"让胜·xxx"式 selection,
# 旧口径只认裸键 → 整票被静默跳过永不入账)。had 与 hhad 前缀都规约到同一 3 路键。
_PICK_ALIASES = {
    "home": "home", "draw": "draw", "away": "away",
    "主胜": "home", "胜": "home", "让胜": "home",
    "平": "draw", "让平": "draw",
    "客胜": "away", "负": "away", "让负": "away",
}


def normalize_pick(selection: str | None) -> str | None:
    """"主胜·阿根廷90分钟"/"让负·杰尔+1不败"/"home" → home/draw/away;不可规约 → None。"""
    s = (selection or "").strip()
    if s in _PICK_ALIASES:
        return _PICK_ALIASES[s]
    head = s.replace("・", "·").split("·", 1)[0].strip()
    return _PICK_ALIASES.get(head)


def normalize_selection(market: str, selection: str | None) -> str | None:
    """按市场把票面 selection 规约成 settle_ticket_leg 的结果键。

    had/hhad → home/draw/away;ttg "2球"/"7+球"/"total_2" → "2".."7"(7=7+);
    crs "2:1"(含全角冒号) → "H:A"。"胜其他"类聚合桶未支持 → None(整票 pending 不误判)。
    """
    if market in ("had", "hhad"):
        return normalize_pick(selection)
    if market == "hafu":
        return normalize_hafu(selection)
    head = ((selection or "").strip().replace("：", ":").replace("・", "·")
            .split("·", 1)[0].strip())
    if market == "ttg":
        if head.startswith("total_"):
            head = head[len("total_"):]
        head = head.removesuffix("球").removesuffix("+")
        return head if head.isdigit() and 0 <= int(head) <= 7 else None
    if market == "crs":
        parts = head.split(":")
        if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
            return f"{int(parts[0])}:{int(parts[1])}"
        return None
    return None


