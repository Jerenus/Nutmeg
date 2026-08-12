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


def run_propose(run_date: str, output_dir, *, apply: bool = False,
                fixtures: list[dict] | None = None) -> str:
    """CLI 胶水：读当日板面 audit 缺口 → 拉当日 fixtures → 提案（可选写入）。"""
    from nutmeg.decision.alias_audit import audit_day
    from nutmeg.decision.identity import norm_team
    from nutmeg.services.jczq_apifootball_odds import load_team_aliases

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
        from nutmeg.services.jczq_apifootball_odds import fetch_fixtures_by_date
        fixtures = fetch_fixtures_by_date(run_date)

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
