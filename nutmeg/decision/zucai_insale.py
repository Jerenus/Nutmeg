"""传统足彩在售期板面 live 源 —— 从在售页一次拿全 14 场 + 去水 fair。

旧 lane(`zucai-auto-run`)从来只读预抓文件,`fetch_zucai` 的 live 路径也要求外部
喂 source_url,**没有一条能无人值守跑**——26101/26102 的 `-issue.json`/`-odds.json`
都是手工准备的。这个模块补上那一段。

在售页 `https://trade.500.com/sfc/` 服务端就渲染了全部 14 行,每行带::

    <tr class="bet-tb-tr" data-cid="1" data-vs="阿拉木vs索斯基"
        data-pjgl="37.09,29.55,33.36" data-asian="0.80,平手,0.98">

``data-pjgl`` = **平均概率**(多家公司平均赔率换算,三路和恒为 100.00)= 已去水的
市场 fair,正是判读要的锚,省掉"抓赔率再去水"一步。为不引入第二套 schema,落盘时
换算回隐含赔率 ``1/p`` 写进既有的 ``-odds.json``(对和为 1 的分布,去水是恒等变换)。

⚠️``data-asian``(亚盘)只作参考落盘,**不进任何算术**:体彩 hhad 是三路胜平负,
拿亚盘口径读受让腿会系统性高估约 28pp(见 jczq_hhad_3way_vs_asian_handicap)。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from nutmeg.decision.zucai_gate import INSALE_URL, _default_fetcher, _resolve_year

_ROW_RE = re.compile(r'<tr class="bet-tb-tr[^"]*"(.*?)</tr>', re.S)
_ATTR = {k: re.compile(rf'data-{k}="([^"]*)"') for k in ("cid", "vs", "pjgl", "asian")}
_LEAGUE_RE = re.compile(r'td-evt"><a[^>]*>([^<]*)</a>')
_TIME_RE = re.compile(r'td-endtime">([^<]*)<')
_TEAM_RE = re.compile(r'class="team-[lr]">([^<]+)</a>')


def _kickoff(raw: str, today: date) -> tuple[str, str]:
    """"08-12 00:00" → ("2026-08-12 00:00", "2026-08-12")。年份按离 today 最近推断。"""
    m = re.match(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", (raw or "").strip())
    if not m:
        return "", ""
    mon, day, hour, minute = (int(x) for x in m.groups())
    year = _resolve_year(mon, day, today)
    when = datetime(year, mon, day, hour, minute)
    return when.strftime("%Y-%m-%d %H:%M"), when.strftime("%Y-%m-%d")


def _fair(raw: str) -> dict | None:
    """"37.09,29.55,33.36" → {home,draw,away} 归一化概率。"""
    try:
        vals = [float(x) for x in (raw or "").split(",")]
    except ValueError:
        return None
    if len(vals) != 3 or sum(vals) <= 0:
        return None
    total = sum(vals)
    return dict(zip(("home", "draw", "away"), [v / total for v in vals], strict=True))


def parse_board(html: str, *, today: date | None = None,
                source_url: str = INSALE_URL) -> dict | None:
    """在售页 HTML → {issue, deadline, matches[...]}。任何结构性缺失返回 None。"""
    from nutmeg.decision.zucai_gate import parse_insale

    today = today or date.today()
    insale = parse_insale(html, today=today, source_url=source_url)
    if insale is None:
        return None
    matches = []
    for row in _ROW_RE.findall(html):
        cid = _ATTR["cid"].search(row)
        pjgl = _ATTR["pjgl"].search(row)
        if not cid:
            continue
        teams = _TEAM_RE.findall(row)
        lg = _LEAGUE_RE.search(row)
        tm = _TIME_RE.search(row)
        kickoff, mdate = _kickoff(tm.group(1) if tm else "", today)
        asian = _ATTR["asian"].search(row)
        matches.append({
            "match_no": int(cid.group(1)),
            "competition": lg.group(1).strip() if lg else "",
            "home_team": teams[0].strip() if teams else "",
            "away_team": teams[1].strip() if len(teams) > 1 else "",
            "kickoff_bj": kickoff,
            "match_date": mdate,
            "fair_had": _fair(pjgl.group(1)) if pjgl else None,
            # 仅参考,不进算术(体彩 hhad 是三路,不是亚盘)
            "asian_ref": asian.group(1) if asian else None,
        })
    matches.sort(key=lambda m: m["match_no"])
    if len(matches) != 14:
        return None
    return {"issue": insale.issue,
            "deadline": insale.deadline.strftime("%Y-%m-%d %H:%M"),
            "source_url": insale.source_url,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "matches": matches}


def write_snapshots(board: dict, zucai_dir: Path, *, slot: str = "afternoon") -> dict:
    """落成 build_prep 已在读的两个文件,不新增 schema。"""
    zdir = Path(zucai_dir)
    zdir.mkdir(parents=True, exist_ok=True)
    issue = board["issue"]

    issue_doc = {
        "issue_id": issue,
        "sale_deadline": board["deadline"],
        "sources": [{"label": "500.com 胜负彩在售页", "url": board["source_url"],
                     "captured_at": board["captured_at"]}],
        "matches": [{k: m[k] for k in ("match_no", "competition", "home_team",
                                       "away_team", "kickoff_bj", "match_date")}
                    | {"asian_ref": m["asian_ref"]}
                    for m in board["matches"]],
    }
    # 与 zucai_prep.build_prep 的读端一致:只有 revision 走 -odds-revision.json,
    # morning/afternoon 都是当日基线 -odds.json(26123 出生事故:morning 写错文件)
    odds_name = f"{issue}-odds-revision.json" if slot == "revision" \
        else f"{issue}-odds.json"
    odds_doc = {
        "issue_id": issue,
        "captured_at": board["captured_at"],
        "slot": slot,
        "sources": [{"label": "500.com 在售页 data-pjgl(多家均值平均概率,已去水)",
                     "url": board["source_url"]}],
        "matches": [{"match_no": m["match_no"],
                     # 概率 → 隐含赔率;对和为 1 的分布再去水是恒等变换
                     "home": round(1 / m["fair_had"]["home"], 4),
                     "draw": round(1 / m["fair_had"]["draw"], 4),
                     "away": round(1 / m["fair_had"]["away"], 4)}
                    for m in board["matches"] if m["fair_had"]],
    }
    issue_path = zdir / f"{issue}-issue.json"
    odds_path = zdir / odds_name
    issue_path.write_text(json.dumps(issue_doc, ensure_ascii=False, indent=1), "utf-8")
    odds_path.write_text(json.dumps(odds_doc, ensure_ascii=False, indent=1), "utf-8")
    return {"issue": issue, "issue_path": issue_path, "odds_path": odds_path,
            "n_matches": len(issue_doc["matches"]),
            "n_priced": len(odds_doc["matches"])}


def fetch_and_write(zucai_dir: Path, *, slot: str = "afternoon",
                    today: date | None = None, fetcher=None,
                    issue: str | None = None) -> dict:
    """抓在售页 → 落 issue/odds 快照。失败抛异常,由编排层转成可见告警。"""
    if issue is not None and not re.fullmatch(r"[0-9]{5}", issue):
        raise ValueError(f"Invalid issue: {issue}")
    source_url = f"{INSALE_URL}?expect={issue}" if issue else INSALE_URL
    html = (fetcher or _default_fetcher)(source_url)
    board = parse_board(html, today=today, source_url=source_url)
    if board is None:
        raise ValueError("在售页解析失败(页面结构变化或未满 14 场)")
    if issue is not None and board["issue"] != issue:
        raise ValueError(f"Issue mismatch: expected {issue}, got {board['issue']}")
    return write_snapshots(board, zucai_dir, slot=slot)


def business_dates(board: dict) -> list[str]:
    """这一期覆盖的业务日(欧战期常横跨 3-4 天),供板面加载使用。"""
    out: set[str] = set()
    for m in board.get("matches", []):
        if not m.get("match_date"):
            continue
        day = date.fromisoformat(m["match_date"])
        for offset in (-1, 0):
            out.add((day + timedelta(days=offset)).isoformat())
    return sorted(out)
