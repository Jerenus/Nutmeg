"""传统足彩的 titan007 国际欧赔 —— 场号对齐 + 共识 + 微结构。

竞彩那条链有**竞彩号**可查表（titan007 板面自带），对齐是零猜测的查表。足彩没有这
个键：500.com 在售页不带 titan007 id，titan007 也没有胜负彩板面（``sfc.``/``zc.``
子域实测 404）。

因此本模块用**开球时刻为主键、队名做消歧**：

1. 足彩场次的 ``kickoff_bj`` 与 titan007 板面行的开球时刻**完全相等**才是候选。
2. 同刻多场时，用 titan007 的三组队名变体（简/繁/别名）与足彩缩写做双向子串比对，
   主客任一命中即可定案。
3. **仍不唯一 → 丢场**，绝不猜。丢场只意味着该腿退回 500.com 单源，无回归风险。

为什么不能纯按队名：500.com 的足彩缩写与 titan007 的名字常无子串关系
（``吉国民`` vs ``吉达国民``、``国米`` vs ``国际米兰``），2026-09-14 实测纯队名只
对上 8/14，加开球时刻为主键后 10/14、0 多解——而未对上的 4 场本就不在竞彩板面上。

**只补充，不替换**：产出落到 ``<issue>-odds-intl.json``，与 500.com 基线
``<issue>-odds.json`` 并列。直接覆盖基线会静默改变足彩判读层的输入分布，那属判据
变更，须先有证据再由用户裁定——与竞彩换源走的是同一条规矩。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime

from nutmeg.data.titan007 import Titan007BoardRow, Titan007BookQuote

logger = logging.getLogger(__name__)

__all__ = [
    "align_zucai_to_titan007",
    "collect_zucai_euro_titan007",
    "collect_zucai_euro_titan007_live",
]


def _norm(value: str) -> str:
    return (value or "").strip()


def _name_hit(needle: str, names: Iterable[str]) -> bool:
    """足彩缩写与 titan007 某组名字变体是否指同一队（双向子串）。"""
    target = _norm(needle)
    if not target:
        return False
    for name in names or ():
        other = _norm(name)
        if not other:
            continue
        if target == other or target in other or other in target:
            return True
    return False


def align_zucai_to_titan007(
    matches: list[dict], board: list[Titan007BoardRow]
) -> dict[int, Titan007BoardRow]:
    """``{足彩场号: titan007 板面行}``。对不上的场次直接缺席。

    ``matches`` 是 ``<issue>-issue.json`` 的 ``matches``（需 ``match_no`` /
    ``home_team`` / ``away_team`` / ``kickoff_bj``）。
    """
    out: dict[int, Titan007BoardRow] = {}
    for match in matches or []:
        raw_kickoff = _norm(str(match.get("kickoff_bj") or ""))
        try:
            kickoff = datetime.fromisoformat(raw_kickoff)
        except ValueError:
            logger.info(
                "zucai-titan007 skip 场%s: 开球时刻不可解 %r（不默认、不猜）",
                match.get("match_no"), raw_kickoff,
            )
            continue

        candidates = [row for row in board if row.kickoff == kickoff]
        if len(candidates) > 1:
            candidates = [
                row for row in candidates
                if _name_hit(match.get("home_team"), row.home_names)
                or _name_hit(match.get("away_team"), row.away_names)
            ]
        if len(candidates) != 1:
            logger.info(
                "zucai-titan007 skip 场%s (%s vs %s @ %s): 候选 %d 个——非唯一即丢",
                match.get("match_no"), match.get("home_team"),
                match.get("away_team"), raw_kickoff, len(candidates),
            )
            continue
        out[int(match["match_no"])] = candidates[0]
    return out


def collect_zucai_euro_titan007(
    issue_doc: dict,
    *,
    board_fetcher: Callable[[], Iterable[Titan007BoardRow]],
    odds_fetcher: Callable[[str], Iterable[Titan007BookQuote]],
    books=None,
) -> dict[int, dict]:
    """``{足彩场号: {fair, odds, opening_odds, micro, books, 对齐来源}}``。

    板面抓取失败 → 返回空（调用方据此不落盘，不覆盖已有基线）；单场失败 → 仅该场
    缺席。**从不崩。**
    """
    from nutmeg.decision.microstructure import market_microstructure
    from nutmeg.services.jczq_titan007_odds import _consensus_market, sharp_books

    selection = books if books is not None else sharp_books()
    matches = (issue_doc or {}).get("matches") or []
    if not matches:
        return {}

    try:
        board = list(board_fetcher())
    except Exception:  # noqa: BLE001 — 降级，从不崩
        logger.warning("zucai-titan007: 板面抓取失败，本轮无国际欧赔", exc_info=True)
        return {}

    aligned = align_zucai_to_titan007(matches, board)
    out: dict[int, dict] = {}
    for match_no, row in aligned.items():
        try:
            quotes = list(odds_fetcher(row.match_id))
        except Exception:  # noqa: BLE001 — 降级，从不崩
            logger.warning(
                "zucai-titan007: 欧赔抓取失败 match_id=%s (场%s)",
                row.match_id, match_no, exc_info=True,
            )
            continue
        market = _consensus_market(quotes, selection)
        if market is None:
            logger.info("zucai-titan007 skip 场%s: 入选书目不足", match_no)
            continue
        out[match_no] = {
            "match_no": match_no,
            "fair": dict(market.fair_probability),
            "odds": dict(market.odds),
            "opening_odds": dict(market.opening_odds),
            "books": market.bookmaker_count,
            "micro": market_microstructure(market),
            "jczq_match_no": row.match_no,
            "titan007_match_id": row.match_id,
        }
    return out


def collect_zucai_euro_titan007_live(issue_doc: dict, *, books=None) -> dict[int, dict]:
    """生产入口：装配真 ``Titan007Client`` 并采集。无 key、无配额。"""
    from nutmeg.data.titan007 import Titan007Client

    client = Titan007Client()
    try:
        return collect_zucai_euro_titan007(
            issue_doc,
            board_fetcher=client.fetch_board,
            odds_fetcher=client.fetch_euro_odds,
            books=books,
        )
    finally:
        client.close()
