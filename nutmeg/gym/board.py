"""历史板面/期次：只装"下单时刻可得"的信息；赛果与奖金只给结算器。

竞彩：每天一份 17:00 体彩快照（含次日场次，按 businessDate 归到各自的板）＝假设 17:00 下单；
终盘（titan007 sharp）是开球时刻的价，只许作 belief 源，不许作可买价格。
足彩：期次 14 场 + 去水赔率 + 官方奖金缓存（`gym.prizes`）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from nutmeg.gym.prizes import load_prizes
from nutmeg.ontology.ingest.sporttery import parse_sporttery_markets

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
    name: str
    league: str
    kickoff_bj: str | None
    had: dict[str, float]                  # {"3","1","0"} 体彩赔率（17:00 快照）
    hhad: dict | None                      # {"line": float, "3","1","0"}
    ttg: dict[str, float] | None           # {"0".."7"}
    crs: dict[str, float] | None           # {"s01s02": 赔率, …}
    single_allowed: dict[str, bool]        # {"had": bool, "hhad": bool}
    closing_fair: dict[str, float] | None  # titan007 sharp fair（开球时刻；home/draw/away）
    read_belief: dict[str, float] | None   # 仅 provably_prospective 的研究 belief

    @property
    def belief_market(self) -> dict[str, float]:
        return {FACE_OF[k]: v for k, v in devig(self.had).items()}


@dataclass(frozen=True)
class JczqBoard:
    day: str
    matches: dict[str, JczqMatch]
    results: dict[str, dict] = field(default_factory=dict)   # {code: {outcome_90, goals_h/a}}
    allup: dict[str, list[str]] = field(default_factory=dict)  # {pool: 允许的过关方式}

    def visible(self) -> JczqBoard:
        return replace(self, results={})


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


def _hda(raw: dict | None) -> dict[str, float] | None:
    if not raw:
        return None
    try:
        out = {_HDA[k]: float(raw[k]) for k in ("h", "d", "a")}
    except (KeyError, TypeError, ValueError):
        return None
    return out if all(v > 1 for v in out.values()) else None


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


def load_jczq_board(data_dir: Path, day: str) -> JczqBoard:
    data_dir = Path(data_dir)
    day_dir = data_dir / "jczq" / "daily" / day
    doc = _read(day_dir / "sporttery_markets.json", None)
    if doc is None:
        raise FileNotFoundError(f"{day} 无板面快照")
    closing = _read(day_dir / "closing_odds.json", {}) or {}
    results_raw = (_read(data_dir / "jczq" / "jc-results.json", {}) or {}).get(day) or {}
    raw_by_code = {
        str(r.get("matchNumStr")): r
        for d in doc.get("matchInfoList") or []
        for r in d.get("subMatchList") or []
        if str(r.get("businessDate") or d.get("businessDate") or "") == day
    }
    matches: dict[str, JczqMatch] = {}
    for m in parse_sporttery_markets(doc, business_date=day):
        raw = raw_by_code.get(m.match_no) or {}
        had = _hda(raw.get("had"))
        if not had:
            continue
        hhad_raw = raw.get("hhad") or {}
        hhad = _hda(hhad_raw)
        line = hhad_raw.get("goalLineValue") or hhad_raw.get("goalLine")
        try:
            hhad = {"line": float(line), **hhad} if hhad and line not in (None, "") else None
        except ValueError:
            hhad = None
        pools = {str(p.get("poolCode", "")).lower(): p for p in raw.get("poolList") or []}
        sharp = (closing.get(m.match_no) or {}).get("sharp") or {}
        matches[m.match_no] = JczqMatch(
            code=m.match_no, name=f"{m.home_name}-{m.away_name}", league=m.league_name,
            kickoff_bj=m.scheduled_at, had=had, hhad=hhad,
            ttg=_numeric_pool(raw.get("ttg")), crs=_numeric_pool(raw.get("crs"), prefix_len=0),
            single_allowed={"had": pools.get("had", {}).get("single") == 1,
                            "hhad": pools.get("hhad", {}).get("single") == 1},
            closing_fair=sharp.get("fair_probability") or None,
            read_belief=None,
        )
    results = {
        code: {"outcome_90": _outcome(int(r["ft_home"]), int(r["ft_away"])),
               "goals_h": int(r["ft_home"]), "goals_a": int(r["ft_away"])}
        for code, r in results_raw.items()
        if r.get("ft_home") is not None and r.get("ft_away") is not None
    }
    allup = {
        str(pool).lower(): sorted({row.get("formula") for row in rows if row.get("formula")})
        for pool, rows in (doc.get("allUpList") or {}).items()
    }
    return JczqBoard(day=day, matches=matches, results=results, allup=allup)


def load_zucai_issue(data_dir: Path, issue: str) -> ZucaiIssue:
    zdir = Path(data_dir) / "zucai"
    doc = _read(zdir / f"{issue}-issue.json", None)
    if doc is None:
        raise FileNotFoundError(f"{issue} 无 issue.json")
    odds = {
        str(m["match_no"]): m
        for m in (_read(zdir / f"{issue}-odds.json", {}) or {}).get("matches") or []
    }
    matches: dict[str, ZucaiMatch] = {}
    for m in doc.get("matches") or []:
        no = str(m["match_no"])
        row = odds.get(no)
        if not row:
            continue
        fair = devig({"home": row["home"], "draw": row["draw"], "away": row["away"]})
        matches[no] = ZucaiMatch(no=no, name=f"{m.get('home_team')}-{m.get('away_team')}",
                                 kickoff_bj=m.get("kickoff_bj"), fair=fair)
    prize = load_prizes(zdir).get(issue)
    return ZucaiIssue(issue=issue, sale_deadline=doc.get("sale_deadline") or doc.get("sale_stop"),
                      matches=matches, results=prize["results"] if prize else None, prizes=prize)


def list_days(data_dir: Path) -> list[str]:
    """有体彩快照且有赛果的板面日。"""
    data_dir = Path(data_dir)
    results = _read(data_dir / "jczq" / "jc-results.json", {}) or {}
    root = data_dir / "jczq" / "daily"
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir()
                  if (d / "sporttery_markets.json").exists() and d.name in results)


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
