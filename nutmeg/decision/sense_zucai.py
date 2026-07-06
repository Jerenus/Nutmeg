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


def _default_loader(issue: str, output_dir):
    """从已存 zucai 快照读 (matches, odds, match_date)。replay 优先,不打网。

    真源落盘结构(已核对 .nutmeg-data/zucai/):
    - `{issue}-issue.json`  = ZucaiSourceSyncService.sync 产;顶层含 draw_date,
      `matches: [{match_no, competition, home_team, away_team, match_date, ...}]`。
    - `{issue}-odds.json`(下午盘) / `{issue}-odds-revision.json`(早盘修订)
      = ZucaiOddsSyncService.sync 产;`matches: [{match_no, home, draw, away, ...}]`
      即 1X2 赔率,按 match_no 键。

    尚未接线——两处真源决策需先定,故此占位不猜:
    ① 两个赔率槽(-odds.json 下午盘 vs -odds-revision.json 早盘)共存时选哪个是策略。
    ② 一期 14 场常跨多个 match_date(如 26071 横跨 05-03/05-04),而 zucai_snapshots
       现签名只收单个 match_date;canonical 与竞彩对齐须用每场自身日期——属 Task 4
       签名问题,应在后续 wiring 任务连同 per-match date 一并解决。
    注入 loader 的测试已全面覆盖本模块编排逻辑,真源接线后补。
    """
    raise NotImplementedError(
        "wire to zucai_source/zucai_odds_source 已存快照:"
        f"{issue}-issue.json + {issue}-odds[-revision].json(见 docstring)"
    )


def sense_zucai(issue: str, *, output_dir, taken_at: str, store, loader=None) -> int:
    """一期传统足彩 14 场 → Match(canonical,merge refs)+Snapshot 入库。返回入库场数。"""
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense import upsert_match_merged

    loader = loader or _default_loader
    matches, odds, match_date = loader(issue, output_dir)
    snaps = zucai_snapshots(matches, odds, issue=issue, match_date=match_date,
                            taken_at=taken_at)
    canonical_to_no = {
        canonical_match_id(m.home_team, m.away_team, match_date): m.match_no
        for m in matches
    }
    by_no = {m.match_no: m for m in matches}
    for s in snaps:
        no = canonical_to_no.get(s.match_id)
        m = by_no.get(no)
        upsert_match_merged(store, Match(
            match_id=s.match_id, kickoff_at=taken_at, home=m.home_team,
            away=m.away_team, competition="",
            channel_refs={"zucai": {"issue": issue, "index": no}}))
        store.upsert(s)
    return len(snaps)
