"""夜间结果校准（确定性算术层）。

胜负彩 90 分钟口径：赛果取 `jczq/jc-results.json` 的终场比分（竞彩 90' 口径，加时/点球
不计）。身份纪律（2026-10-01 设计系列第 6 条）：足彩场号 → 内核 match_id 必须来自
`{issue}-channel-map.json`（人工）或 `.auto.json`（自动、同一张表），内核 match_id →
竞彩编号来自该板面日的 `jczq/daily/<日>/jczq-legs-base.json`；任一环缺失即显式跳过，
禁止按队名猜测回退。API-Football + `{issue}-af-map.json` 那条路 2026-10-01 退役：
af-map 是每期手工 curl 拼的第二套身份表，与 channel-map 重复且常缺（26134 就没有，
当晚校准全报「无映射」）。
本模块不写 rx、不写 scoreboard——判断与复盘留在主循环。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.match_results import board_outcomes


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def load_channel_map(zucai_dir, issue: str) -> dict[str, str]:
    """{issue}-channel-map(.auto).json（match_id → 场号）→ {match_no(str): match_id}。

    人工表优先；缺两份=空映射（全场显式跳过）。
    """
    base = Path(zucai_dir)
    for name in (f"{issue}-channel-map.json", f"{issue}-channel-map.auto.json"):
        data = _read_json(base / name, None)
        if isinstance(data, dict) and data:
            return {str(no): str(mid) for mid, no in data.items()}
    return {}


def board_results(data_dir, day: str) -> dict[str, dict]:
    """板面日 day 的竞彩终场 → {match_id: {code, ft, home, away, jc_code}}。

    legs-base 给身份（编号 ↔ match_id），`match_results` 给比分；缺终场的场不进表。
    """
    data_dir = Path(data_dir)
    legs = (_read_json(data_dir / "jczq" / "daily" / day / "jczq-legs-base.json", {})
            or {}).get("legs") or {}
    results = board_outcomes(data_dir, day)
    out: dict[str, dict] = {}
    for code, leg in legs.items():
        mid, res = leg.get("match_id"), results.get(code)
        if not mid or res is None:
            continue
        out[str(mid)] = {
            "code": res["outcome_90"], "ft": f"{res['goals_h']}-{res['goals_a']}",
            "jc_code": code,
            "home": leg.get("home_team") or "", "away": leg.get("away_team") or "",
        }
    return out


def night_results(matches: list[dict], channel_map: dict[str, str],
                  board: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """逐场解析当夜彩果。返回 (results, skipped)。

    results = {match_no: {code, ft, home, away, jc_code, match_id}}；
    skipped 逐条给出机器可读理由——缺失不静默变确定性。
    """
    results: dict[str, dict] = {}
    skipped: list[str] = []
    for m in matches:
        no = str(m["match_no"])
        mid = channel_map.get(no)
        if mid is None:
            skipped.append(f"场{no}: channel-map 无映射（不在竞彩板或未对齐）")
            continue
        row = board.get(mid)
        if row is None:
            skipped.append(f"场{no}: {mid} 该板面日无终场（未开赛、非本夜或赛果未封存）")
            continue
        results[no] = {**row, "match_id": mid}
    return results, skipped


def ticket_partial_status(faces: dict, codes: dict[str, str]) -> dict:
    """期中口径的复式票状态。faces={场次: "31"...}, codes={场次: 彩果}。

    与 zucai_official.ticket_hits 的区别：hits 是终局全量口径，
    这里区分 已中/已死/未决 三态，供夜间报告与在场监控使用。
    """
    faces = {str(k): str(v) for k, v in faces.items()}
    hit = sorted((no for no, f in faces.items()
                  if no in codes and codes[no] in set(f)), key=int)
    dead = sorted((no for no, f in faces.items()
                   if no in codes and codes[no] not in set(f)), key=int)
    undecided = sorted((no for no in faces if no not in codes), key=int)
    return {"alive": not dead, "hit": hit, "dead": dead, "undecided": undecided}


def render_report(issue: str, date: str, results: dict[str, dict],
                  skipped: list[str], tickets: list[dict]) -> str:
    lines = [f"== {issue} 夜间校准 {date} (jc-results 板面, 90' 口径) =="]
    for no in sorted(results, key=int):
        r = results[no]
        lines.append(f"场{no} {r['home']} vs {r['away']}: {r['ft']}(90') → {r['code']}"
                     f" [{r['jc_code']}]")
    codes = {no: r["code"] for no, r in results.items()}
    for t in tickets:
        st = ticket_partial_status(t["faces"], codes)
        state = "存活" if st["alive"] else f"已死(断腿 {','.join(st['dead'])})"
        tid = t.get("id") or t.get("slip_id") or "?"
        lines.append(f"{tid}: {state} | 已中 {','.join(st['hit']) or '-'}"
                     f" | 未决 {','.join(st['undecided']) or '-'}")
    lines.extend(skipped)
    return "\n".join(lines)


def run_night_calibrate(issue: str, date: str, zucai_dir, *, data_dir=None) -> str:
    """一次夜间校准：读板面赛果→按身份链解析→存活→快照→报告。只读 + 写快照，不碰 rx/scoreboard。

    date = 竞彩板面日（jc-results 的键；北京凌晨场归前一天板面）。
    """
    from datetime import datetime, timezone

    zucai_dir = Path(zucai_dir)
    data_dir = Path(data_dir) if data_dir is not None else zucai_dir.parent
    issue_doc = json.loads((zucai_dir / f"{issue}-issue.json").read_text("utf-8"))
    channel_map = load_channel_map(zucai_dir, issue)
    board = board_results(data_dir, date)
    results, skipped = night_results(issue_doc["matches"], channel_map, board)

    tickets_path = zucai_dir / f"{issue}-final-tickets.json"
    tickets = (json.loads(tickets_path.read_text("utf-8"))["tickets"]
               if tickets_path.exists() else [])

    snap_path = zucai_dir / f"{issue}-night-{date}-jc.json"
    snap_path.write_text(json.dumps({
        "issue": issue,
        "source": f"jczq/jc-results.json[{date}] via channel-map + legs-base (90' 口径)",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": results,
        "skipped": skipped,
    }, ensure_ascii=False, indent=1), "utf-8")

    return render_report(issue, date, results, skipped, tickets)
