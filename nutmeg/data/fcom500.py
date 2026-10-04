"""500.com market-odds collector.

A quota-free market-odds source for the JCZQ conflict engine. Fetches and
parses 500.com pages (static HTML, gb2312-encoded) into per-JCZQ-match
``Fixture`` + ``OddsSnapshot`` objects, keyed by the 竞彩 number (周日NNN).

Recon contract: ``docs/superpowers/notes/fcom500-page-structure.md``. The
conflict engine focuses on 胜平负 only — the ``OddsSnapshot`` it consumes
carries ONLY ``match_winner`` (欧赔, a clean 体彩-independent signal). The
``total_goals`` (进球指数) and ``handicap`` (亚盘) parsers remain in the module
(tested, harmless) but are deliberately NOT fed to the conflict engine:
``total_goals`` is 体彩-derived (circular vs the 体彩 line the engine compares
against) and ``handicap`` is a 2-way 亚盘 that does not key-match the model's
3-way buckets. ``correct_score`` is JS-rendered and not collected. See the
structure note §4 verdict.

**Graceful degradation is the contract.** Any page fetch/parse failure
degrades that match/market — it never crashes the daily flow.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_DEFAULT_TIMEOUT = 20.0

__all__ = [
    "Fcom500Client",
    "Fcom500JczqMatch",
    "MarketOdds",
    "parse_jczq_list",
]


# ---------------------------------------------------------------------------
# Task A2 — fetch + decode client
# ---------------------------------------------------------------------------


class Fcom500Client:
    """HTTP client for 500.com pages: UA, timeout, gb2312→UTF-8 decode.

    Results are cached in-memory per URL (a daily run hits each page once,
    mirroring ``MatchAligner``'s fixture cache). The ``transport`` argument is
    injectable so tests drive the parsers from recorded fixtures with no live
    network.
    """

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        self._cache: dict[str, str] = {}

    def get(self, url: str) -> str:
        """Fetch ``url`` and return UTF-8 text (gb2312 decoded). Cached per URL."""
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        response = self._client.get(url)
        response.raise_for_status()
        text = response.content.decode("gb2312", errors="ignore")
        self._cache[url] = text
        return text

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fcom500Client":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Task A3 — the 竞彩 match list
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Fcom500JczqMatch:
    """One match from ``trade.500.com/jczq/``.

    ``match_no`` is the 竞彩 number (周日NNN) — the join key the conflict engine
    aligns on. ``fid`` is 500.com's internal id, the key for the 欧赔/亚盘/进球
    analysis sub-pages.
    """

    match_no: str
    fid: str
    home_team: str
    away_team: str
    league: str
    league_short: str
    kickoff: str
    # 体彩备源扩展（spec 2026-06-11）：tr data 属性 + data-sp 官方价
    had_sp: dict[str, float] = field(default_factory=dict)
    hhad_sp: dict[str, float] = field(default_factory=dict)
    hhad_line: float = 0.0
    business_date: str = ""
    match_date: str = ""
    match_time: str = ""
    is_selling: bool = False


# Each match is a <tr ... data-matchid="N" data-matchnum="周日NNN" ...>.
_MATCH_BLOCK_SPLIT = re.compile(r"(?=<tr[^>]*data-matchid=)")
_RE_MATCH_NO = re.compile(r'data-matchnum="(周[日一二三四五六]\d{3})"')
_RE_FID = re.compile(r"ouzhi-(\d+)\.shtml")
_RE_TEAMS = re.compile(r'class="team-[lr]"[^>]*title="([^"]+)"')
_RE_LEAGUE = re.compile(
    r'liansai\.500\.com/zuqiu-\d+/"[^>]*title="([^"]+)"[^>]*>([^<]+)<'
)
_RE_KICKOFF = re.compile(r'td-endtime"[^>]*title="([^"]+)"')
_RE_SP = re.compile(
    r'data-type="(nspf|spf)"\s+data-value="(\d)"\s+data-sp="([\d.]+)"'
)
_SP_OUTCOME = {"3": "home", "1": "draw", "0": "away"}
_RE_RANGQIU = re.compile(r'data-rangqiu="(-?\d+(?:\.\d+)?)"')
_RE_PROCESSDATE = re.compile(r'data-processdate="(\d{4}-\d{2}-\d{2})"')
_RE_MATCHDATE = re.compile(r'data-matchdate="(\d{4}-\d{2}-\d{2})"')
_RE_MATCHTIME = re.compile(r'data-matchtime="(\d{2}:\d{2})"')
_RE_ISEND = re.compile(r'data-isend="(\d+)"')


def parse_jczq_list(html: str) -> list[Fcom500JczqMatch]:
    """Parse ``trade.500.com/jczq/`` into one record per match.

    Establishes the 竞彩号 ↔ ``fid`` join entirely from this single page — no
    extra fetch needed to pair them. Malformed rows are skipped (graceful
    degradation), not raised on.
    """

    matches: list[Fcom500JczqMatch] = []
    seen: set[str] = set()
    for block in _MATCH_BLOCK_SPLIT.split(html):
        match_no_m = _RE_MATCH_NO.search(block)
        fid_m = _RE_FID.search(block)
        if not match_no_m or not fid_m:
            continue
        match_no = match_no_m.group(1)
        if match_no in seen:
            continue
        teams = _RE_TEAMS.findall(block)
        if len(teams) < 2:
            logger.warning("fcom500: match %s missing team names — skipped", match_no)
            continue
        league_m = _RE_LEAGUE.search(block)
        kickoff_m = _RE_KICKOFF.search(block)
        had_sp: dict[str, float] = {}
        hhad_sp: dict[str, float] = {}
        for market, value_key, sp in _RE_SP.findall(block):
            outcome = _SP_OUTCOME.get(value_key)
            if outcome is None:
                continue
            (had_sp if market == "nspf" else hhad_sp)[outcome] = float(sp)
        rangqiu_m = _RE_RANGQIU.search(block)
        processdate_m = _RE_PROCESSDATE.search(block)
        matchdate_m = _RE_MATCHDATE.search(block)
        matchtime_m = _RE_MATCHTIME.search(block)
        isend_m = _RE_ISEND.search(block)
        seen.add(match_no)
        matches.append(
            Fcom500JczqMatch(
                match_no=match_no,
                fid=fid_m.group(1),
                home_team=teams[0],
                away_team=teams[1],
                league=league_m.group(1) if league_m else "",
                league_short=league_m.group(2) if league_m else "",
                kickoff=(kickoff_m.group(1) if kickoff_m else "").replace("截止", ""),
                had_sp=had_sp,
                hhad_sp=hhad_sp,
                hhad_line=float(rangqiu_m.group(1)) if rangqiu_m else 0.0,
                business_date=processdate_m.group(1) if processdate_m else "",
                match_date=matchdate_m.group(1) if matchdate_m else "",
                match_time=matchtime_m.group(1) if matchtime_m else "",
                is_selling=bool(isend_m and isend_m.group(1) == "0"),
            )
        )
    return matches


def sporttery_value_from_jczq_board(
    matches: list[Fcom500JczqMatch],
) -> dict:
    """500.com 竞彩列表 → sporttery ``getMatchCalculatorV1`` 同形 ``value`` dict。

    体彩备源（spec 2026-06-11）：sporttery webapi 被 WAF 拦截/降级时，由
    trade.500.com 的体彩 sp 价合成引擎可直接消费的 value——下游
    （``bold_matches_from_sporttery`` / ``_board_matches`` / 快照 / --replay）
    零感知。只有 had/hhad 两池（trade 列表页所带）；ttg/crs 缺省，引擎
    spec §11.1 原生支持缺池。停售/缺 businessDate/两池全缺的场被排除——
    绝不猜测。顶层 ``nutmegSource`` 标记数据来源，引擎忽略、复盘可见。
    """
    by_date: dict[str, list[dict]] = {}
    for m in matches:
        if not m.is_selling:
            continue
        if not (m.business_date and m.match_date):
            continue
        sub: dict[str, object] = {
            "matchStatus": "Selling",
            "matchNumStr": m.match_no,
            "businessDate": m.business_date,
            "homeTeamAbbName": m.home_team,
            "awayTeamAbbName": m.away_team,
            "leagueAbbName": m.league_short,
            "matchDate": m.match_date,
            "matchTime": m.match_time,
        }
        if len(m.had_sp) == 3:
            sub["had"] = {
                "h": m.had_sp["home"],
                "d": m.had_sp["draw"],
                "a": m.had_sp["away"],
            }
        if len(m.hhad_sp) == 3:
            sub["hhad"] = {
                "h": m.hhad_sp["home"],
                "d": m.hhad_sp["draw"],
                "a": m.hhad_sp["away"],
                # sporttery 原样格式：负带号、正不带号（"-1" / "1"）
                "goalLineValue": f"{m.hhad_line:g}",
            }
        if "had" not in sub and "hhad" not in sub:
            continue
        by_date.setdefault(m.business_date, []).append(sub)
    return {
        "nutmegSource": "fcom500-fallback",
        "matchInfoList": [
            {"businessDate": business_date, "subMatchList": subs}
            for business_date, subs in sorted(by_date.items())
        ],
    }


# ---------------------------------------------------------------------------
# Shared market value type + de-vig helper
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class MarketOdds:
    """A parsed market: per-outcome decimal odds + de-vigged fair probabilities.

    ``independent`` records the §4 verdict — ``True`` when the odds come from
    international bookmakers (a true conflict signal), ``False`` when they are
    体彩-derived (a flagged model-vs-体彩 weak signal). ``line`` carries the
    handicap / over-under line where applicable.
    """

    odds: dict[str, float]
    fair_probability: dict[str, float]
    independent: bool
    line: str | None = None
    bookmaker_count: int = 0
    opening_odds: dict[str, float] = field(default_factory=dict)
    per_book_odds: dict[str, list[float]] = field(default_factory=dict)


def _devig(odds: dict[str, float]) -> dict[str, float]:
    """Normalize 1/odds to sum 1 — the same fair-probability convention as
    ``OutcomeOddsSnapshot.fair_probability`` elsewhere in the codebase.

    The 6-dp rounding delta is absorbed into the largest bucket so the result
    sums to exactly 1.0 (mirrors ``dixon_coles._normalize_bucket_map``)."""
    inverse = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    total = sum(inverse.values())
    if total <= 0:
        return {}
    fair = {k: round(v / total, 6) for k, v in inverse.items()}
    delta = round(1.0 - sum(fair.values()), 6)
    if delta:
        strongest = max(fair, key=fair.get)
        fair[strongest] = round(fair[strongest] + delta, 6)
    return fair


# ---------------------------------------------------------------------------
# Task A4 — 欧赔 (international 1X2)
# ---------------------------------------------------------------------------

# A bookmaker row in the ouzhi/yazhi/daxiao datatb table.
_RE_DATATB = re.compile(r'id="datatb"')
# A bookmaker row opens with <tr class="tr1|tr2" ... id="N" ...>; its body runs
# to the next such opener (rows carry nested <table> so a naive </table> bound
# truncates them). The ``id`` attribute order varies across pages (欧赔 puts it
# right after class, 亚盘/大小 put it after xls="row") — the pattern tolerates
# intervening attributes. The split keeps each opener with its following body.
_RE_BOOK_ROW_SPLIT = re.compile(r'(?=<tr class="tr[12]"[^>]*\bid="\d+")')
_RE_BOOK_ROW_ID = re.compile(r'^<tr class="tr[12]"[^>]*\bid="(\d+)"')
_RE_PL_TABLE = re.compile(r'<table[^>]*class="pl_table_data".*?</table>', re.S)
_RE_ODDS_CELL = re.compile(r"<td[^>]*>\s*([\d.]+)\s*</td>")
# A <td> with its full attribute string + inner content. Used for the
# 亚盘/大小 tables whose odds cells carry trailing ↑↓ arrows and whose middle
# cell is the line (identified by a ``ref`` attribute).
_RE_TD = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
_RE_LEADING_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_RE_TAG = re.compile(r"<[^>]+>")
# 竞彩官方 row is id=1 — the 体彩 feed, excluded from independent signals.
_SPORTTERY_ROW_ID = "1"


# ---------------------------------------------------------------------------
# Task A5 — 让球 / 亚盘 (Asian handicap)
# ---------------------------------------------------------------------------

_RE_REF_ATTR = re.compile(r'\bref="(-?[\d.]+)"')


# ---------------------------------------------------------------------------
# Task A6 — 总进球 (进球指数) + 比分
# ---------------------------------------------------------------------------

# jqs page: <table class="pub_table"> with 0球..7+ columns; rows are tr1/tr2.
_RE_PUB_TABLE = re.compile(r'<table[^>]*class="pub_table".*?</table>', re.S)
_RE_JQS_ROW = re.compile(r'<tr class="tr[12]">(.*?)</tr>', re.S)
_RE_JQS_CELL = re.compile(r"<td>([\d.]+)</td>")
# Model total-goals buckets: total_0..total_6, total_7_plus (8 columns).
_TOTAL_GOALS_KEYS = (
    "total_0",
    "total_1",
    "total_2",
    "total_3",
    "total_4",
    "total_5",
    "total_6",
    "total_7_plus",
)


# ---------------------------------------------------------------------------
# Task A7 — Fcom500OddsProvider
# ---------------------------------------------------------------------------


_JCZQ_LIST_URL = "https://trade.500.com/jczq/"


# ---------------------------------------------------------------------------
# Task A8 — conflict-engine wiring
# ---------------------------------------------------------------------------


