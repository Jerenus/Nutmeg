"""别名自愈提案器 —— audit 点名的缺口由机器提案、人一键确认（Roadmap C1）。

**方法：对手推断（确定性，零 LLM）。** 板面一场比赛若一边已解析（帕尔梅拉斯→Palmeiras）、
另一边未解析（波特诺），则在 API-Football 当日 fixtures 里找含 Palmeiras 的那场——
它的对手英文名（Cerro Porteno）就是"波特诺"的候选。这正是采集侧安全失败机制
（双边匹配同一场才生效）的逆运算。

两边都未解析的场（普拉滕斯 vs 科金博联）**推断不了，如实报出**——那是 agent/人工
补位的地方，机器不猜。⚠️`--apply` 只写"恰有一个候选"的提案；多候选/零候选一律只报告。
"""
from __future__ import annotations

import json
from pathlib import Path

ALIAS_FILE = Path("nutmeg/data/jczq_club_team_aliases.json")


def _fixture_pairs(fixtures: list[dict]) -> list[tuple[str, str]]:
    out = []
    for f in fixtures or []:
        try:
            out.append((f["teams"]["home"]["name"], f["teams"]["away"]["name"]))
        except (KeyError, TypeError):
            continue
    return out


def propose_for_board(board_matches: list[dict], resolved: dict,
                      fixtures: list[dict]) -> dict:
    """→ {proposals: [{cn, candidate_en, via, fixture}], unresolvable: [...]}

    board_matches: [{home, away}]（中文）；resolved: {中文名: 英文名}（已入表的）；
    fixtures: API-Football 当日 fixtures 原始条目。
    """
    pairs = _fixture_pairs(fixtures)
    proposals, unresolvable = [], []
    for m in board_matches:
        h, a = m.get("home") or "", m.get("away") or ""
        rh, ra = resolved.get(h), resolved.get(a)
        if rh and ra:
            continue                      # 双边已解析,无事可做
        if not rh and not ra:
            unresolvable.append({"home": h, "away": a,
                                 "reason": "双边均未解析,无锚点可推断——需人工/agent 补位"})
            continue
        known_en, missing_cn, missing_side = (rh, a, "away") if rh else (ra, h, "home")
        cands = set()
        for fh, fa in pairs:
            if fh == known_en:
                cands.add(fa if missing_side == "away" else None)
            if fa == known_en:
                cands.add(fh if missing_side == "home" else None)
        cands.discard(None)
        if len(cands) == 1:
            proposals.append({"cn": missing_cn, "candidate_en": cands.pop(),
                              "via": known_en, "fixture": f"{h} vs {a}"})
        elif not cands:
            unresolvable.append({"home": h, "away": a,
                                 "reason": f"当日 fixtures 未找到 {known_en} 的对局"})
        else:
            unresolvable.append({"home": h, "away": a,
                                 "reason": f"{known_en} 当日有多场对局,候选歧义: {sorted(cands)}"})
    return {"proposals": proposals, "unresolvable": unresolvable}


def apply_proposals(proposals: list[dict], alias_path=ALIAS_FILE) -> list[str]:
    """把单一候选提案写入别名表。已存在的键不覆盖（如实报）。"""
    path = Path(alias_path)
    table = json.loads(path.read_text("utf-8"))
    lines = []
    changed = False
    for p in proposals:
        cn, en = p["cn"], p["candidate_en"]
        if cn in table:
            lines.append(f"跳过 {cn}(已存在 → {table[cn]})")
            continue
        table[cn] = en
        changed = True
        lines.append(f"+ {cn} → {en}  (经 {p['via']} 对手推断)")
    if changed:
        path.write_text(json.dumps(table, ensure_ascii=False, indent=1), "utf-8")
    return lines


def _fetch_day_fixtures(run_date: str) -> list[dict]:
    """当日全联赛 fixtures → `propose_for_board` 要的 `{teams:{home:{name},away:{name}}}` 形状。

    出生事故 2026-09-18：本函数原来是
    `from nutmeg.services.jczq_apifootball_odds import fetch_fixtures_by_date`，
    而那个名字在 2026-09-14 竞彩国际欧赔切源（titan007 主 / AF 备）时被删掉了，
    `decision-alias-propose` 从那天起**一调用就 ImportError**。没被测到是因为
    `tests/decision/test_alias_propose.py` 只测注入 fixtures 的纯函数
    `propose_for_board`，`run_propose` 的取数路径一行覆盖都没有。
    改用生产客户端 `ApiFootballClient.fetch_fixtures_by_date`（返回 `Fixture` 领域对象），
    在这里转回提案器要的原始形状 —— 转换只做名字，不猜任何东西。
    """
    from datetime import date as _date

    from nutmeg.config.settings import get_settings
    from nutmeg.data.api_football import ApiFootballClient

    settings = get_settings()
    key = (settings.api_football_key or "").strip()
    if not key:                      # 与采集侧同一契约：无 key 优雅降级，不崩
        return []
    client = ApiFootballClient(base_url=settings.api_football_base_url, api_key=key)
    try:
        batch = client.fetch_fixtures_by_date(_date.fromisoformat(run_date))
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return [{"teams": {"home": {"name": f.home_team}, "away": {"name": f.away_team}}}
            for f in batch.fixtures]


def run_propose(run_date: str, output_dir, *, apply: bool = False,
                fixtures: list[dict] | None = None) -> str:
    """CLI 胶水：读当日板面 audit 缺口 → 拉当日 fixtures → 提案（可选写入）。"""
    from nutmeg.data.team_aliases import load_team_aliases
    from nutmeg.decision.alias_audit import audit_day
    from nutmeg.decision.identity import norm_team

    report = audit_day(run_date, output_dir)
    missing = {r["name"] for r in (report.get("odds_alias") or {}).get("missing_teams") or []}
    if not missing:
        return f"{run_date}: 别名无缺口,无需提案"

    # 板面里含未解析队名的场次
    board_path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    value = json.loads(board_path.read_text("utf-8"))
    from nutmeg.decision.alias_audit import board_matches as _rows
    board = [{"home": r.get("homeTeamAbbName"), "away": r.get("awayTeamAbbName")}
             for r in _rows(value)
             if r.get("homeTeamAbbName") in missing or r.get("awayTeamAbbName") in missing]

    aliases = {k: v for k, v in load_team_aliases().items() if not str(k).startswith("_")}
    resolved = {}
    norm_missing = {norm_team(m) for m in missing}
    for cn, en in aliases.items():
        resolved[cn] = en
    # audit 用 norm 匹配;这里以"名字不在缺口列表"为已解析近似(板面缩写与表键一致时成立)
    resolved = {cn: en for cn, en in resolved.items() if norm_team(cn) not in norm_missing}

    if fixtures is None:
        fixtures = _fetch_day_fixtures(run_date)

    got = propose_for_board(board, resolved, fixtures)
    lines = [f"{run_date}: 缺口 {len(missing)} 队 | 提案 {len(got['proposals'])} 条"
             f" | 不可推断 {len(got['unresolvable'])} 场"]
    for p in got["proposals"]:
        lines.append(f"  提案: {p['cn']} → {p['candidate_en']}  (经 {p['via']},{p['fixture']})")
    for u in got["unresolvable"]:
        lines.append(f"  ⚠️ {u['home']} vs {u['away']}: {u['reason']}")
    if apply and got["proposals"]:
        lines.append("写入:")
        lines += [f"  {ln}" for ln in apply_proposals(got["proposals"])]
        lines.append("⚠️写入后请重跑 decision-am 使锚生效,并以 alias-audit 复验")
    return "\n".join(lines)


# ── 足彩截短队名 → 种子实体（2026-10-08）────────────────────────────────────
# 足彩期次用 3–4 字截短名（「埃因霍」「西班人」「海登」），种子里只有全名，于是
# 前提卡与深研 brief 把有 11 条画像的队当成「store 无记录」（26136：16/28 支未命中，
# 其中 5 支种子里其实有）。上面的提案器只认竞彩板 + API-Football 英文名，管不到这里。


def _norm(name: str) -> str:
    from nutmeg.decision.identity import norm_team

    return norm_team(name)


def propose_zucai_aliases(matches: list[dict], zgzcw_rows: list[dict], teams: list[dict],
                          team_table: dict[str, str], league_of) -> dict:
    """→ {proposals: [{cn, team_id, via, match_no}], unresolved: [{cn, match_no, reason}]}

    两条确定性路径（零 LLM，多候选只报告）：
    ① zgzcw 同场全名（同开球时刻对齐）能被别名表解析 → 用它（「埃因霍」经「埃因霍温」）；
    ② 同联赛种子实体里**恰有一支**的中文名/别名以截短名（或 zgzcw 全名）开头 →
       用它（「格勒诺」经前缀对上「格勒诺布尔」）。跨联赛不猜。
    """
    rows = list(zgzcw_rows or [])
    proposals, unresolved = [], []
    seen: set[str] = set()
    for index, m in enumerate(matches):
        no = int(m.get("match_no") or 0)
        # zgzcw 按期次顺序列 14 场；同序且同开球时刻才算同一场（两站短名不同，不能按名配）
        row = rows[index] if index < len(rows) else None
        if row is not None and (str(row.get("gameStartDate") or "")[:16]
                                != str(m.get("kickoff_bj") or "")[:16]):
            row = None
        for short, side in ((m.get("home_team"), "host"), (m.get("away_team"), "guest")):
            short = str(short or "")
            if not short or short in seen or _norm(short) in team_table:
                continue
            seen.add(short)
            full = str(row.get(f"{side}NameFull") or row.get(f"{side}Name") or "") if row else ""
            team_id = team_table.get(_norm(full)) if full else None
            via = f"zgzcw 全名「{full}」" if team_id else ""
            if team_id is None:
                league = league_of(str(m.get("competition") or ""))
                stems = [s for s in (short, full) if len(s) >= 2]
                cands = {
                    t["team_id"] for t in teams
                    if league and league in (t.get("competition_ids") or [])
                    and any(str(a).startswith(stem)
                            for a in [t.get("name_zh"), *(t.get("aliases") or [])] if a
                            for stem in stems)
                }
                if len(cands) == 1:
                    team_id = cands.pop()
                    via = f"同联赛（{league}）前缀唯一"
                else:
                    unresolved.append({"cn": short, "match_no": no, "reason": (
                        f"同联赛前缀歧义 {sorted(cands)}" if cands
                        else f"种子同联赛无匹配（没有这支队，或译名不同；zgzcw 全名「{full}」）"
                        if league else f"联赛「{m.get('competition')}」未解析")})
                    continue
            proposals.append({"cn": short, "team_id": team_id, "via": via, "match_no": no})
    return {"proposals": proposals, "unresolved": unresolved}


def apply_entity_aliases(proposals: list[dict], path: Path | None = None) -> list[str]:
    """把提案写进种子 `teams[].aliases`（已有的不重复写），保持种子原格式。"""
    from nutmeg.decision.entities import seed_path

    target = Path(path) if path else seed_path()
    data = json.loads(target.read_text(encoding="utf-8"))
    by_id = {row.get("team_id"): row for row in data.get("teams") or []}
    lines, changed = [], False
    for p in proposals:
        row = by_id.get(p["team_id"])
        if row is None:
            lines.append(f"跳过 {p['cn']}（种子无 {p['team_id']}）")
            continue
        aliases = row.setdefault("aliases", [])
        if p["cn"] in aliases:
            continue
        aliases.append(p["cn"])
        changed = True
        lines.append(f"+ {p['cn']} → {p['team_id']}  （{p['via']}）")
    if changed:
        target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return lines


def run_propose_zucai(issue: str, zucai_dir, *, apply: bool = False) -> str:
    """CLI 胶水：期次文件 + 最后一张 zgzcw 快照 → 提案（可选写入种子）。"""
    from nutmeg.decision.entities import (
        _ENTITIES_RESOURCE,
        _load_resource,
        load_league_alias_table,
        load_team_alias_table,
        resolve_league,
    )

    zdir = Path(zucai_dir)
    matches = json.loads((zdir / f"{issue}-issue.json").read_text("utf-8")).get("matches") or []
    zg_path = zdir / f"{issue}-zgzcw.json"
    snaps = []
    if zg_path.exists():
        snaps = json.loads(zg_path.read_text("utf-8")).get("snapshots") or []
    rows = ((snaps[-1].get("raw") or {}).get("matchInfo") or []) if snaps else []
    league_table = load_league_alias_table()
    got = propose_zucai_aliases(
        matches, rows, _load_resource(_ENTITIES_RESOURCE).get("teams") or [],
        load_team_alias_table(), lambda name: resolve_league(name, league_table))
    lines = [f"{issue}: 截短名提案 {len(got['proposals'])} 条 | 未解决 {len(got['unresolved'])} 支"
             + ("" if rows else "（无 zgzcw 快照，只走前缀路径）")]
    for p in got["proposals"]:
        lines.append(f"  提案: 场{p['match_no']} {p['cn']} → {p['team_id']}  （{p['via']}）")
    for u in got["unresolved"]:
        lines.append(f"  ⚠️ 场{u['match_no']} {u['cn']}: {u['reason']}")
    if apply and got["proposals"]:
        lines.append("写入种子:")
        lines += [f"  {ln}" for ln in apply_entity_aliases(got["proposals"])]
        lines.append("⚠️写入后跑 decision-entities-sync 让 store 同步别名")
    return "\n".join(lines)
