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
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

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


def _in_order(short: str, long: str) -> bool:
    """``吉国民`` ⊂ ``吉达国民``：短名每个字按序出现在长名里（足彩缩写的常见形）。"""
    it = iter(long)
    return all(ch in it for ch in short)


_YOUTH = re.compile(r"U\d{2}|女|后备|青年|预备")


def _hit_strength(needle: str, names: Iterable[str]) -> int:
    """2=强（双向子串 / ≥3 字按序），1=弱（2 字按序），0=不中。"""
    if _name_hit(needle, names):
        return 2
    target = _norm(needle)
    best = 0
    for name in names or ():
        other = _norm(name)
        short, long = sorted((target, other), key=len)
        if len(short) >= 2 and _in_order(short, long):
            best = max(best, 2 if len(short) >= 3 else 1)
    return best


def _schedule_candidates(match: dict, rows: list[Titan007BoardRow]) -> list[Titan007BoardRow]:
    """赛程页行（整天全部赛事，无竞彩号）的认场规则。

    - 青年/女足行先剔除（除非足彩名本身就是）——同刻的「意大利U21」不许顶包「意大利」。
    - 任一边强命中即入围；两边都只弱命中也入围（``萨堡``→``萨普斯堡`` 这种两字缩写
      单独太松）。译名常只差一边：赫塔费/赫塔菲、托林斯/杜连斯。
    - 多个入围 → 只留两边都中的；仍不唯一由调用方丢场。
    """
    home, away = match.get("home_team") or "", match.get("away_team") or ""
    youth_ok = bool(_YOUTH.search(home + away))
    scored = []
    for row in rows:
        if not youth_ok and any(_YOUTH.search(n) for n in row.home_names + row.away_names):
            continue
        h, a = _hit_strength(home, row.home_names), _hit_strength(away, row.away_names)
        if h == 2 or a == 2 or (h and a):
            scored.append((row, bool(h and a)))
    if len(scored) > 1:
        scored = [pair for pair in scored if pair[1]]
    return [row for row, _both in scored]


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
        # ⛔队名校验对**任意候选数**都必须执行。曾经只在 len>1 时校验,导致
        # 2026-09-15 实测 26124 场13「阿罗卡-圣克拉」(当日不在竞彩板面)被同为
        # 01:00 开球的「本菲卡-吉维森特」静默顶包——26111 身份错配同类死法。
        board_rows = [
            row for row in candidates
            if row.match_no and (
                _name_hit(match.get("home_team"), row.home_names)
                or _name_hit(match.get("away_team"), row.away_names)
            )
        ]
        # 竞彩板行（有竞彩号）优先；只有板上没有时才看整日赛程页。
        candidates = board_rows or _schedule_candidates(
            match, [row for row in candidates if not row.match_no]
        )
        if len(candidates) != 1:
            logger.info(
                "zucai-titan007 skip 场%s (%s vs %s @ %s): 候选 %d 个——非唯一即丢",
                match.get("match_no"), match.get("home_team"),
                match.get("away_team"), raw_kickoff, len(candidates),
            )
            continue
        out[int(match["match_no"])] = candidates[0]
    return out


def _schedule_rows(
    matches: list[dict],
    fetcher: Callable[[str], Iterable[Titan007BoardRow]],
    *,
    known: set[str],
) -> list[Titan007BoardRow]:
    """足彩各场开球日 + 前一天的整日赛程页（凌晨场挂在前一天页上），按 id 去重。

    竞彩板上已有的 id 不再加：同一场两行会让对齐判成多解而丢场。
    """
    days: set[str] = set()
    for match in matches:
        try:
            kickoff = datetime.fromisoformat(_norm(str(match.get("kickoff_bj") or "")))
        except ValueError:
            continue
        days.add(kickoff.date().isoformat())
        days.add((kickoff.date() - timedelta(days=1)).isoformat())
    out: list[Titan007BoardRow] = []
    seen = set(known)
    for day in sorted(days):
        try:
            rows = list(fetcher(day))
        except Exception:  # noqa: BLE001 — 单日失败只少这一天
            logger.warning("zucai-titan007: 赛程页 %s 抓取失败", day, exc_info=True)
            continue
        for row in rows:
            if row.match_id not in seen:
                seen.add(row.match_id)
                out.append(row)
    return out


def collect_zucai_euro_titan007(
    issue_doc: dict,
    *,
    board_fetcher: Callable[[], Iterable[Titan007BoardRow]],
    odds_fetcher: Callable[[str], Iterable[Titan007BookQuote]],
    books=None,
    schedule_fetcher: Callable[[str], Iterable[Titan007BoardRow]] | None = None,
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
        logger.warning("zucai-titan007: 竞彩板面抓取失败", exc_info=True)
        board = []
    if schedule_fetcher is not None:
        board.extend(_schedule_rows(matches, schedule_fetcher,
                                    known={row.match_id for row in board}))
    if not board:
        logger.warning("zucai-titan007: 板面与赛程页都拿不到，本轮无国际欧赔")
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
            "jczq_match_no": row.match_no or None,
            "titan007_match_id": row.match_id,
            "align_source": "jc_board" if row.match_no else "schedule",
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
            schedule_fetcher=client.fetch_schedule,
        )
    finally:
        client.close()
