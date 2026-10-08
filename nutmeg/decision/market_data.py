"""market_data — 决策系统的确定性盘口数据层(唯一外部数据形状适配点)。

2026-07-07 A.1 基元物理迁入,spec 附录 A 兑现:去水/解析基元(OUTCOMES/_devig_map/
_fair_from_odds/_f/_signed_float/_had_from_pool/_ttg_from_pool/_crs_from_pool)与
盘口快照 I/O(fetch_sporttery_value_with_fallback/persist_*/load_*)从已删的
jczq_market_kernel 原样搬入本文件(函数体一字不动)。**结构性禁止**引入 A.3 信号打分符号。
去水 2026-10-08 起只有 `nutmeg.data.prices.devig` 一份，本模块再导出。
"""
from __future__ import annotations

import re

from nutmeg.data.prices import devig  # 唯一去水实现；本模块再导出，旧引用不断链

__all__ = [
    "OUTCOMES",
    "devig",
    "fetch_sporttery_value_with_fallback",
    "load_bold_odds_snapshot",
    "load_sporttery_snapshot",
    "persist_bold_odds_provenance",
    "persist_bold_odds_snapshot",
    "persist_sporttery_snapshot",
]

OUTCOMES: tuple[str, str, str] = ("home", "draw", "away")


_RE_CRS_KEY = re.compile(r"^s\d{2}s\d{2}$|^s1s[hda]$")


def _f(value: object) -> float | None:
    """Parse a Sporttery odds string to float; ``None`` when unusable.

    Odds are always positive, so a non-positive parse is treated as unusable.
    """
    result = _signed_float(value)
    return result if result is not None and result > 0 else None


def _signed_float(value: object) -> float | None:
    """Parse a Sporttery numeric string to float, keeping its sign.

    Unlike ``_f`` this accepts negatives — the 让球 ``goalLine`` is legitimately
    negative when the home side gives goals (e.g. ``"-1"``). ``None`` when the
    value cannot be parsed at all (an absent / non-numeric field).
    """
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _had_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery had/hhad pool ``{h,d,a}`` → ``{home,draw,away}`` odds."""
    out: dict[str, float] = {}
    for src, dst in (("h", "home"), ("d", "draw"), ("a", "away")):
        value = _f(pool.get(src))
        if value is not None:
            out[dst] = value
    return out


# ---------------------------------------------------------------------------
# 盘口快照 I/O(2026-07-07 从 jczq_market_kernel 原样迁入 — 决策本体
# decision-am/close 的抓取与回放底座)。
# ---------------------------------------------------------------------------

_EMPTY_RETRIES = 3
_EMPTY_RETRY_SECONDS = 20.0


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _diagnose_empty_calculator() -> str:
    """计算器空壳的原因：未开售 / 上游缓存抖动 / 真 WAF。只读赛程接口，不猜。

    赛程接口也拿不到时才沿用「degraded/WAF」——那才是真正看不见板面的情形。
    """
    import nutmeg.services.jczq as jczq_service

    try:
        listing = jczq_service.SportteryMatchListProvider().fetch()
    except jczq_service.JczqProviderError:
        return "Sporttery returned no matchInfoList (degraded/WAF response)"
    statuses = [
        str(sub.get("matchStatus") or "")
        for block in listing.get("matchInfoList") or []
        for sub in block.get("subMatchList") or []
    ]
    selling = statuses.count("Selling")
    # 两个数都报、不二选一：9/28 09:26 列表里还挂着一场前一业务日的 Selling 遗留，
    # 按「selling==0 才算未开售」会把真正的未开售误判成缓存抖动。
    return (f"Sporttery calculator empty (not a WAF block): match list "
            f"{selling} Selling / {len(statuses) - selling} not yet on sale")


def fetch_sporttery_value_with_fallback() -> tuple[dict, str]:
    """体彩盘面抓取：sporttery 主源 → trade.500.com 备源（spec 2026-06-11）。

    返回 ``(value, source)``；``source`` ∈ {"sporttery", "fcom500-fallback"}。
    回退触发两种情形：主源抛 ``JczqProviderError``（403/网络/errorCode≠0），或
    返回的 value 无非空 ``matchInfoList``（2026-06-11 WAF 降级空壳形态）。备源
    只有 had/hhad 两池。备源也失败/解析 0 场 → 原样抛出主源错误——绝不静默
    出假空盘。
    """
    import logging

    import nutmeg.services.jczq as jczq_service

    logger = logging.getLogger(__name__)
    primary_error: Exception | None = None
    # 空壳先短重试：开售后数分钟内五池计算器会间歇返回空（2026-09-28 11:01 开售后实测 0/1/1）。
    for attempt in range(1, _EMPTY_RETRIES + 1):
        try:
            fetched = jczq_service.SportteryJczqCalculatorProvider().fetch()
        except jczq_service.JczqProviderError as exc:
            primary_error = exc
            logger.warning("sporttery 主源失败（%s），尝试 500.com 备源", exc)
            break
        value = fetched.get("value") if "value" in fetched else fetched
        if value.get("matchInfoList"):
            return value, "sporttery"
        if attempt < _EMPTY_RETRIES:
            _sleep(_EMPTY_RETRY_SECONDS)
    if primary_error is None:
        primary_error = jczq_service.JczqProviderError(_diagnose_empty_calculator())
        logger.warning("sporttery 主源空壳：%s；尝试 500.com 备源", primary_error)

    try:
        import nutmeg.data.fcom500 as fcom500

        with fcom500.Fcom500Client() as client:
            html = client.get("https://trade.500.com/jczq/")
        board = fcom500.parse_jczq_list(html)
        value = fcom500.sporttery_value_from_jczq_board(board)
        if value.get("matchInfoList"):
            return value, "fcom500-fallback"
        logger.warning("500.com 备源解析 0 场在售比赛")
    except Exception:  # noqa: BLE001 — 备源失败不掩盖主源错误
        logger.warning("500.com 备源也失败", exc_info=True)
    raise primary_error


def persist_sporttery_snapshot(run_date: str, output_dir, value: dict) -> None:
    """Write the Sporttery response to ``<output_dir>/daily/<run_date>/
    sporttery_markets.json`` so ``--replay`` is reproducible.

    守卫（spec 2026-06-11）：新 ``value`` 无非空 ``matchInfoList`` 且磁盘已有
    含非空 ``matchInfoList`` 的快照 → 拒绝覆盖。修 2026-06-11 数据丢失 bug——
    WAF 降级空壳把当天 12:00 的完好 20 场快照冲掉（与 v2.2 修过的 ``--replay``
    覆盖派发文件 bug 同族）。
    """
    import json
    import logging
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    if not value.get("matchInfoList") and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
        if isinstance(existing, dict) and existing.get("matchInfoList"):
            logging.getLogger(__name__).warning(
                "sporttery snapshot guard: 拒绝用空盘响应覆盖 %s 的非空快照",
                run_date,
            )
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def persist_bold_odds_snapshot(run_date: str, output_dir, bold_odds: dict) -> None:
    """Write the ``collect_bold_odds`` result to ``<output_dir>/daily/<run_date>/
    bold_odds.json`` so ``--replay`` reproduces the 国际-odds-enriched engine
    (spec §14).

    Without this, ``--replay`` never re-fetches 国际 odds and degrades to
    体彩-only — the conflict / drift / dispersion signals collapse to 0 and the
    day chaos value falsely reads 0. ``bold_odds`` maps 竞彩号 →
    ``{market_name: MarketOdds}``; each ``MarketOdds`` is a plain fcom500
    dataclass (no predictive model) serialized via ``dataclasses.asdict``.
    """
    import dataclasses
    import json
    from pathlib import Path

    payload = {
        match_no: {
            market: dataclasses.asdict(odds) for market, odds in markets.items()
        }
        for match_no, markets in bold_odds.items()
    }
    path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def persist_bold_odds_provenance(run_date: str, output_dir, provenance: dict) -> None:
    """把 ``{竞彩号: 源名}`` 落到 ``bold_odds_source.json``,与 ``bold_odds.json`` 并列。

    独立一个文件而不是塞进 bold_odds.json——后者的形状是
    ``dataclasses.asdict(MarketOdds)``,``load_bold_odds_snapshot`` 按此形状回读,
    混进非 MarketOdds 的键会破坏 replay 的字节兼容。
    """
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "bold_odds_source.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(provenance, ensure_ascii=False), encoding="utf-8")


def load_sporttery_snapshot(run_date: str, output_dir) -> dict | None:
    """Read a persisted Sporttery snapshot; ``None`` when absent."""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_bold_odds_snapshot(run_date: str, output_dir) -> dict:
    """Read a persisted 国际-odds snapshot back into the ``bold_odds`` shape
    ``bold_matches_from_sporttery`` expects — ``{竞彩号: {market: MarketOdds}}``.

    Absent snapshot → ``{}`` — pre-§14 dates (and any day the live 国际 fetch
    failed) degrade to 体彩-only exactly as before, never a crash. Rebuilds real
    ``MarketOdds`` objects (a plain fcom500 dataclass — imports NO predictive
    model).
    """
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    if not path.exists():
        return {}
    from nutmeg.data.fcom500 import MarketOdds

    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        match_no: {
            market: MarketOdds(**fields) for market, fields in markets.items()
        }
        for match_no, markets in raw.items()
    }
