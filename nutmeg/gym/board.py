"""历史板面/期次：只装"下单时刻可得"的信息；赛果与奖金只给结算器。

竞彩：每天一份 17:00 体彩快照（含次日/后日场次）。板面日 D 的"策略可见"场＝D 快照里
businessDate==D 且仍在售（Selling、有 had 价）的场＝假设 17:00 下单；17:00 前已开球的早场
（如 13:00 的 J 联赛）从 D−1 快照补进 `all_matches`（真票可能头天晚上就买了），连同 D 快照里
businessDate>D 的次日场一起只供真票结算与合法性检查，不进策略视野。终盘（titan007 sharp）
是开球时刻的价，只许作 belief 源，不许作可买价格。
足彩：期次 14 场 + 去水赔率 + 官方奖金缓存（`gym.prizes`）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from nutmeg.gym.prizes import load_prizes

FACES = ("home", "draw", "away")
CODE_OF = {"home": "3", "draw": "1", "away": "0"}
FACE_OF = {"3": "home", "1": "draw", "0": "away"}
_HDA = {"h": "3", "d": "1", "a": "0"}


def devig(odds: dict[str, float]) -> dict[str, float]:
    inv = {k: 1 / float(v) for k, v in odds.items()}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()}


@dataclass(frozen=True)
class JczqMatch:
    code: str
    business_date: str
    name: str
    league: str
    kickoff_bj: str | None
    selling: bool                          # 快照时刻仍在售
    had: dict[str, float]                  # {"3","1","0"} 体彩赔率；未开盘则 {}
    hhad: dict | None                      # {"line": float, "3","1","0"}
    ttg: dict[str, float] | None           # {"0".."7"}
    crs: dict[str, float] | None           # {"s01s02": 赔率, …}
    single_allowed: dict[str, bool]        # {"had": bool, "hhad": bool, …}
    closing_fair: dict[str, float] | None  # titan007 sharp fair（开球时刻；home/draw/away）
    read_belief: dict[str, float] | None   # 仅 provably_prospective 的研究 belief
    sp: dict | None = None                 # 历史板：开奖 SP（只有开出那个面的赔率）

    @property
    def belief_market(self) -> dict[str, float]:
        if len(self.had) != 3:
            raise ValueError(f"{self.code} 无 had 价")
        return {FACE_OF[k]: v for k, v in devig(self.had).items()}

    @property
    def belief_any(self) -> dict[str, float] | None:
        """能当 belief 用的市场分布：有 had 价用 had，否则用终盘；都没有 → None。"""
        if len(self.had) == 3:
            return self.belief_market
        return dict(self.closing_fair) if self.closing_fair else None


@dataclass(frozen=True)
class JczqBoard:
    day: str
    matches: dict[str, JczqMatch]                       # 策略可见：本日、在售、有 had
    extra: dict[str, JczqMatch] = field(default_factory=dict)   # 只供结算：早场补录 + 次日场
    results: dict[str, dict] = field(default_factory=dict)      # {code: {outcome_90, goals, ht}}
    allup: dict[str, list[str]] = field(default_factory=dict)   # {pool: 允许的过关方式}
    source: str = "snapshot"                             # snapshot | history_sp

    def lookup(self, code: str) -> JczqMatch | None:
        return self.matches.get(code) or self.extra.get(code)

    def visible(self) -> JczqBoard:
        return replace(self, results={}, extra={})


@dataclass(frozen=True)
class ZucaiMatch:
    no: str
    name: str
    kickoff_bj: str | None
    fair: dict[str, float]


@dataclass(frozen=True)
class ZucaiIssue:
    issue: str
    sale_deadline: str | None
    matches: dict[str, ZucaiMatch]
    results: str | None = None            # "3 1 0 … *"
    prizes: dict | None = None            # official-prizes 行

    @property
    def void(self) -> set[int]:
        return {i + 1 for i, c in enumerate((self.results or "").split()) if c == "*"}

    def visible(self) -> ZucaiIssue:
        return replace(self, results=None, prizes=None)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _outcome(gh: int, ga: int) -> str:
    return "home" if gh > ga else ("draw" if gh == ga else "away")


def _hda(raw: dict | None) -> dict[str, float]:
    if not raw:
        return {}
    try:
        out = {_HDA[k]: float(raw[k]) for k in ("h", "d", "a")}
    except (KeyError, TypeError, ValueError):
        return {}
    return out if all(v > 1 for v in out.values()) else {}


def _numeric_pool(raw: dict | None, prefix_len: int = 1) -> dict[str, float] | None:
    """ttg: s0..s7 → {"0".."7"}；crs: s01s02 → {"s01s02"}。跳过 *f 变动标志与空值。"""
    if not raw:
        return None
    out: dict[str, float] = {}
    for key, value in raw.items():
        if not key.startswith("s") or key.endswith("f") or value in (None, ""):
            continue
        try:
            out[key[prefix_len:] if key[1:].isdigit() else key] = float(value)
        except ValueError:
            continue
    return out or None


def _snapshot_rows(data_dir: Path, day: str) -> tuple[list[dict], dict]:
    doc = _read(data_dir / "jczq" / "daily" / day / "sporttery_markets.json", None)
    if not isinstance(doc, dict):
        return [], {}
    rows = []
    for group in doc.get("matchInfoList") or []:
        for raw in group.get("subMatchList") or []:
            business = str(raw.get("businessDate") or group.get("businessDate") or "")
            if raw.get("matchNumStr") and business:
                rows.append({**raw, "_business": business})
    return rows, doc


def _match(raw: dict, closing: dict) -> JczqMatch:
    code = str(raw["matchNumStr"])
    hhad_raw = raw.get("hhad") or {}
    hhad = _hda(hhad_raw)
    line = hhad_raw.get("goalLineValue") or hhad_raw.get("goalLine")
    try:
        hhad_full = {"line": float(line), **hhad} if hhad and line not in (None, "") else None
    except ValueError:
        hhad_full = None
    pools = {str(p.get("poolCode", "")).lower(): p for p in raw.get("poolList") or []}
    sharp = (closing.get(code) or {}).get("sharp") or {}
    when = f"{raw.get('matchDate')}T{raw.get('matchTime')}+08:00" if raw.get("matchDate") else None
    return JczqMatch(
        code=code, business_date=raw["_business"],
        name=f"{raw.get('homeTeamAbbName') or ''}-{raw.get('awayTeamAbbName') or ''}",
        league=str(raw.get("leagueAbbName") or ""), kickoff_bj=when,
        selling=str(raw.get("matchStatus") or "").casefold() == "selling",
        had=_hda(raw.get("had")), hhad=hhad_full,
        ttg=_numeric_pool(raw.get("ttg")), crs=_numeric_pool(raw.get("crs"), prefix_len=0),
        single_allowed={pool: p.get("single") == 1 for pool, p in pools.items()},
        closing_fair=sharp.get("fair_probability") or None,
        read_belief=None,
    )


def _result_row(results_doc: dict, business_date: str, code: str) -> dict | None:
    row = (results_doc.get(business_date) or {}).get(code)
    if not row or row.get("ft_home") is None or row.get("ft_away") is None:
        return None
    out = {"outcome_90": _outcome(int(row["ft_home"]), int(row["ft_away"])),
           "goals_h": int(row["ft_home"]), "goals_a": int(row["ft_away"])}
    if row.get("ht_home") is not None and row.get("ht_away") is not None:
        out["ht_h"], out["ht_a"] = int(row["ht_home"]), int(row["ht_away"])
    return out


_SP_FACE = {"胜": "home", "平": "draw", "负": "away"}


def load_history_board(data_dir: Path, day: str) -> JczqBoard:
    """历史板（假期迭代 #5）：`jc-history.json[day]` 的赛果 + 开奖 SP，终盘作 belief。

    没有三面全价：策略只能用终盘当 belief，派奖按开奖 SP；单关一律视为不开。"""
    data_dir = Path(data_dir)
    history = (_read(data_dir / "jczq" / "jc-history.json", {}) or {}).get(day)
    if not history:
        raise FileNotFoundError(f"{day} 无历史板")
    closing = _read(data_dir / "jczq" / "daily" / day / "closing_odds.json", {}) or {}
    matches: dict[str, JczqMatch] = {}
    results: dict[str, dict] = {}
    for code, rec in history.items():
        sharp = (closing.get(code) or {}).get("sharp") or {}
        sp = rec.get("sp") or None
        matches[code] = JczqMatch(
            code=code, business_date=day, name=f"{rec.get('home', '')}-{rec.get('away', '')}",
            league="", kickoff_bj=None, selling=True, had={}, hhad=None, ttg=None, crs=None,
            single_allowed={}, closing_fair=sharp.get("fair_probability") or None,
            read_belief=None, sp=sp,
        )
        if rec.get("ft_home") is not None and rec.get("ft_away") is not None:
            row = {"outcome_90": _outcome(int(rec["ft_home"]), int(rec["ft_away"])),
                   "goals_h": int(rec["ft_home"]), "goals_a": int(rec["ft_away"])}
            if rec.get("ht_home") is not None and rec.get("ht_away") is not None:
                row["ht_h"], row["ht_a"] = int(rec["ht_home"]), int(rec["ht_away"])
            results[code] = row
    return JczqBoard(day=day, matches=matches, results=results, source="history_sp")


def load_jczq_board(data_dir: Path, day: str, *, allow_history: bool = False) -> JczqBoard:
    data_dir = Path(data_dir)
    rows, doc = _snapshot_rows(data_dir, day)
    if not doc:
        if allow_history:
            return load_history_board(data_dir, day)
        raise FileNotFoundError(f"{day} 无板面快照")
    closing = _read(data_dir / "jczq" / "daily" / day / "closing_odds.json", {}) or {}
    results_doc = _read(data_dir / "jczq" / "jc-results.json", {}) or {}
    prev_day = (_date.fromisoformat(day) - timedelta(days=1)).isoformat()
    prev_rows, _ = _snapshot_rows(data_dir, prev_day)

    matches: dict[str, JczqMatch] = {}
    extra: dict[str, JczqMatch] = {}
    for raw in rows:
        m = _match(raw, closing)
        if m.business_date == day:
            if m.selling and len(m.had) == 3:
                matches[m.code] = m
            else:
                extra[m.code] = m
        elif m.business_date > day:
            extra[m.code] = m
    for raw in prev_rows:                          # 早场补录：D 快照里已不在的本日场
        if raw["_business"] == day and raw["matchNumStr"] not in matches \
                and raw["matchNumStr"] not in extra:
            extra[str(raw["matchNumStr"])] = _match(raw, closing)

    # 作废登记（延期 >36h 体彩按取消：腿算中、赔率按 1）：jczq/void-matches.json = {板面日: [编号]}
    void_doc = _read(data_dir / "jczq" / "void-matches.json", {}) or {}
    results: dict[str, dict] = {}
    for code, m in {**matches, **extra}.items():
        row = _result_row(results_doc, m.business_date, code)
        if row:
            results[code] = row
        elif code in (void_doc.get(m.business_date) or []):
            results[code] = {"void": True}
    allup = {
        str(pool).lower(): sorted({row.get("formula") for row in rows_ if row.get("formula")})
        for pool, rows_ in (doc.get("allUpList") or {}).items()
    }
    return JczqBoard(day=day, matches=matches, extra=extra, results=results, allup=allup)


def _zucai_odds(doc) -> dict[str, dict[str, float]]:
    """两种历史形状：list[{match_no, home, draw, away}] 或 {no: {"odds": [h, d, a]}}。"""
    out: dict[str, dict[str, float]] = {}
    matches = (doc or {}).get("matches") if isinstance(doc, dict) else None
    if isinstance(matches, list):
        for m in matches:
            if isinstance(m, dict) and all(k in m for k in ("match_no", "home", "draw", "away")):
                out[str(m["match_no"])] = {"home": m["home"], "draw": m["draw"], "away": m["away"]}
    elif isinstance(matches, dict):
        for no, m in matches.items():
            if isinstance(m, dict) and isinstance(m.get("odds"), list) and len(m["odds"]) == 3:
                h, d, a = m["odds"]
                out[str(no)] = {"home": h, "draw": d, "away": a}
            elif isinstance(m, dict) and all(k in m for k in ("home", "draw", "away")):
                out[str(no)] = {"home": m["home"], "draw": m["draw"], "away": m["away"]}
    return out


def load_zucai_issue(data_dir: Path, issue: str) -> ZucaiIssue:
    zdir = Path(data_dir) / "zucai"
    doc = _read(zdir / f"{issue}-issue.json", None)
    if doc is None:
        raise FileNotFoundError(f"{issue} 无 issue.json")
    odds = _zucai_odds(_read(zdir / f"{issue}-odds.json", {}))
    matches: dict[str, ZucaiMatch] = {}
    for m in doc.get("matches") or []:
        no = str(m["match_no"])
        row = odds.get(no)
        if not row:
            continue
        try:
            fair = devig(row)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        matches[no] = ZucaiMatch(no=no, name=f"{m.get('home_team')}-{m.get('away_team')}",
                                 kickoff_bj=m.get("kickoff_bj"), fair=fair)
    prize = load_prizes(zdir).get(issue)
    return ZucaiIssue(issue=issue, sale_deadline=doc.get("sale_deadline") or doc.get("sale_stop"),
                      matches=matches, results=prize["results"] if prize else None, prizes=prize)


def list_days(data_dir: Path, *, include_history: bool = False) -> list[str]:
    """有体彩快照且有赛果的板面日；`include_history` 再并入只有 jc-history 的日子（SP 板）。"""
    data_dir = Path(data_dir)
    results = _read(data_dir / "jczq" / "jc-results.json", {}) or {}
    root = data_dir / "jczq" / "daily"
    days = set()
    if root.exists():
        days = {d.name for d in root.iterdir()
                if (d / "sporttery_markets.json").exists() and d.name in results}
    if include_history:
        history = _read(data_dir / "jczq" / "jc-history.json", {}) or {}
        days |= {d for d, rows in history.items() if rows and d not in days}
    return sorted(days)


def list_issues(data_dir: Path) -> list[str]:
    """有 issue.json、odds.json 和官方奖金的期次。"""
    zdir = Path(data_dir) / "zucai"
    prizes = load_prizes(zdir)
    out = []
    for path in zdir.glob("*-issue.json"):
        issue = path.name.split("-")[0]
        if issue in prizes and (zdir / f"{issue}-odds.json").exists():
            out.append(issue)
    return sorted(out)
