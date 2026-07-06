"""规范化比赛身份(spec §2 Match=跨通道身份)——一场真实比赛一个 canonical id,
竞彩号/zucai期号是 channel_refs。同一场两通道算出同一 id → 校准不双计。"""
from __future__ import annotations


def norm_team(name: str) -> str:
    """去空格 + casefold(中文名原样保留;拉丁名归一大小写)。"""
    return "".join((name or "").split()).casefold()


def canonical_match_id(home: str, away: str, date: str) -> str:
    """M-<date>-<norm(home)>-<norm(away)>。确定性、跨通道稳定。"""
    return f"M-{date}-{norm_team(home)}-{norm_team(away)}"
