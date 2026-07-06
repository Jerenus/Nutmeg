"""先验锚选择——欧赔读时 fair 优先(最 sharp),否则体彩 fair(spec §9 精化 2)。

CLV 两端都用欧赔才自洽:prior=欧赔读时 fair,closing=欧赔收盘 fair。
只认 kind=read_time 快照(收盘快照不作先验)。
"""
from __future__ import annotations

_SOURCE_PRIORITY = ("apifootball", "fcom500", "sporttery")


def resolve_prior(snapshots: list, *, market: str):
    """→ (prior_dict, anchor_snapshot)。无可用 read_time 快照带该市场 → (None, None)。"""
    candidates = [
        s for s in snapshots
        if s.kind == "read_time" and (s.fair or {}).get(market)
    ]
    if not candidates:
        return None, None
    candidates.sort(key=lambda s: _SOURCE_PRIORITY.index(s.source)
                    if s.source in _SOURCE_PRIORITY else len(_SOURCE_PRIORITY))
    anchor = candidates[0]
    return anchor.fair[market], anchor
