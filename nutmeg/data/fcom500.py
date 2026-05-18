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
from datetime import UTC, datetime

import httpx

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.odds import (
    BookmakerQuote,
    MarketOddsSnapshot,
    OddsProviderSnapshot,
    OddsSnapshot,
    OutcomeOddsSnapshot,
)

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_DEFAULT_TIMEOUT = 20.0

__all__ = [
    "Fcom500Client",
    "Fcom500JczqMatch",
    "Fcom500OddsProvider",
    "Fcom500OddsService",
    "Fcom500ValueBridge",
    "MarketOdds",
    "build_model_identity",
    "collect_bold_odds",
    "parse_correct_score",
    "parse_european_1x2",
    "parse_handicap",
    "parse_jczq_list",
    "parse_over_under",
    "parse_total_goals",
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


# Each match is a <tr ... data-matchid="N" data-matchnum="周日NNN" ...>.
_MATCH_BLOCK_SPLIT = re.compile(r"(?=<tr[^>]*data-matchid=)")
_RE_MATCH_NO = re.compile(r'data-matchnum="(周[日一二三四五六]\d{3})"')
_RE_FID = re.compile(r"ouzhi-(\d+)\.shtml")
_RE_TEAMS = re.compile(r'class="team-[lr]"[^>]*title="([^"]+)"')
_RE_LEAGUE = re.compile(
    r'liansai\.500\.com/zuqiu-\d+/"[^>]*title="([^"]+)"[^>]*>([^<]+)<'
)
_RE_KICKOFF = re.compile(r'td-endtime"[^>]*title="([^"]+)"')


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
            )
        )
    return matches


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


def _leading_number(text: str) -> float | None:
    """Parse the leading decimal of a cell, tolerating trailing ↑↓ arrows /
    markup (e.g. ``0.950↓`` → ``0.95``)."""
    stripped = _RE_TAG.sub("", text).strip()
    m = _RE_LEADING_NUMBER.match(stripped)
    return float(m.group(0)) if m else None


def _book_rows(html: str) -> list[tuple[str, str]]:
    """Return (row_id, row_html) for each bookmaker row in the datatb table."""
    start = _RE_DATATB.search(html)
    if not start:
        return []
    rows: list[tuple[str, str]] = []
    for block in _RE_BOOK_ROW_SPLIT.split(html[start.start():]):
        id_m = _RE_BOOK_ROW_ID.match(block)
        if id_m:
            rows.append((id_m.group(1), block))
    return rows


def parse_european_1x2(html: str) -> MarketOdds | None:
    """Parse the 欧赔 page into average international 1X2 odds + fair probs.

    Excludes the 竞彩官方 (体彩) row — the average is over international
    bookmakers only, so the result is a true 体彩-independent conflict signal.
    Returns ``None`` when no international row can be parsed.
    """

    home: list[float] = []
    draw: list[float] = []
    away: list[float] = []
    open_home: list[float] = []
    open_draw: list[float] = []
    open_away: list[float] = []
    for row_id, body in _book_rows(html):
        if row_id == _SPORTTERY_ROW_ID:
            continue
        first_table = _RE_PL_TABLE.search(body)
        if not first_table:
            continue
        cells = _RE_ODDS_CELL.findall(first_table.group(0))
        # Two <tr>: opening (first 3) + live (last 3). Use the live odds.
        if len(cells) < 6:
            continue
        opening = [float(c) for c in cells[0:3]]
        live = [float(c) for c in cells[3:6]]
        if any(o <= 1.0 for o in live) or any(o <= 1.0 for o in opening):
            continue
        home.append(live[0])
        draw.append(live[1])
        away.append(live[2])
        open_home.append(opening[0])
        open_draw.append(opening[1])
        open_away.append(opening[2])

    if not home:
        return None
    odds = {
        "home": round(sum(home) / len(home), 4),
        "draw": round(sum(draw) / len(draw), 4),
        "away": round(sum(away) / len(away), 4),
    }
    opening_odds = {
        "home": round(sum(open_home) / len(open_home), 4),
        "draw": round(sum(open_draw) / len(open_draw), 4),
        "away": round(sum(open_away) / len(open_away), 4),
    }
    return MarketOdds(
        odds=odds,
        fair_probability=_devig(odds),
        independent=True,
        bookmaker_count=len(home),
        opening_odds=opening_odds,
        per_book_odds={"home": home, "draw": draw, "away": away},
    )


# ---------------------------------------------------------------------------
# Task A5 — 让球 / 亚盘 (Asian handicap)
# ---------------------------------------------------------------------------

_RE_REF_ATTR = re.compile(r'\bref="(-?[\d.]+)"')


def _parse_line_table(table_html: str) -> tuple[float, float, float, str] | None:
    """Parse a 亚盘/大小 inner table: ``[up_odds, <ref line>, down_odds]``.

    Returns ``(up, down, line_value, line_text)`` or ``None`` when the cells
    cannot be read. The middle cell is the line — identified by its ``ref``
    attribute — the outer two are the odds (which carry ↑↓ arrows).
    """

    tds = _RE_TD.findall(table_html)
    up: float | None = None
    down: float | None = None
    line_value: float | None = None
    line_text = ""
    for attrs, content in tds:
        ref = _RE_REF_ATTR.search(attrs)
        if ref is not None:
            line_value = float(ref.group(1))
            line_text = _RE_TAG.sub("", content).strip()
            continue
        number = _leading_number(content)
        if number is None:
            continue
        if up is None:
            up = number
        elif down is None:
            down = number
    if up is None or down is None or line_value is None:
        return None
    return up, down, line_value, line_text


def parse_handicap(html: str) -> MarketOdds | None:
    """Parse the 亚盘 page into average international Asian-handicap odds.

    Asian handicap is a 2-way market (``handicap_home`` covers /
    ``handicap_away`` covers). ``line`` is the median signed handicap line in
    goals (the ``ref`` attribute). The odds are international — independent of
    体彩 — but this 2-way shape does NOT key-match the model's 3-way
    integer-line handicap buckets (see structure note §3).
    """

    up: list[float] = []
    down: list[float] = []
    lines: list[float] = []
    line_text: str | None = None
    for row_id, body in _book_rows(html):
        if row_id == _SPORTTERY_ROW_ID:
            continue
        first_table = _RE_PL_TABLE.search(body)
        if not first_table:
            continue
        parsed = _parse_line_table(first_table.group(0))
        if parsed is None:
            continue
        up_odds, down_odds, line_value, text = parsed
        if up_odds <= 0 or down_odds <= 0:
            continue
        up.append(up_odds)
        down.append(down_odds)
        lines.append(line_value)
        if line_text is None and text:
            line_text = text

    if not up:
        return None
    odds = {
        "handicap_home": round(sum(up) / len(up), 4),
        "handicap_away": round(sum(down) / len(down), 4),
    }
    lines.sort()
    median_line = lines[len(lines) // 2]
    line_label = f"{median_line:+g}"
    if line_text:
        line_label = f"{line_label} ({line_text})"
    return MarketOdds(
        odds=odds,
        fair_probability=_devig(odds),
        independent=True,
        line=line_label,
        bookmaker_count=len(up),
    )


def parse_over_under(html: str) -> MarketOdds | None:
    """Parse the 大小球 (daxiao) page into average international over/under odds.

    Same datatb shape as 亚盘: each international bookmaker row's first
    ``pl_table_data`` is ``[over_odds, <td ref>line</td>, under_odds]``. Excludes
    the 竞彩官方 (体彩) row — the result is a true 体彩-independent signal.
    ``line`` is the median over/under line (magnitude — the ``ref`` is signed).
    ``per_book_odds`` carries each book's over/under for the dispersion signal.
    Returns ``None`` when no international row parses.
    """
    over: list[float] = []
    under: list[float] = []
    lines: list[float] = []
    for row_id, body in _book_rows(html):
        if row_id == _SPORTTERY_ROW_ID:
            continue
        first_table = _RE_PL_TABLE.search(body)
        if not first_table:
            continue
        parsed = _parse_line_table(first_table.group(0))
        if parsed is None:
            continue
        over_odds, under_odds, line_value, _text = parsed
        if over_odds <= 0 or under_odds <= 0:
            continue
        over.append(over_odds)
        under.append(under_odds)
        lines.append(abs(line_value))

    if not over:
        return None
    odds = {
        "over": round(sum(over) / len(over), 4),
        "under": round(sum(under) / len(under), 4),
    }
    lines.sort()
    median_line = lines[len(lines) // 2]
    return MarketOdds(
        odds=odds,
        fair_probability=_devig(odds),
        independent=True,
        line=f"{median_line:g}",
        bookmaker_count=len(over),
        per_book_odds={"over": over, "under": under},
    )


def _safe_parse_page(client: Fcom500Client, url: str, parser) -> MarketOdds | None:
    """Fetch + parse one analysis page, degrading to ``None`` on any error."""
    try:
        html = client.get(url)
    except Exception:  # noqa: BLE001 — a missing page degrades that market
        logger.warning("fcom500: fetch failed for %s — market degraded", url)
        return None
    try:
        return parser(html)
    except Exception:  # noqa: BLE001 — a parse failure degrades that market
        logger.warning("fcom500: parse failed for %s — market degraded", url)
        return None


def collect_bold_odds(client: Fcom500Client) -> dict[str, dict[str, MarketOdds]]:
    """Collect the bold engine's 国际 odds as raw ``MarketOdds`` per match.

    Returns ``{match_no: {"match_winner": MarketOdds, "over_under": MarketOdds}}``.
    Unlike ``Fcom500OddsProvider`` (which maps to domain ``MarketOddsSnapshot``
    and drops opening/per-book odds), this keeps the raw ``MarketOdds`` so the
    bold engine's drift + dispersion signals have their inputs. Any page
    fetch/parse failure degrades that match/market — never crashes.
    """
    try:
        list_html = client.get(_JCZQ_LIST_URL)
    except Exception:  # noqa: BLE001 — degrade, never crash
        logger.warning("fcom500: 竞彩 list fetch failed — no bold odds", exc_info=True)
        return {}
    result: dict[str, dict[str, MarketOdds]] = {}
    for match in parse_jczq_list(list_html):
        entry: dict[str, MarketOdds] = {}
        euro = _safe_parse_page(client, _ouzhi_url(match.fid), parse_european_1x2)
        if euro is not None:
            entry["match_winner"] = euro
        over_under = _safe_parse_page(client, _daxiao_url(match.fid), parse_over_under)
        if over_under is not None:
            entry["over_under"] = over_under
        if entry:
            result[match.match_no] = entry
    return result


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


def parse_total_goals(html: str) -> MarketOdds | None:
    """Parse the 进球指数 (jqs) page into exact goal-count odds + fair probs.

    Per the §4 verdict the 进球指数 page exposes only 体彩-derived rows
    (``竞彩**`` / ``足球**``) — no international bookmaker odds for the
    exact-count market. The parser still returns the odds, tagged
    ``independent=False`` so the conflict engine flags it a model-vs-体彩 weak
    signal. The first table row is used; returns ``None`` when absent.
    """

    pub = _RE_PUB_TABLE.search(html)
    if not pub:
        return None
    for body in _RE_JQS_ROW.findall(pub.group(0)):
        cells = _RE_JQS_CELL.findall(body)
        if len(cells) < len(_TOTAL_GOALS_KEYS):
            continue
        odds = {
            key: float(cells[idx])
            for idx, key in enumerate(_TOTAL_GOALS_KEYS)
            if float(cells[idx]) > 1.0
        }
        if not odds:
            continue
        return MarketOdds(
            odds=odds,
            fair_probability=_devig(odds),
            independent=False,
            bookmaker_count=1,
        )
    return None


def parse_correct_score(html: str) -> MarketOdds | None:
    """Parse the 比分 page — correct-score odds.

    Per the §4 verdict the 比分指数 page's odds are loaded client-side via
    JavaScript: the static ``pub_table`` contains only the score-column header
    row, no odds. There is nothing to parse from a recorded static page, so
    this always returns ``None``. Kept as a named entry point so the provider
    composes uniformly and a future JS-aware fetch can fill it in.
    """

    return None


# ---------------------------------------------------------------------------
# Task A7 — Fcom500OddsProvider
# ---------------------------------------------------------------------------


def _ouzhi_url(fid: str) -> str:
    return f"https://odds.500.com/fenxi/ouzhi-{fid}.shtml"


def _daxiao_url(fid: str) -> str:
    return f"https://odds.500.com/fenxi/daxiao-{fid}.shtml"


_JCZQ_LIST_URL = "https://trade.500.com/jczq/"


def _market_snapshot(
    *,
    market_key: str,
    market_name: str,
    parsed: MarketOdds,
    source: str,
) -> MarketOddsSnapshot:
    """Map a parsed ``MarketOdds`` onto a domain ``MarketOddsSnapshot``.

    Outcome keys are the exact vocabulary the conflict engine expects
    (``home``/``draw``/``away``, ``total_N``/``total_7_plus``,
    ``handicap_home``/``handicap_away``) — see ``nutmeg/services/value.py``
    ``_market_probabilities`` and ``nutmeg/models/dixon_coles.py``.
    """

    outcomes: list[OutcomeOddsSnapshot] = []
    for outcome_key, decimal_odds in parsed.odds.items():
        fair_p = parsed.fair_probability.get(outcome_key)
        outcomes.append(
            OutcomeOddsSnapshot(
                outcome_key=outcome_key,
                outcome_name=outcome_key,
                bookmaker_quotes=[
                    BookmakerQuote(
                        bookmaker_id=0,
                        bookmaker_name=(
                            "500.com international avg"
                            if parsed.independent
                            else "500.com 体彩-derived"
                        ),
                        market_id=0,
                        market_name=market_name,
                        selection_value=outcome_key,
                        decimal_odds=decimal_odds,
                        source=source,
                    )
                ],
                best_odds=decimal_odds,
                average_odds=decimal_odds,
                fair_probability=fair_p,
                fair_odds=(round(1.0 / fair_p, 4) if fair_p else None),
                bookmaker_count=parsed.bookmaker_count,
            )
        )
    return MarketOddsSnapshot(
        market_key=market_key,
        market_name=market_name,
        status="available",
        line=parsed.line,
        source_market_ids=[],
        outcomes=outcomes,
    )


def _parse_kickoff(kickoff: str, run_date: str) -> datetime:
    """Best-effort parse of the '05-17 14:00' cutoff into a UTC datetime."""
    year = int(run_date.split("-")[0])
    text = kickoff.strip()
    try:
        parsed = datetime.strptime(f"{year}-{text}", "%Y-%m-%d %H:%M")
        return parsed.replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC).replace(microsecond=0)


def _model_season_for(run_date: str) -> int:
    """Map a JCZQ run date to the API-Football / soccerdata season year.

    European-league seasons span two calendar years; the catalog labels a
    season by its starting year. A fixture from July onward belongs to the
    season starting that year; a January–June fixture to the one that started
    the previous year. Mirrors ``jczq_value_wiring.season_for_date`` — kept
    inline so the data layer carries no services-layer import.
    """
    year, month, _day = (int(part) for part in run_date.split("-"))
    return year if month >= 7 else year - 1


def build_model_identity(match, run_date: str) -> Fixture | None:
    """Build a JCZQ match's **model-side** ``Fixture`` — English team names + a
    catalog league code — keyed by the 竞彩-synthetic ``fcom500:周日NNN`` id.

    The 500.com collector's synthetic ``Fixture`` carries **Chinese** team
    names and a Chinese league string; the model side
    (``FixtureSnapshotService`` → soccerdata, ``get_league()``) needs English
    team names and a catalog league code. This builds that identity the way
    ``MatchAligner`` does:

    - Chinese team names → English via ``load_team_aliases()`` keyed by the
      JCZQ league.
    - JCZQ league → ``load_league_aliases()`` → API-Football id →
      ``league_code_by_api_football_id()`` → catalog code.

    The ``fixture_id`` stays ``fcom500:周日NNN`` so ``Fcom500OddsService`` still
    keys the odds snapshot correctly.

    **Honest degradation:** a match whose league or either team is not in the
    alias tables → ``None`` (no model identity), never a crash. 500.com-path
    model coverage therefore equals alias-table coverage — expected and
    correct.
    """
    # Deferred imports keep the data layer free of a load-time dependency on
    # the services layer (and avoid an import cycle).
    from nutmeg.config.catalog import league_code_by_api_football_id
    from nutmeg.services.jczq_match_align import (
        load_league_aliases,
        load_team_aliases,
    )

    league = getattr(match, "league", "")
    api_football_id = load_league_aliases().get(league)
    if api_football_id is None:
        logger.info(
            "fcom500: match %s league '%s' not in jczq_league_aliases — "
            "no model identity",
            getattr(match, "match_no", "?"),
            league,
        )
        return None
    league_code = league_code_by_api_football_id().get(api_football_id)
    if league_code is None:
        logger.info(
            "fcom500: match %s league '%s' (api id %s) has no catalog code — "
            "no model identity",
            getattr(match, "match_no", "?"),
            league,
            api_football_id,
        )
        return None

    team_table = load_team_aliases().get(league, {})
    home_en = _lookup_team_alias(team_table, getattr(match, "home_team", ""))
    away_en = _lookup_team_alias(team_table, getattr(match, "away_team", ""))
    missing = [
        zh
        for zh, en in (
            (getattr(match, "home_team", ""), home_en),
            (getattr(match, "away_team", ""), away_en),
        )
        if en is None
    ]
    if missing:
        logger.info(
            "fcom500: match %s teams %s not in jczq_team_aliases['%s'] — "
            "no model identity",
            getattr(match, "match_no", "?"),
            missing,
            league,
        )
        return None

    assert home_en is not None and away_en is not None
    return Fixture(
        fixture_id=f"fcom500:{match.match_no}",
        league_code=league_code,
        provider_league_id=api_football_id,
        season=_model_season_for(run_date),
        kickoff_at=_parse_kickoff(getattr(match, "match_time", ""), run_date),
        home_team_id=None,
        away_team_id=None,
        home_team=home_en,
        away_team=away_en,
        source="fcom500",
        status=FixtureStatus.SCHEDULED,
    )


def _lookup_team_alias(team_table: dict[str, str], chinese_name: str) -> str | None:
    """Resolve a Chinese team name to its English alias, tolerating the
    whitespace variants 体彩 team names sometimes carry. Mirrors
    ``MatchAligner._lookup_team``."""
    if chinese_name in team_table:
        return team_table[chinese_name]
    normalized = "".join((chinese_name or "").split()).casefold()
    for zh, en in team_table.items():
        if "".join(zh.split()).casefold() == normalized:
            return en
    return None


@dataclass(slots=True)
class Fcom500MatchOdds:
    """A JCZQ match's synthetic fixture + assembled odds snapshot."""

    match_no: str
    fixture: Fixture
    odds: OddsSnapshot
    market_count: int
    notes: list[str] = field(default_factory=list)


class Fcom500OddsProvider:
    """Assembles per-JCZQ-match ``Fixture`` + ``OddsSnapshot`` from 500.com.

    ``collect(run_date)`` fetches the 竞彩 list, then per match fetches the
    analysis sub-pages and assembles a synthetic ``Fixture``
    (id ``fcom500:周日NNN``) + an ``OddsSnapshot`` covering the markets that
    are cleanly available. Any page fetch/parse failure degrades that
    match/market — never crashes (graceful degradation is the contract).
    """

    def __init__(self, *, client: Fcom500Client) -> None:
        self._client = client

    def collect(self, run_date: str) -> dict[str, Fcom500MatchOdds]:
        """Return ``{match_no: Fcom500MatchOdds}`` for every parseable match."""
        try:
            list_html = self._client.get(_JCZQ_LIST_URL)
        except Exception:  # noqa: BLE001 — degrade, never crash
            logger.warning("fcom500: 竞彩 list fetch failed — no odds", exc_info=True)
            return {}
        matches = parse_jczq_list(list_html)
        result: dict[str, Fcom500MatchOdds] = {}
        for match in matches:
            collected = self._collect_match(match, run_date)
            if collected is not None:
                result[match.match_no] = collected
        return result

    def _collect_match(
        self, match: Fcom500JczqMatch, run_date: str
    ) -> Fcom500MatchOdds | None:
        # 胜平负聚焦：the conflict engine focuses on match_winner only. The
        # OddsSnapshot fed to it carries ONLY the 欧赔-sourced match_winner
        # market — total_goals (体彩-derived, independent=False — circular vs the
        # 体彩 line the engine compares against) and handicap (2-way 亚盘, does
        # not key-match the model's 3-way buckets) are deliberately dropped.
        # Their parsers stay in the module (tested, harmless) but never feed
        # the conflict engine.
        markets: dict[str, MarketOddsSnapshot] = {}
        notes: list[str] = []

        # match_winner — the mandatory anchor (true independent signal).
        european = self._safe_parse(_ouzhi_url(match.fid), parse_european_1x2)
        if european is not None:
            markets["match_winner"] = _market_snapshot(
                market_key="match_winner",
                market_name="胜平负 (欧赔)",
                parsed=european,
                source="fcom500:ouzhi",
            )
        else:
            notes.append("欧赔缺失：无 match_winner 市场")

        fixture = Fixture(
            fixture_id=f"fcom500:{match.match_no}",
            league_code=match.league_short or "jczq",
            provider_league_id=0,
            season=int(run_date.split("-")[0]),
            kickoff_at=_parse_kickoff(match.kickoff, run_date),
            home_team_id=None,
            away_team_id=None,
            home_team=match.home_team,
            away_team=match.away_team,
            source="fcom500",
            status=FixtureStatus.SCHEDULED,
        )
        odds = OddsSnapshot(
            fixture=fixture,
            provider=OddsProviderSnapshot(
                name="fcom500",
                updated_at=datetime.now(UTC).replace(microsecond=0),
                bookmaker_count=max(
                    (m.outcomes[0].bookmaker_count for m in markets.values() if m.outcomes),
                    default=0,
                ),
            ),
            markets=markets,
            deferred_sections=[],
        )
        return Fcom500MatchOdds(
            match_no=match.match_no,
            fixture=fixture,
            odds=odds,
            market_count=len(markets),
            notes=notes,
        )

    def _safe_parse(self, url: str, parser) -> MarketOdds | None:
        """Fetch + parse one analysis page, degrading to ``None`` on any error."""
        try:
            html = self._client.get(url)
        except Exception:  # noqa: BLE001 — a missing page degrades that market
            logger.warning("fcom500: fetch failed for %s — market degraded", url)
            return None
        try:
            return parser(html)
        except Exception:  # noqa: BLE001 — a parse failure degrades that market
            logger.warning("fcom500: parse failed for %s — market degraded", url)
            return None


# ---------------------------------------------------------------------------
# Task A8 — conflict-engine wiring
# ---------------------------------------------------------------------------


class Fcom500OddsService:
    """An ``OddsService``-shaped view over collected 500.com snapshots.

    ``ValueBoardService`` resolves a fixture's market odds through
    ``odds_service.build_snapshot(fixture_id)``. This serves the per-match
    ``OddsSnapshot`` assembled by ``Fcom500OddsProvider`` — keyed by the
    synthetic ``fcom500:周日NNN`` fixture id — so the conflict engine consumes
    500.com odds with no code change.
    """

    def __init__(self, collected: dict[str, "Fcom500MatchOdds"]) -> None:
        self._by_fixture_id: dict[str, OddsSnapshot] = {
            entry.fixture.fixture_id: entry.odds for entry in collected.values()
        }

    def build_snapshot(
        self, fixture_id: str, *, persist_history: bool = True
    ) -> OddsSnapshot:
        snapshot = self._by_fixture_id.get(fixture_id)
        if snapshot is None:
            raise ValueError(f"no 500.com odds for fixture {fixture_id}")
        return snapshot


class Fcom500ValueBridge:
    """The 500.com-backed conflict-engine bridge.

    A drop-in for ``JczqValueBridge`` (same ``evaluate_day`` →
    ``JczqValueReport`` contract) that sources market odds from 500.com keyed
    by the 竞彩 number — **no ``MatchAligner``, no alias table, no
    API-Football call**. The model side still calls a ``SnapshotService``
    (soccerdata, quota-free); only the odds source is swapped.

    Graceful degradation is the contract: a JCZQ match absent from the
    500.com collection is honestly marked unaligned, never papered over.
    """

    def __init__(
        self,
        *,
        provider: Fcom500OddsProvider,
        run_date: str,
        value_service_factory,
        min_edge: float = 0.03,
    ) -> None:
        self._provider = provider
        self._run_date = run_date
        self._value_service_factory = value_service_factory
        self._min_edge = min_edge

    def evaluate_day(self, matches):
        """Collect 500.com odds, price every covered JCZQ match, group the
        conflicts by 竞彩 number into a ``JczqValueReport``.

        The 竞彩 number joins the JCZQ match to its 500.com odds. The **model
        side** needs a separate identity — English team names + a catalog
        league code — built by ``build_model_identity`` (Chinese→English via
        the alias tables). The model-identity fixture keeps the
        ``fcom500:周日NNN`` id, so ``Fcom500OddsService`` still resolves the
        500.com odds for it. A match with 500.com odds but no model identity
        (its league/teams are not in the alias tables) is honestly marked
        aligned-but-no-conflict — never crashed on.
        """

        # Deferred imports keep the data layer free of a load-time dependency
        # on the services layer (and avoid an import cycle).
        from nutmeg.services.jczq_value_bridge import (
            JczqMatchConflicts,
            JczqValueReport,
        )

        collected = self._provider.collect(self._run_date)
        value_service = self._value_service_factory()
        # Swap in the 500.com odds source: the conflict engine resolves a
        # fixture's market odds through odds_service.build_snapshot(fixture_id).
        value_service._odds_service = Fcom500OddsService(collected)  # noqa: SLF001

        # Build each covered JCZQ match's model-side identity. Only fixtures
        # with a resolvable English-name identity reach the pricing engine —
        # the rest degrade honestly (model coverage = alias-table coverage).
        model_fixtures: dict[str, Fixture] = {}
        for match in matches:
            if match.match_no not in collected:
                continue
            identity = build_model_identity(match, self._run_date)
            if identity is not None:
                model_fixtures[match.match_no] = identity

        conflicts_by_fixture: dict[str, list] = {}
        if model_fixtures:
            board = value_service.build_board_for_fixtures(
                list(model_fixtures.values()),
                min_edge=self._min_edge,
                league="jczq-fcom500",
            )
            for candidate in board.candidates:
                conflicts_by_fixture.setdefault(
                    candidate.fixture_id, []
                ).append(candidate)
            for group in conflicts_by_fixture.values():
                group.sort(key=lambda c: (-c.edge, -c.quarter_kelly_fraction))

        entries: list[JczqMatchConflicts] = []
        for match in matches:
            entry = collected.get(match.match_no)
            if entry is None:
                entries.append(
                    JczqMatchConflicts(
                        match_no=match.match_no,
                        league=match.league,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        aligned=False,
                        coverage_note=(
                            "无 500.com 数据：该竞彩编号不在当天 500.com 列表中"
                        ),
                    )
                )
                continue
            fixture_id = entry.fixture.fixture_id
            if match.match_no not in model_fixtures:
                # 500.com odds present, but no model-side identity — the
                # league or a team is absent from the alias tables.
                entries.append(
                    JczqMatchConflicts(
                        match_no=match.match_no,
                        league=match.league,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        aligned=True,
                        fixture_id=fixture_id,
                        orientation_swapped=False,
                        conflicts=[],
                        coverage_note=(
                            "已对齐 500.com 赔率，但模型侧无身份"
                            "（联赛/球队未收录于别名表）— 无冲突点"
                        ),
                    )
                )
                continue
            conflicts = conflicts_by_fixture.get(fixture_id, [])
            coverage_note = None
            if not conflicts:
                coverage_note = (
                    "已对齐 500.com，但无 +edge 冲突点"
                    "（赔率市场缺失或模型无优势）"
                )
            entries.append(
                JczqMatchConflicts(
                    match_no=match.match_no,
                    league=match.league,
                    home_team=match.home_team,
                    away_team=match.away_team,
                    aligned=True,
                    fixture_id=fixture_id,
                    orientation_swapped=False,
                    conflicts=conflicts,
                    coverage_note=coverage_note,
                )
            )
        return JczqValueReport(matches=entries)
