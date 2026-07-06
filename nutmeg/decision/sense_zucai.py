"""传统足彩 adapter:zucai 14场 + 1X2赔率 → MarketSnapshot(canonical 身份,去水 fair)。
复用同一信念层,不重造。express 票构造属 M1.5,本模块只到信念快照。

⚠️ 每场用**自身比赛日期**(一期常跨多天,如 26070 横跨 05-02/05-03),否则 canonical
与竞彩对不齐、跨通道 dedup 失效——故 dates 是 {match_no: match_date} 而非 issue 单日。"""
from __future__ import annotations

from nutmeg.decision.identity import canonical_match_id
from nutmeg.decision.market_data import fair_1x2


def zucai_snapshots(matches, odds: dict, *, issue: str, dates: dict,
                    taken_at: str) -> list:
    """matches: ZucaiMatch 列表(match_no/home_team/away_team);
    odds: {match_no: {home,draw,away}};dates: {match_no: match_date}(每场自身日期)。
    → MarketSnapshot(source=zucai,canonical)。
    某场无 1X2 赔率、或无该场日期 → 跳过(不伪造 fair、不用 issue 级单日兜底)。"""
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for m in matches:
        row = odds.get(m.match_no)
        if not row or not all(row.get(k) for k in ("home", "draw", "away")):
            continue
        date = dates.get(m.match_no)
        if not date:
            continue
        fair = fair_1x2({"home": row["home"], "draw": row["draw"], "away": row["away"]})
        if not fair:
            continue
        mid = canonical_match_id(m.home_team, m.away_team, date)
        snaps.append(MarketSnapshot(
            snapshot_id=f"S-read_time-zucai-{issue}-{m.match_no}-{taken_at}",
            match_id=mid, taken_at=taken_at, kind="read_time", source="zucai",
            fair={"had": fair}, raw_odds={"had": dict(row)}, lines={},
        ))
    return snaps


def _default_loader(issue: str, output_dir):
    """从已存 zucai 快照读 (matches, odds, dates)。replay 优先,不打网。

    真源落盘结构(已核对 .nutmeg-data/zucai/):
    - `{issue}-issue.json`  = ZucaiSourceSyncService.sync 产;顶层含 draw_date,
      `matches: [{match_no, competition, home_team, away_team, match_date, ...}]`。
      → 构造 ZucaiMatch 列表 + dates(每场自身 match_date,不用 draw_date 兜底,
      否则跨多天的期又退回单日 bug)。
    - `{issue}-odds*.json`  = ZucaiOddsSyncService.sync 产(下午盘 `-odds.json` /
      早盘 `-odds-revision.json` / 历史 `-odds-jczq-*.json` 等)。
      赔率槽策略(已定):取**最新**槽(按 mtime,最接近读时的盘),
      `matches: [{match_no, home, draw, away, ...}]` → {match_no:{home,draw,away}}。
    缺 issue 或 odds 文件 → FileNotFoundError(清晰指明路径)。
    """
    import json
    from pathlib import Path

    from nutmeg.domain.zucai import ZucaiMatch

    base = Path(output_dir)
    issue_path = base / f"{issue}-issue.json"
    if not issue_path.exists():
        raise FileNotFoundError(f"zucai issue 快照缺失: {issue_path}")
    issue_data = json.loads(issue_path.read_text(encoding="utf-8"))

    matches: list = []
    dates: dict = {}
    for row in issue_data.get("matches") or []:
        no = row.get("match_no")
        matches.append(ZucaiMatch(
            match_no=no,
            competition=str(row.get("competition") or ""),
            home_team=str(row.get("home_team") or ""),
            away_team=str(row.get("away_team") or ""),
            match_date=row.get("match_date"),
        ))
        date = row.get("match_date")
        if no is not None and date:
            dates[no] = str(date)

    odds_files = list(base.glob(f"{issue}-odds*.json"))
    if not odds_files:
        raise FileNotFoundError(f"zucai odds 快照缺失: {base}/{issue}-odds*.json")
    latest = max(odds_files, key=lambda p: p.stat().st_mtime)
    odds_data = json.loads(latest.read_text(encoding="utf-8"))

    odds: dict = {}
    for row in odds_data.get("matches") or []:
        no = row.get("match_no")
        if no is None:
            continue
        try:
            odds[no] = {"home": float(row["home"]), "draw": float(row["draw"]),
                        "away": float(row["away"])}
        except (KeyError, TypeError, ValueError):
            continue
    return matches, odds, dates


def sense_zucai(issue: str, *, output_dir, taken_at: str, store, loader=None) -> int:
    """一期传统足彩 14 场 → Match(canonical,merge refs)+Snapshot 入库。返回入库场数。"""
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense import upsert_match_merged

    loader = loader or _default_loader
    matches, odds, dates = loader(issue, output_dir)
    snaps = zucai_snapshots(matches, odds, issue=issue, dates=dates,
                            taken_at=taken_at)
    canonical_to_no = {
        canonical_match_id(m.home_team, m.away_team, dates[m.match_no]): m.match_no
        for m in matches if m.match_no in dates
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
