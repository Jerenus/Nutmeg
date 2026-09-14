"""titan007 国际欧赔采集 → jczq-today 的 ``bold_odds`` 形状。

与 ``jczq_apifootball_odds.collect_bold_odds_apifootball`` **同签名同返回形状**::

    {match_no: {"match_winner": MarketOdds}}

因此对判断层是 drop-in——只换数据源槽位，不动任何选腿逻辑。

相对 API-Football 路径的三点结构性差异：

1. **零别名**。titan007 板面自带竞彩编号，对齐是查表不是匹配。``_utc_date`` /
   ``_resolve`` / ``_find_fixture`` / 两张别名 JSON 在本路径上全部不需要，
   「别名未命中 → 丢国际锚 prior 静默退化」这个失败模式随之消失。
2. **有初赔**。``MarketOdds.opening_odds`` 真正被填上，drift 信号不再恒为 0。
3. **必须筛书**。152 家里既有 Pinnacle/Crown 这样的锐盘，也有 ``Rodeoslot``
   这类噪声盘，更有 **竞彩官方（id 1129）——它就是体彩盘本身**。不排除它，
   「国际 vs 体彩」的冲突信号会变成体彩跟自己比。

本模块只出 ``match_winner``。大小球/亚盘住在另外两个 AES 加密的端点，属后续阶段；
在此之前由 ``merge_bold_odds`` 用 API-Football/500.com 兜底补 ``over_under``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from nutmeg.data.fcom500 import MarketOdds, _devig
from nutmeg.data.titan007 import Titan007BoardRow, Titan007BookQuote

logger = logging.getLogger(__name__)

__all__ = [
    "ALL_BOOKS",
    "SHARP_BOOKS",
    "BookSelection",
    "collect_bold_odds_titan007",
    "collect_bold_odds_titan007_live",
]

_OUTCOME_KEYS = ("home", "draw", "away")

# 竞彩官方 = 体彩盘本身（自指）；香港马会 = 彩池非庄家盘；Betfair = 交易所（佣金口径
# 不同）。三者一律不进「国际共识」，与口径无关。
_EXCLUDED_COMPANY_IDS = frozenset({"1129", "432", "2"})

# 锐盘白名单（公司 id 稳定，按 id 不按名字）。规模（~15 家）刻意贴近 API-Football
# 原本给到的书目量级，使切源时共识口径的变化尽量只来自「书更好」而非「书更多」。
_SHARP_COMPANY_IDS = frozenset(
    {
        "177",  # Pinnacle
        "545",  # Crown 皇冠
        "80",   # Macauslot 澳门
        "649",  # IBCBET
        "474",  # Sbobet
        "281",  # Bet 365
        "115",  # William Hill
        "82",   # Ladbrokes
        "81",   # Vcbet
        "90",   # Easybets
        "104",  # Interwetten
        "16",   # 10BET
        "18",   # 12bet
        "976",  # 18Bet
        "255",  # Bwin
    }
)

# 竞彩号每周复用（周一002 每周都有）。对齐时除竞彩号外再验开球时间，超出此容差
# 即判为对到了别的一期 → 丢场。体彩与 titan007 实测逐分钟一致，容差留给临时改期。
_KICKOFF_TOLERANCE = timedelta(minutes=30)

# 共识至少要这么多家才算数；不足视为该场无信号（宁可缺席不可用单家冒充共识）。
_MIN_CONSENSUS_BOOKS = 3


@dataclass(frozen=True, slots=True)
class BookSelection:
    """一种共识口径：名字 + 判定某家是否入选。"""

    name: str
    include_ids: frozenset[str] | None  # None = 除排除名单外全收

    def accepts(self, quote: Titan007BookQuote) -> bool:
        if quote.company_id in _EXCLUDED_COMPANY_IDS:
            return False
        if self.include_ids is None:
            return True
        return quote.company_id in self.include_ids


SHARP_BOOKS = BookSelection(name="sharp", include_ids=_SHARP_COMPANY_IDS)
ALL_BOOKS = BookSelection(name="all", include_ids=None)


def _avg(values: list[float]) -> float:
    """跨家均赔。沿用 ``jczq_apifootball_odds._avg`` 的 4 位小数口径——切源时聚合
    规则保持不变，使影子期看到的差异只来自书目集合本身。"""
    return round(sum(values) / len(values), 4)


def _board_matches(value: dict, run_date: str) -> list[tuple[str, datetime]]:
    """从 Sporttery 响应抽 (竞彩号, 北京开球时间)。无法解时间的场直接丢（不猜）。"""
    out: list[tuple[str, datetime]] = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(raw.get("businessDate") or day.get("businessDate") or "")
            if run_date and business_date and business_date != run_date:
                continue
            match_no = str(raw.get("matchNumStr") or "")
            kickoff_date = str(raw.get("matchDate") or business_date or "")
            kickoff_time = str(raw.get("matchTime") or "").strip()
            if not (match_no and kickoff_date and kickoff_time):
                continue
            try:
                kickoff = datetime.fromisoformat(f"{kickoff_date}T{kickoff_time}")
            except ValueError:
                continue
            out.append((match_no, kickoff))
    return out


def _consensus_market(
    quotes: Iterable[Titan007BookQuote], selection: BookSelection
) -> MarketOdds | None:
    """入选书目 → ``MarketOdds``（即时赔为主盘、初赔入 ``opening_odds``）。

    三路任一缺失、或入选不足 ``_MIN_CONSENSUS_BOOKS`` 家 → ``None``（该场无信号）。
    """
    chosen = [q for q in quotes if selection.accepts(q)]
    if len(chosen) < _MIN_CONSENSUS_BOOKS:
        return None

    per_book: dict[str, list[float]] = {k: [] for k in _OUTCOME_KEYS}
    opening_book: dict[str, list[float]] = {k: [] for k in _OUTCOME_KEYS}
    for quote in chosen:
        for key in _OUTCOME_KEYS:
            per_book[key].append(quote.current[key])
            opening_book[key].append(quote.opening[key])

    if not all(per_book[k] for k in _OUTCOME_KEYS):
        return None

    odds = {key: _avg(values) for key, values in per_book.items()}
    opening = {key: _avg(values) for key, values in opening_book.items()}
    return MarketOdds(
        odds=odds,
        fair_probability=_devig(odds),
        independent=True,
        bookmaker_count=len(chosen),
        opening_odds=opening,
        per_book_odds=per_book,
    )


def collect_bold_odds_titan007(
    value: dict,
    *,
    run_date: str,
    board_fetcher: Callable[[], Iterable[Titan007BoardRow]],
    odds_fetcher: Callable[[str], Iterable[Titan007BookQuote]],
    books: BookSelection = SHARP_BOOKS,
) -> dict[str, dict[str, MarketOdds]]:
    """采集体彩盘各场的 titan007 国际欧赔，键到体彩竞彩号。

    ``board_fetcher()`` 返回 titan007 当日板面（生产包 ``Titan007Client.fetch_board``）；
    ``odds_fetcher(match_id)`` 返回该场各家报价（包 ``fetch_euro_odds``）。两个
    fetcher 注入以便测试无网络。

    返回 ``{match_no: {"match_winner": MarketOdds}}``。板面抓取失败 → 返回空 dict
    （由 ``fetch_day`` 决定不落盘，保住上一版完好快照）；单场失败 → 仅该场缺席。
    **从不崩。**
    """
    board = _board_matches(value, run_date)
    if not board:
        return {}

    try:
        titan_rows = list(board_fetcher())
    except Exception:  # noqa: BLE001 — 降级，从不崩
        logger.warning("titan007-odds: 板面抓取失败，本轮无国际欧赔", exc_info=True)
        return {}

    by_no: dict[str, Titan007BoardRow] = {row.match_no: row for row in titan_rows}

    result: dict[str, dict[str, MarketOdds]] = {}
    for match_no, kickoff in board:
        row = by_no.get(match_no)
        if row is None:
            logger.info("titan007-odds skip %s: titan007 板面无此竞彩号", match_no)
            continue
        drift = abs(row.kickoff - kickoff)
        if drift > _KICKOFF_TOLERANCE:
            logger.warning(
                "titan007-odds skip %s: 开球时间不符（体彩 %s vs 007 %s）——疑似对到别期",
                match_no, kickoff, row.kickoff,
            )
            continue
        try:
            quotes = list(odds_fetcher(row.match_id))
        except Exception:  # noqa: BLE001 — 降级，从不崩
            logger.warning(
                "titan007-odds: 欧赔抓取失败 match_id=%s (%s)",
                row.match_id, match_no, exc_info=True,
            )
            continue
        market = _consensus_market(quotes, books)
        if market is None:
            logger.info(
                "titan007-odds skip %s: %s 口径下入选书目不足", match_no, books.name
            )
            continue
        logger.info(
            "titan007-odds %s → 007=%s (%s 家 %s 口径, drift=%s)",
            match_no, row.match_id, market.bookmaker_count, books.name,
            {k: round(market.odds[k] - market.opening_odds[k], 3) for k in _OUTCOME_KEYS},
        )
        result[match_no] = {"match_winner": market}
    return result


def collect_bold_odds_titan007_live(
    value: dict,
    *,
    run_date: str,
    books: BookSelection = SHARP_BOOKS,
) -> dict[str, dict[str, MarketOdds]]:
    """生产入口：装配真 ``Titan007Client`` 并采集。无 key、无配额。"""
    from nutmeg.data.titan007 import Titan007Client

    client = Titan007Client()
    try:
        return collect_bold_odds_titan007(
            value,
            run_date=run_date,
            board_fetcher=client.fetch_board,
            odds_fetcher=client.fetch_euro_odds,
            books=books,
        )
    finally:
        client.close()
