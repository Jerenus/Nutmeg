"""传统足彩 adapter:zucai 14场 + 1X2赔率 → MarketSnapshot(canonical 身份,去水 fair)。
复用同一信念层,不重造。express 票构造属 M1.5,本模块只到信念快照。"""
from __future__ import annotations

from nutmeg.decision.identity import canonical_match_id
from nutmeg.decision.market_data import fair_1x2


def zucai_snapshots(matches, odds: dict, *, issue: str, match_date: str,
                    taken_at: str) -> list:
    """matches: ZucaiMatch 列表(match_no/home_team/away_team);
    odds: {match_no: {home,draw,away}}。→ MarketSnapshot(source=zucai,canonical)。
    某场无 1X2 赔率 → 跳过(不伪造 fair)。"""
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for m in matches:
        row = odds.get(m.match_no)
        if not row or not all(row.get(k) for k in ("home", "draw", "away")):
            continue
        fair = fair_1x2({"home": row["home"], "draw": row["draw"], "away": row["away"]})
        if not fair:
            continue
        mid = canonical_match_id(m.home_team, m.away_team, match_date)
        snaps.append(MarketSnapshot(
            snapshot_id=f"S-read_time-zucai-{issue}-{m.match_no}-{taken_at}",
            match_id=mid, taken_at=taken_at, kind="read_time", source="zucai",
            fair={"had": fair}, raw_odds={"had": dict(row)}, lines={},
        ))
    return snaps
