"""基线与研究席位。规则看过全样本回测，所以不走封存验证，只作前瞻对照。"""
from __future__ import annotations

from nutmeg.decision.arena.rules import TIERS

_LOGICS = (
    ("稳胆串", {"market": ["had"], "is_fav": True}, "p_fair",
     "全选热门，是最朴素的高命中串法", "实中率不高于同档地板"),
    ("高返还", {"p_fair": [0.15, 1.0]}, "ret",
     "体彩赔率乘国际概率最高的腿，体彩抽水相对最少", "同档 ROI 不高于地板"),
    ("中赔串", {"sp": [1.7, 3.2]}, "ret",
     "中段赔率方差较小，串起来不靠单条冷腿", "同档 ROI 不高于地板"),
    ("价差让负", {"face": ["not_win"], "gap": [0.03, 1.0]}, "gap",
     "体彩比国际盘多压主队时，主不胜可能偏便宜", "同档 ROI 不高于地板"),
    ("让球护盘", {"market": ["hhad"]}, "ret",
     "主不胜和主不败覆盖两个面，单腿更稳", "同档 ROI 不高于地板"),
    ("平局串", {"face": ["draw"]}, "ret",
     "人群不爱押平，平局赔率可能偏高", "同档 ROI 不高于地板"),
    ("冷门串", {"market": ["had"], "is_dog": True}, "ret",
     "最低概率面的赔率溢价", "同档 ROI 不高于地板"),
)
_DROPPED = {"稳胆串-50", "冷门串-50"}


def _rule(rule_id: str, tier: list[int], conds: dict, score: str, why: str, wrong: str) -> dict:
    return {"id": rule_id, "tier": tier, "filter": conds, "score": score, "legs": [2, 5],
            "mechanism": why, "falsify": wrong}


def baseline_rules() -> list[dict]:
    rules = [_rule(f"B-{name}-{tier[0]}", tier, conds, score, why, wrong)
             for name, conds, score, why, wrong in _LOGICS for tier in TIERS
             if f"{name}-{tier[0]}" not in _DROPPED]
    rules += [_rule(f"R-研究同向-{tier[0]}", tier, {"stance_match": True}, "p_fair",
                    "当日深研表态的面，可能含市场未消化的伤停和轮换信息",
                    "同档 ROI 不高于地板，也不高于稳胆串") for tier in TIERS]
    return rules
