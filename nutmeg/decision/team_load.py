"""球队损耗台账（2026-10-09，设计稿 docs/superpowers/specs/2026-10-09-team-load-ledger-design.md）。

**测量仪，不是判断参数**：只做取数与确定性算术——出场索引 → 每队特征 → 每场派生 → 落盘冻结。
台账只展示、只记账；任何数字进 belief 之前必须先过 F16 前瞻实证。

事前证据（同一设计稿 §2）：休息天数差被市场完全定价（三档残差≈0，n≈550/档），只有「单边赛程
密集」方向像样但样本太小——所以这里不给任何权重。
"""
from __future__ import annotations

import glob
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from nutmeg.data.sporttery_board import flatten
from nutmeg.decision.bj_time import bj_iso, parse_bj
from nutmeg.decision.files import read_json
from nutmeg.decision.identity import norm_team

COVERAGE = ("竞彩/足彩开售场次（jc-history + 体彩板面 + 足彩期次）+ API-Football 全联赛日程"
            "（`schedule/apifootball/<日>.json`，2026-10-24 起按日累计；免费档只到 today±1，"
            "累计满 14 天前低级别联赛的休息天数仍可能偏长）；国家队出场分钟数没有；"
            "各源深夜场归日不一，误差 ±1 天")
SCHEDULE_DIR = Path("schedule") / "apifootball"
WINDOW_DAYS = 14
LOOKAHEAD_DAYS = 10
LONG_BREAK_DAYS = 12
CONGESTED, SPARSE = 4, 2          # 单边密集：一方 14 天 ≥4 场、另一方 ≤2
TRIGGER_DIFF = 2                  # F16 触发：14 天场数差 ≥2
SOON_DAYS = 3                     # 下一场 ≤3 天（轮换风险）
GAP_SUSPECT_DAYS = 30             # 赛季中休 >30 天多半是没上板的场次缺失（26136 德乙/法乙/北欧）

Resolve = Callable[[str], str | None]


def default_resolver() -> Resolve:
    """队名 → 种子实体 team_id（别名表与前提卡、深研 brief 同一张）。"""
    from nutmeg.decision.entities import load_team_alias_table, resolve_team

    table = load_team_alias_table()
    return lambda name: resolve_team(name, table)


class LoadIndex:
    """每队出场日期索引。同一队相邻 ≤1 天的出场按同一场处理（各源归日不一）。"""

    def __init__(self, resolve: Resolve):
        self._resolve = resolve
        self._days: dict[str, set[date]] = {}

    def key(self, name: str) -> str:
        name = str(name or "").strip()
        return self._resolve(name) or f"name:{norm_team(name)}"

    def add(self, name: str, day: date, *aliases: str) -> None:
        """记一次出场；`aliases`（如体彩全称）用于简称解析不了时再试一次。"""
        key = next((k for k in (self._resolve(n) for n in (name, *aliases) if n) if k), None)
        key = key or self.key(name)
        self._days.setdefault(key, set()).add(day)

    def features(self, name: str, on: date) -> dict:
        days = sorted(self._days.get(self.key(name), ()))
        before = [d for d in days if d <= on - timedelta(days=2)]
        ahead = on + timedelta(days=LOOKAHEAD_DAYS)
        after = [d for d in days if on + timedelta(days=2) <= d <= ahead]
        rest = (on - before[-1]).days if before else None
        return {
            "rest_days": rest,
            "matches_14d": sum(1 for d in before if d >= on - timedelta(days=WINDOW_DAYS)),
            "next_days": (after[0] - on).days if after else None,
            "long_break": rest is not None and rest >= LONG_BREAK_DAYS,
        }


def _date_of(value) -> date | None:
    dt = parse_bj(value)
    if dt is not None:
        return dt.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def build_index(data_dir: Path, resolve: Resolve | None = None) -> LoadIndex:
    """jc-history（业务日）+ 体彩每日板面（matchDate）+ 足彩期次（kickoff_bj）→ 出场索引。"""
    data_dir = Path(data_dir)
    idx = LoadIndex(resolve or default_resolver())
    history = read_json(data_dir / "jczq" / "jc-history.json", {}) or {}
    for day, board in history.items():
        when = _date_of(day)
        if when is None or not isinstance(board, dict):
            continue
        for match in board.values():
            for side in ("home", "away"):
                if isinstance(match, dict) and match.get(side):
                    idx.add(match[side], when)
    boards = data_dir / "jczq" / "daily" / "*" / "sporttery_markets.json"
    for path in sorted(glob.glob(str(boards))):
        doc = read_json(path, {}) or {}
        for raw in flatten(doc.get("value", doc) if isinstance(doc, dict) else {}):
            when = _date_of(raw.get("matchDate"))
            if when is None:
                continue
            for side in ("home", "away"):
                name = raw.get(f"{side}TeamAbbName")
                if name:
                    idx.add(name, when, raw.get(f"{side}TeamAllName") or "")
    for path in sorted(glob.glob(str(data_dir / "zucai" / "*-issue.json"))):
        for match in (read_json(path, {}) or {}).get("matches") or []:
            when = _date_of(match.get("kickoff_bj") or match.get("match_date"))
            if when is None:
                continue
            for side in ("home_team", "away_team"):
                if match.get(side):
                    idx.add(match[side], when)
    # 2026-10-24（26148 复盘结论 2）：全联赛日程补覆盖——没上板的场次也算出场。
    for path in sorted(glob.glob(str(data_dir / SCHEDULE_DIR / "*.json"))):
        for fx in (read_json(path, []) or []):
            when = _date_of(fx.get("date"))
            if when is None or not isinstance(fx, dict):
                continue
            for side in ("home", "away"):
                if fx.get(side):
                    idx.add(fx[side], when)
    return idx


def store_fixtures(data_dir: Path, day: date, fixtures: list, *,
                   source: str = "api-football") -> Path:
    """把一天的全联赛日程落成 `schedule/apifootball/<日>.json`（只存 日期/主/客/联赛；已完赛与
    未赛都算出场，取消/延期不算）。幂等：同日重跑整文件覆盖。"""
    rows = []
    for fx in fixtures:
        status = str(getattr(fx, "status", "") or "")
        if any(x in status.lower() for x in ("cancel", "postpone", "abandon")):
            continue
        rows.append({"date": day.isoformat(), "home": fx.home_team, "away": fx.away_team,
                     "league": getattr(fx, "league_code", None), "source": source})
    path = Path(data_dir) / SCHEDULE_DIR / f"{day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    return path


def fetch_schedule(data_dir: Path, days: list[date]) -> dict:
    """API-Football `fixtures?date=` 逐日拉取并落盘；无 key 优雅降级（与 alias_propose 同契约）。"""
    from nutmeg.config.settings import get_settings
    from nutmeg.data.api_football import ApiFootballClient

    settings = get_settings()
    key = (settings.api_football_key or "").strip()
    if not key:
        return {"written": {}, "skipped": "no api_football_key"}
    client = ApiFootballClient(base_url=settings.api_football_base_url, api_key=key)
    written: dict = {}
    errors: dict = {}
    try:
        for day in days:
            try:
                batch = client.fetch_fixtures_by_date(day)
            except Exception as exc:          # 免费档窗口外（today±1）等：记错继续，不整轮失败
                errors[day.isoformat()] = str(exc).splitlines()[0][:160]
                continue
            written[day.isoformat()] = (str(store_fixtures(data_dir, day, batch.fixtures)),
                                        len(batch.fixtures))
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return {"written": written, "errors": errors}


def absences(rubric: dict | None) -> dict:
    """伤停摘要，只取该场研究 rubric 已答的事实项（不新采集、不推断）。

    rubric 的 p ＝命题为真的概率，answer 由它派生（p≥0.5 → yes）。"""
    items = (rubric or {}).get("items") or {}
    out: dict[str, list[str]] = {"home": [], "away": []}

    def answered(item_id: str) -> dict | None:
        item = items.get(item_id) or {}
        return None if item.get("abstain") else item

    for side in ("home", "away"):
        item = answered(f"F_absence_{side}")
        if item and item.get("answer") == "yes":
            out[side].append("缺阵")
    for item_id, label in (("F_suspension", "停赛"), ("F_rotation", "轮换")):
        item = answered(item_id) or {}
        answer = item.get("answer")
        for side in ("home", "away"):
            if answer in (side, "both"):
                out[side].append(label)
    spine = answered("S_spine_intact") or {}
    anchor = (answered("S_anchor_side") or {}).get("answer")
    if spine.get("answer") == "no" and anchor in out:
        out[anchor].append("中轴缺")
    return out


def _flags(home: dict, away: dict) -> list[str]:
    flags = []
    m14 = {"home": home["matches_14d"], "away": away["matches_14d"]}
    for side, other in (("home", "away"), ("away", "home")):
        if m14[side] >= CONGESTED and m14[other] <= SPARSE:
            flags.append(f"单边密集:{side}")
        if m14[side] - m14[other] >= TRIGGER_DIFF:
            flags.append(f"负荷差≥2:{side}")
    for side, f in (("home", home), ("away", away)):
        if f["next_days"] is not None and f["next_days"] <= SOON_DAYS:
            flags.append(f"下场≤3天:{side}")
    broke = [side for side, f in (("home", home), ("away", away)) if f["long_break"]]
    if broke:
        flags.append("长歇:" + ("both" if len(broke) == 2 else broke[0]))
    return flags


def match_row(index: LoadIndex, *, key: str, home: str, away: str, kickoff: str,
              captured_at: str, rubric: dict | None = None, match_id: str | None = None) -> dict:
    on = _date_of(kickoff)
    home_f, away_f = index.features(home, on), index.features(away, on)
    rest_diff = (None if home_f["rest_days"] is None or away_f["rest_days"] is None
                 else home_f["rest_days"] - away_f["rest_days"])
    return {
        "key": key, "match_id": match_id, "home": home, "away": away,
        "home_key": index.key(home), "away_key": index.key(away),
        "kickoff": bj_iso(kickoff), "captured_at": captured_at,
        "home_load": home_f, "away_load": away_f,
        "rest_diff": rest_diff,
        "load_diff_14": home_f["matches_14d"] - away_f["matches_14d"],
        "flags": _flags(home_f, away_f),
        "absences": absences(rubric),
    }


def merge_rows(old: dict, new: dict, *, now: str) -> dict:
    """已开球的行原样保留（前瞻样本不许事后改），其余换成新算的。"""
    now_dt = parse_bj(now)
    merged = dict(old or {})
    for k, row in new.items():
        prior = merged.get(k)
        kicked = parse_bj((prior or {}).get("kickoff"))
        if prior is not None and kicked is not None and now_dt is not None and kicked <= now_dt:
            continue
        merged[k] = row
    return merged


def _write(path: Path, header: dict, rows: dict, now: str) -> Path:
    old = (read_json(path, {}) or {}).get("rows") or {}
    doc = {**header, "updated_at": now, "coverage": COVERAGE,
           "rows": merge_rows(old, rows, now=now)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def jczq_ledger_rows(data_dir: Path, day: str, *, now: str,
                     index: LoadIndex | None = None) -> dict:
    """竞彩当日板逐场台账行（行键＝编号，key＝`<日>-<编号>`）；没有 legs-base → 空。"""
    data_dir = Path(data_dir)
    day_dir = data_dir / "jczq" / "daily" / day
    legs = (read_json(day_dir / "jczq-legs-base.json", {}) or {}).get("legs") or {}
    if not legs:
        return {}
    index = index or build_index(data_dir)
    rows = {}
    for code, leg in legs.items():
        if not (leg.get("home_team") and leg.get("away_team") and leg.get("kickoff_bj")):
            continue
        research = read_json(day_dir / f"research-{code}.json", {}) or {}
        rows[code] = match_row(index, key=f"{day}-{code}", home=leg["home_team"],
                               away=leg["away_team"], kickoff=leg["kickoff_bj"], captured_at=now,
                               rubric=research.get("rubric") or leg.get("rubric"),
                               match_id=leg.get("match_id"))
    return rows


def zucai_ledger_rows(data_dir: Path, issue: str, *, now: str,
                      index: LoadIndex | None = None) -> dict:
    """足彩期次逐场台账行（行键＝场号，key＝`<期>-<场号>`）；没有期次文件 → 空。"""
    zdir = Path(data_dir) / "zucai"
    matches = (read_json(zdir / f"{issue}-issue.json", {}) or {}).get("matches") or []
    if not matches:
        return {}
    index = index or build_index(Path(data_dir))
    store = read_json(zdir / f"{issue}-store-ids.json", {}) or {}
    rows = {}
    for match in matches:
        no = int(match["match_no"])
        if not (match.get("home_team") and match.get("away_team") and match.get("kickoff_bj")):
            continue
        research = read_json(zdir / f"{issue}-research-m{no}.json", {}) or {}
        rows[str(no)] = match_row(index, key=f"{issue}-{no}", home=match["home_team"],
                                  away=match["away_team"], kickoff=match["kickoff_bj"],
                                  captured_at=now, rubric=research.get("rubric"),
                                  match_id=(store.get(str(no)) or {}).get("match_id"))
    return rows


def write_jczq_ledger(data_dir: Path, day: str, *, now: str,
                      index: LoadIndex | None = None) -> Path | None:
    """→ `jczq/daily/<日>/team-load.json`；已开球的行保留原样。"""
    rows = jczq_ledger_rows(data_dir, day, now=now, index=index)
    if not rows:
        return None
    path = Path(data_dir) / "jczq" / "daily" / day / "team-load.json"
    return _write(path, {"day": day}, rows, now)


def write_zucai_ledger(data_dir: Path, issue: str, *, now: str,
                       index: LoadIndex | None = None) -> Path | None:
    """→ `zucai/<期>-team-load.json`；已开球的行保留原样。"""
    rows = zucai_ledger_rows(data_dir, issue, now=now, index=index)
    if not rows:
        return None
    return _write(Path(data_dir) / "zucai" / f"{issue}-team-load.json", {"issue": issue}, rows, now)


def write_day_ledgers(data_dir: Path, day: str, *, now: str,
                      index: LoadIndex | None = None) -> dict:
    """并集池的一天：竞彩当日板 + 当天截止的足彩期次（与 `research refresh` 同一口径）。"""
    from nutmeg.decision.zucai_identity import closing_issues

    data_dir = Path(data_dir)
    index = index or build_index(data_dir)
    jczq = write_jczq_ledger(data_dir, day, now=now, index=index)
    zucai = {}
    for issue, _doc in closing_issues(data_dir / "zucai", day):
        path = write_zucai_ledger(data_dir, issue, now=now, index=index)
        if path is not None:
            zucai[issue] = str(path)
    return {"jczq": str(jczq) if jczq else None, "zucai": zucai}


def brief_cell(row: dict | None) -> str:
    """初判包「损耗」一格：休 主/客 · 14天 主/客 + 旗 + 伤停缩写（只看不拨动）。"""
    if not row:
        return "—"

    def num(v) -> str:
        if v is None:
            return "?"
        return f"{v}?" if v > GAP_SUSPECT_DAYS else str(v)

    h, a = row["home_load"], row["away_load"]
    text = (f"休{num(h['rest_days'])}/{num(a['rest_days'])} "
            f"14天{h['matches_14d']}/{a['matches_14d']}")
    side_mark = {"home": "主", "away": "客", "both": "双"}
    marks = []
    for flag in row.get("flags") or []:
        name, _, side = flag.partition(":")
        symbol = {"单边密集": "⚑密", "下场≤3天": "⇢", "长歇": "⏸"}.get(name)
        if symbol:
            marks.append(f"{symbol}{side_mark.get(side, side)}")
    hurt = row.get("absences") or {}
    for side in ("home", "away"):
        if hurt.get(side):
            marks.append(side_mark[side] + "".join(x[0] for x in hurt[side]))
    return text + (" " + " ".join(marks) if marks else "")


def attach_ledgers(rows: list[dict], data_dir: Path) -> int:
    """语料 v2：把开球前冻结的台账行挂到行顶层 `team_load`（不进 `labels`，免得虚增
    「带判读标签」计数）。键与台账同形：竞彩 `<日>-<编号>`、足彩 `<期>-<场号>`。返回挂上的行数。"""
    data_dir = Path(data_dir)
    cache: dict[Path, dict] = {}

    def ledger(path: Path) -> dict:
        if path not in cache:
            cache[path] = (read_json(path, {}) or {}).get("rows") or {}
        return cache[path]

    attached = 0
    for row in rows:
        key = str(row.get("key") or "")
        if row.get("src") == "jczq" and len(key) > 11:
            found = ledger(data_dir / "jczq" / "daily" / key[:10] / "team-load.json").get(key[11:])
        elif row.get("src") == "zucai" and "-" in key:
            issue, no = key.split("-", 1)
            found = ledger(data_dir / "zucai" / f"{issue}-team-load.json").get(no)
        else:
            continue
        captured = parse_bj((found or {}).get("captured_at"))
        kickoff = parse_bj((found or {}).get("kickoff"))
        if captured is None or kickoff is None or captured >= kickoff:
            continue
        row["team_load"] = found
        attached += 1
    return attached


def now_bj() -> str:
    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ).isoformat(timespec="seconds")
