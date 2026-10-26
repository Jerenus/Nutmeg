"""足彩售后播报去会话化（2026-10-26 Tier 1 #5）：首发复核 / 停售倒计时 / 18:30 位移 diff。

26150 期 21:00 首发复核与 18:30 位移 diff 都没发出——播报挂在会话 turn 上，没有 turn 就没有
播报。本模块由 launchd 每 15 分钟跑一次（`com.nutmeg.zucai.lineups`），**只推需要 Jun 动作的事**
（2026-10-05 原则）：

1. 首发复核：只看有已登记实票的期；票内场在开球前 45–75 分钟内才拉 API-Football 名单，否则
   立刻退出不打网。研究原件里按上下文分成「研究记缺阵」与「研究记在阵」两组人名，只在
   *研究记缺阵的人首发* 或 *研究记在阵的人坐替补* 时推一条（名单上根本找不到的名字不推——
   宁可漏报不误报）。票面该场全包（310）不推。一场一期只推一次。
2. 停售倒计时：停售前 30 / 10 分各一次，只在「有分析包、无实票」时推，带机器默认动作。
3. 位移 diff：读 prep-revision 已落盘的 `<期>-diff-afternoon-revision.md`，票内场位移 ≥3pp 才推
   一条汇总。

状态文件 `.nutmeg-data/zucai/<期>-lineup-watch.json` 记每场 pushed / no_impact / no_lineups 等
原因；`notify()` 自带的账本去重是第二道闸。开球与停售时间只认 `<期>-issue.json`。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from nutmeg.decision.betslip import BetSlip, load_slips
from nutmeg.decision.bj_time import BJ, aware, parse_bj

ZUCAI_CHANNELS = ("renjiu", "shengfucai")
LINEUP_WINDOW_MIN = (45, 75)        # 开球前多少分钟内拉名单
COUNTDOWN_MIN = (30, 10)            # 停售前几分钟各推一次
SHIFT_THRESHOLD_PP = 3.0            # 票内场位移 ≥ 这个值才推
FULL_COVER = "310"

FetchFixtures = Callable[[date], list[dict]]          # → [{fixture_id, home, away, kickoff}]
FetchLineups = Callable[[str], list[dict]]            # → [{team, xi:[...], bench:[...]}]
Notify = Callable[..., object]

_ABSENT_WORDS = ("缺", "伤", "停赛", "存疑", "骨折", "不在", "无法", "手术", "禁赛", "缺席",
                 "out", "injur", "suspend", "doubt")
_LATIN_NAME = re.compile(r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’\-]{2,}(?:\s[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’\-]{2,})?")
_CLAUSE_SPLIT = re.compile(r"[，。；、;,.()（）]")
_DIFF_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([+\-−]?[\d.]+)\s*\|\s*([+\-−]?[\d.]+)\s*\|"
                       r"\s*([+\-−]?[\d.]+)\s*\|")


# ---------------------------------------------------------------------------
# 期次与票面
# ---------------------------------------------------------------------------

def _zucai_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "zucai"


def issue_doc(data_dir: Path, issue: str) -> dict | None:
    path = _zucai_dir(data_dir) / f"{issue}-issue.json"
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def kickoffs(doc: dict) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for m in doc.get("matches") or []:
        dt = parse_bj(m.get("kickoff_bj"))
        if dt is not None:
            out[str(m.get("match_no"))] = dt
    return out


def match_names(doc: dict) -> dict[str, tuple[str, str, str]]:
    """{场号: (主, 客, 赛事)}。"""
    return {str(m.get("match_no")): (str(m.get("home_team") or ""), str(m.get("away_team") or ""),
                                     str(m.get("competition") or ""))
            for m in doc.get("matches") or []}


def active_issues(data_dir: Path, now: datetime) -> list[str]:
    """还有场次没踢完（最晚开球 + 3 小时 > now）且停售不早于 2 天前的期，按期号升序。"""
    out = []
    for path in sorted(_zucai_dir(data_dir).glob("*-issue.json")):
        issue = path.name.split("-")[0]
        doc = issue_doc(data_dir, issue)
        if not doc:
            continue
        kicks = list(kickoffs(doc).values())
        if not kicks:
            continue
        if max(kicks) + timedelta(hours=3) <= now:
            continue
        deadline = parse_bj(doc.get("sale_deadline"))
        if deadline is not None and deadline < now - timedelta(days=2):
            continue
        out.append(issue)
    return out


def real_slips(data_dir: Path, issue: str) -> list[BetSlip]:
    return [s for s in load_slips(data_dir, issue=issue)
            if s.purchased and s.channel in ZUCAI_CHANNELS]


def ticket_faces(slips: list[BetSlip]) -> dict[str, list[tuple[str, str]]]:
    """{场号: [(slip_id, 面)]}，全包（310）的格不算「票面押了这场」。"""
    out: dict[str, list[tuple[str, str]]] = {}
    for s in slips:
        for no, face in s.faces.items():
            if face and "".join(sorted(face)) != "013":
                out.setdefault(str(no), []).append((s.slip_id, face))
    return out


# ---------------------------------------------------------------------------
# 状态文件
# ---------------------------------------------------------------------------

def state_path(data_dir: Path, issue: str) -> Path:
    return _zucai_dir(data_dir) / f"{issue}-lineup-watch.json"


def load_state(data_dir: Path, issue: str) -> dict:
    try:
        return json.loads(state_path(data_dir, issue).read_text("utf-8"))
    except (OSError, ValueError):
        return {"lineup": {}, "countdown": {}, "shift": {}}


def save_state(data_dir: Path, issue: str, state: dict) -> None:
    path = state_path(data_dir, issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 研究原件 → 关键人
# ---------------------------------------------------------------------------

def research_doc(data_dir: Path, issue: str, match_no: str, kickoff: datetime) -> dict | None:
    """先找足彩独有 m 文件；没有就经 channel-map（store id → 场号）到当日/前一日竞彩板的研究件。"""
    data_dir = Path(data_dir)
    direct = _zucai_dir(data_dir) / f"{issue}-research-m{match_no}.json"
    if direct.exists():
        try:
            return json.loads(direct.read_text("utf-8"))
        except ValueError:
            return None
    from nutmeg.decision.zucai_identity import load_channel_map

    cmap = load_channel_map(_zucai_dir(data_dir), issue)
    match_id = next((mid for mid, no in cmap.items() if str(no) == str(match_no)), None)
    if not match_id:
        return None
    for day in (kickoff.date(), kickoff.date() - timedelta(days=1)):
        daily = data_dir / "jczq" / "daily" / day.isoformat()
        try:
            legs = json.loads((daily / "jczq-legs-base.json").read_text("utf-8")).get("legs") or {}
        except (OSError, ValueError):
            continue
        code = next((c for c, lg in legs.items() if (lg or {}).get("match_id") == match_id), None)
        if code and (daily / f"research-{code}.json").exists():
            try:
                return json.loads((daily / f"research-{code}.json").read_text("utf-8"))
            except ValueError:
                return None
    return None


def _texts(research: dict) -> list[str]:
    out = [str(research.get("summary") or "")]
    hole = research.get("hole_location") or {}
    if isinstance(hole, dict):
        out.append(str(hole.get("detail") or ""))
    sb = research.get("strength_balance") or {}
    if isinstance(sb, dict):
        out.append(json.dumps(sb, ensure_ascii=False))
    return out


def key_names(research: dict) -> tuple[set[str], set[str]]:
    """→ (研究记在阵, 研究记缺阵)。按子句上下文分组：子句含缺/伤/停赛等词 → 缺阵。"""
    present: set[str] = set()
    absent: set[str] = set()
    for text in _texts(research):
        for clause in _CLAUSE_SPLIT.split(text):
            names = {n.strip() for n in _LATIN_NAME.findall(clause)}
            if not names:
                continue
            low = clause.lower()
            (absent if any(w in low for w in _ABSENT_WORDS) else present).update(names)
    present -= absent
    return present, absent


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def _surname(name: str) -> str:
    return _norm(name).split()[-1]


def _in(name: str, players: list[str]) -> bool:
    sur = _surname(name)
    return any(sur == _surname(p) or sur in _norm(p).split() for p in players)


@dataclass
class LineupVerdict:
    status: str                            # pushed | no_impact | no_lineups | no_research | ...
    absent_but_starting: list[str] = field(default_factory=list)
    present_but_bench: list[str] = field(default_factory=list)
    text: str = ""


def compare(research: dict, lineups: list[dict]) -> LineupVerdict:
    present, absent = key_names(research)
    xi = [p for t in lineups for p in t.get("xi") or []]
    bench = [p for t in lineups for p in t.get("bench") or []]
    if not xi:
        return LineupVerdict("no_lineups")
    abs_start = sorted(n for n in absent if _in(n, xi))
    pres_bench = sorted(n for n in present if not _in(n, xi) and _in(n, bench))
    if not abs_start and not pres_bench:
        return LineupVerdict("no_impact")
    return LineupVerdict("affected", abs_start, pres_bench)


# ---------------------------------------------------------------------------
# API-Football（默认抓取器；测试注入假函数）
# ---------------------------------------------------------------------------

def default_fetchers() -> tuple[FetchFixtures, FetchLineups] | None:
    from nutmeg.config.settings import get_settings
    from nutmeg.data.api_football import ApiFootballClient

    settings = get_settings()
    key = (settings.api_football_key or "").strip()
    if not key:
        return None
    client = ApiFootballClient(base_url=settings.api_football_base_url, api_key=key)

    def fixtures(day: date) -> list[dict]:
        batch = client.fetch_fixtures_by_date(day, timezone="Asia/Shanghai")
        return [{"fixture_id": f.fixture_id, "home": f.home_team, "away": f.away_team,
                 "league": f.league_code, "kickoff": f.kickoff_at.astimezone(BJ)}
                for f in batch.fixtures]

    return fixtures, client.fetch_lineups


def _resolver():
    from nutmeg.decision.entities import load_team_alias_table, resolve_team
    table = load_team_alias_table()
    return lambda name: resolve_team(name, table)


def _league_resolver():
    from nutmeg.decision.entities import load_league_alias_table, resolve_league
    table = load_league_alias_table()
    return lambda name: resolve_league(name, table)


def find_fixture(fixtures: list[dict], home: str, away: str, kickoff: datetime,
                 competition: str = "", resolve=None, resolve_league=None) -> str | None:
    """同日板里找这场：两队都经别名表解析到同一实体才算；队名解析不了（法甲六队无实体，26145）
    就退到「同一联赛 + 开球时刻 ±10 分钟」唯一命中；再不行 → None（不猜）。"""
    resolve = resolve or _resolver()
    h, a = resolve(home), resolve(away)
    if h and a:
        for f in fixtures:
            if resolve(f["home"]) == h and resolve(f["away"]) == a:
                return str(f["fixture_id"])
    near = [f for f in fixtures
            if abs((aware(f["kickoff"]) - kickoff).total_seconds()) <= 600
            and (h is None or resolve(f["home"]) == h) and (a is None or resolve(f["away"]) == a)]
    if (h or a) and len(near) == 1:
        return str(near[0]["fixture_id"])
    if competition:
        resolve_league = resolve_league or _league_resolver()
        lg = resolve_league(competition)
        same = [f for f in near if lg and resolve_league(str(f.get("league") or "")) == lg]
        if len(same) == 1:
            return str(same[0]["fixture_id"])
    return None


# ---------------------------------------------------------------------------
# 三类播报
# ---------------------------------------------------------------------------

def _fp(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def run_lineup_check(data_dir: Path, issue: str, *, now: datetime, notify_fn: Notify,
                     fetchers: tuple[FetchFixtures, FetchLineups] | None,
                     resolve=None, resolve_league=None, dry_run: bool = False) -> list[dict]:
    doc = issue_doc(data_dir, issue)
    if not doc:
        return []
    slips = real_slips(data_dir, issue)
    faces = ticket_faces(slips)
    if not faces:
        return [{"issue": issue, "status": "no_real_ticket"}]
    kicks = kickoffs(doc)
    names = match_names(doc)
    lo, hi = LINEUP_WINDOW_MIN
    due = [no for no in faces
           if no in kicks and lo <= (kicks[no] - now).total_seconds() / 60 <= hi]
    if not due:
        return [{"issue": issue, "status": "no_match_in_window"}]
    state = load_state(data_dir, issue)
    done = state.setdefault("lineup", {})
    events: list[dict] = []
    board: dict[date, list[dict]] = {}
    for no in sorted(due, key=int):
        if done.get(no, {}).get("status") in ("pushed", "no_impact", "no_research"):
            continue
        ev: dict = {"issue": issue, "match_no": no}
        research = research_doc(data_dir, issue, no, kicks[no])
        if research is None:
            ev["status"] = "no_research"
        elif fetchers is None:
            ev["status"] = "no_api_key"
        else:
            fetch_fixtures, fetch_lineups = fetchers
            day = kicks[no].date()
            if day not in board:
                try:
                    board[day] = fetch_fixtures(day)
                except Exception as exc:  # noqa: BLE001 - 记原因，下轮再试
                    board[day] = []
                    ev["error"] = str(exc)[:160]
            home, away, comp = names.get(no, ("", "", ""))
            fid = find_fixture(board[day], home, away, kicks[no], comp, resolve, resolve_league)
            if not fid:
                ev["status"] = "team_unresolved"
            else:
                try:
                    verdict = compare(research, fetch_lineups(fid))
                except Exception as exc:  # noqa: BLE001
                    verdict = LineupVerdict("no_lineups")
                    ev["error"] = str(exc)[:160]
                ev["status"] = verdict.status
                if verdict.status == "affected":
                    parts = []
                    if verdict.absent_but_starting:
                        parts.append("研究记缺阵但首发：" + "、".join(verdict.absent_but_starting))
                    if verdict.present_but_bench:
                        parts.append("研究记在阵却替补：" + "、".join(verdict.present_but_bench))
                    tickets = "；".join(f"票 {sid} 该格 {face}" for sid, face in faces[no])
                    text = f"{issue}·{no} {home}-{away}｜" + "｜".join(parts) + f"｜{tickets}"
                    ev["text"] = text
                    notify_fn("zucai.lineup", f"{issue}:{no}", _fp(text), text, dry_run=dry_run)
                    ev["status"] = "pushed" if not dry_run else "dry_run"
        ev["at"] = now.isoformat(timespec="seconds")
        if not dry_run:
            done[no] = {k: v for k, v in ev.items() if k in ("status", "at", "error", "text")}
        events.append(ev)
    if not dry_run:
        save_state(data_dir, issue, state)
    return events


def default_action(data_dir: Path, issue: str) -> str:
    """分析包 §2 里第一处「机器默认…」短语；没有就空串。"""
    try:
        text = (_zucai_dir(data_dir) / f"{issue}-packet.md").read_text("utf-8")
    except OSError:
        return ""
    sec = text.split("## §2", 1)
    body = sec[1] if len(sec) == 2 else text
    m = re.search(r"机器默认[^*。；\n|]{0,30}", body)
    return m.group(0).strip() if m else ""


def run_countdown(data_dir: Path, issue: str, *, now: datetime, notify_fn: Notify,
                  dry_run: bool = False) -> list[dict]:
    doc = issue_doc(data_dir, issue)
    deadline = parse_bj((doc or {}).get("sale_deadline")) if doc else None
    if deadline is None:
        return []
    left = (deadline - now).total_seconds() / 60
    if left <= 0 or left > max(COUNTDOWN_MIN):
        return []
    if not (_zucai_dir(data_dir) / f"{issue}-packet.md").exists():
        return [{"issue": issue, "status": "no_packet"}]
    if real_slips(data_dir, issue):
        return [{"issue": issue, "status": "has_real_ticket"}]
    state = load_state(data_dir, issue)
    done = state.setdefault("countdown", {})
    mark = next((str(m) for m in sorted(COUNTDOWN_MIN) if left <= m), None)
    if mark is None or mark in done:
        return [{"issue": issue, "status": "already_pushed", "mark": mark}]
    action = default_action(data_dir, issue) or "（§2 未写机器默认）"
    text = (f"{issue} 停售前 {int(left)} 分（{deadline.strftime('%H:%M')}）：无登记票；"
            f"机器默认动作 {action}")
    notify_fn("zucai.countdown", f"{issue}:{mark}", _fp(text), text, dry_run=dry_run)
    if not dry_run:
        done[mark] = now.isoformat(timespec="seconds")
        save_state(data_dir, issue, state)
    return [{"issue": issue, "status": "pushed" if not dry_run else "dry_run", "mark": mark,
             "text": text}]


def parse_shift_table(md: str) -> list[dict]:
    rows = []
    for line in md.splitlines():
        m = _DIFF_ROW.match(line.strip())
        if not m:
            continue
        vals = [float(v.replace("−", "-")) for v in m.groups()[2:]]
        rows.append({"match_no": m.group(1), "name": m.group(2).strip(),
                     "d_home": vals[0], "d_draw": vals[1], "d_away": vals[2],
                     "max_abs": max(abs(v) for v in vals)})
    return rows


def run_shift_diff(data_dir: Path, issue: str, *, now: datetime, notify_fn: Notify,
                   dry_run: bool = False) -> list[dict]:
    path = _zucai_dir(data_dir) / f"{issue}-diff-afternoon-revision.md"
    if not path.exists():
        return []
    faces = ticket_faces(real_slips(data_dir, issue))
    if not faces:
        return [{"issue": issue, "status": "no_real_ticket"}]
    kicks = kickoffs(issue_doc(data_dir, issue) or {})
    hits = [r for r in parse_shift_table(path.read_text("utf-8"))
            if r["match_no"] in faces and r["max_abs"] >= SHIFT_THRESHOLD_PP
            and r["match_no"] in kicks and kicks[r["match_no"]] > now]   # 已开球的位移不可行动
    if not hits:
        return [{"issue": issue, "status": "no_shift_in_ticket"}]
    lines = [f"{r['match_no']} {r['name']} Δ主{r['d_home']:+.1f} 平{r['d_draw']:+.1f} "
             f"客{r['d_away']:+.1f}｜" + "；".join(f"{sid} {f}" for sid, f in faces[r["match_no"]])
             for r in hits]
    text = f"{issue} 18:30 位移≥{SHIFT_THRESHOLD_PP:g}pp 的票内场：\n" + "\n".join(lines)
    fp = _fp(text)
    state = load_state(data_dir, issue)
    done = state.setdefault("shift", {})
    if fp in done:
        return [{"issue": issue, "status": "already_pushed"}]
    notify_fn("zucai.shift", issue, fp, text, dry_run=dry_run)
    if not dry_run:
        done[fp] = now.isoformat(timespec="seconds")
        save_state(data_dir, issue, state)
    return [{"issue": issue, "status": "pushed" if not dry_run else "dry_run", "text": text}]


def watch(data_dir: Path, *, issue: str | None = None, now: datetime | None = None,
          notify_fn: Notify | None = None,
          fetchers: tuple[FetchFixtures, FetchLineups] | None = None,
          fetchers_factory: Callable[[], tuple | None] | None = None,
          resolve=None, dry_run: bool = False) -> dict:
    """一次巡检：倒计时 → 位移 diff → 首发复核。只在有票内场进窗口时才构造抓取器（不打网）。"""
    from nutmeg.notifications.notify import notify as _notify

    data_dir = Path(data_dir)
    now = now or datetime.now(BJ)
    notify_fn = notify_fn or _notify
    issues = [issue] if issue else active_issues(data_dir, now)
    report: dict = {"now": now.isoformat(timespec="seconds"), "issues": {}}
    for iss in issues:
        r: dict = {}
        r["countdown"] = run_countdown(data_dir, iss, now=now, notify_fn=notify_fn,
                                       dry_run=dry_run)
        r["shift"] = run_shift_diff(data_dir, iss, now=now, notify_fn=notify_fn,
                                    dry_run=dry_run)
        probe = run_lineup_check(data_dir, iss, now=now, notify_fn=notify_fn, fetchers=None,
                                 resolve=resolve, dry_run=True)
        needs_net = any(e.get("status") == "no_api_key" for e in probe)
        if needs_net and fetchers is None:
            fetchers = (fetchers_factory or default_fetchers)()
        r["lineup"] = (run_lineup_check(data_dir, iss, now=now, notify_fn=notify_fn,
                                        fetchers=fetchers, resolve=resolve, dry_run=dry_run)
                       if needs_net else probe)
        report["issues"][iss] = r
    return report
