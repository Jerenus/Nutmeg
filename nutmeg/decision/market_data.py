"""market_data — 决策系统的确定性盘口数据层(唯一外部数据形状适配点)。

2026-07-07 A.1 基元物理迁入,spec 附录 A 兑现:去水/解析基元(OUTCOMES/_devig_map/
_fair_from_odds/_f/_signed_float/_had_from_pool/_ttg_from_pool/_crs_from_pool)与
盘口快照 I/O(fetch_sporttery_value_with_fallback/persist_*/load_*)从已删的
jczq_market_kernel 原样搬入本文件(函数体一字不动)。**结构性禁止**引入 A.3 信号打分符号。
"""
from __future__ import annotations

import re

from nutmeg.decision.identity import canonical_match_id

__all__ = [
    "OUTCOMES",
    "devig",
    "euro_snapshot_from_bold_odds",
    "fair_1x2",
    "fetch_sporttery_value_with_fallback",
    "load_bold_odds_snapshot",
    "load_sporttery_snapshot",
    "persist_bold_odds_snapshot",
    "persist_sporttery_snapshot",
    "snapshots_from_sporttery",
]

OUTCOMES: tuple[str, str, str] = ("home", "draw", "away")


_RE_CRS_KEY = re.compile(r"^s\d{2}s\d{2}$|^s1s[hda]$")


def _devig_map(odds: dict[str, float]) -> dict[str, float]:
    """De-vig an arbitrary-keyed odds map to fair probabilities summing to ~1.

    Generalizes ``_fair_from_odds`` (which is hard-coded to ``OUTCOMES``) to the
    总进球 / 让球 keyspaces. Empty / unusable input → empty dict.
    """
    inverse = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in inverse.items()}


def _fair_from_odds(odds: dict[str, float]) -> dict[str, float]:
    """De-vig decimal odds to fair probabilities summing to ~1.

    Returns an empty dict when ``odds`` is empty/unusable — callers treat that
    as "signal unavailable" (graceful degradation)."""
    inverse = {
        o: 1.0 / odds[o]
        for o in OUTCOMES
        if odds.get(o) and odds[o] > 0
    }
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {o: v / total for o, v in inverse.items()}


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


def _ttg_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery ttg pool ``{s0..s7}`` → ``{total_0..total_7}`` odds."""
    out: dict[str, float] = {}
    for k in range(8):
        value = _f(pool.get(f"s{k}"))
        if value is not None:
            out[f"total_{k}"] = value
    return out


def _crs_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery crs pool → ``{raw_key: odds}`` — the ``...f`` flag keys and any
    metadata keys (``goalLine`` …) are excluded; only ``sHHsAA`` / ``s1sX``."""
    out: dict[str, float] = {}
    for key, raw in pool.items():
        if not (_RE_CRS_KEY.match(key)):
            continue
        value = _f(raw)
        if value is not None:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# 盘口快照 I/O(2026-07-07 从 jczq_market_kernel 原样迁入 — 决策本体
# decision-am/close 的抓取与回放底座)。
# ---------------------------------------------------------------------------

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
    primary_error: Exception
    try:
        fetched = jczq_service.SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        if value.get("matchInfoList"):
            return value, "sporttery"
        primary_error = jczq_service.JczqProviderError(
            "Sporttery returned no matchInfoList (degraded/WAF response)"
        )
        logger.warning("sporttery 主源返回空壳（无 matchInfoList），尝试 500.com 备源")
    except jczq_service.JczqProviderError as exc:
        primary_error = exc
        logger.warning("sporttery 主源失败（%s），尝试 500.com 备源", exc)

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


def devig(odds: dict[str, float]) -> dict[str, float]:
    """任意键赔率 → 去水 fair 概率(和≈1)。空/不可用 → 空 dict。"""
    return _devig_map(odds)


def fair_1x2(had_odds: dict[str, float]) -> dict[str, float]:
    """胜平负三路赔率 → 去水 fair(home/draw/away)。"""
    return _fair_from_odds(had_odds)


def _snapshot_id(match_no: str, taken_at: str, kind: str, source: str) -> str:
    """确定性 id:同场同时刻同 kind 同 source 只产一条(store 幂等靠它)。

    source 入 id 是必需的:同一场同一时刻的体彩(sporttery)与欧赔(apifootball)
    读时快照 kind 都是 read_time,不带 source 会撞 id 互相覆盖。
    """
    return f"S-{kind}-{source}-{match_no}-{taken_at}"


def snapshots_from_sporttery(
    value: dict, *, run_date: str, taken_at: str, source: str, kind: str,
) -> list:
    """sporttery getMatchCalculatorV1 的 value → MarketSnapshot 列表(净化版)。

    附录 A.2:同 bold_matches_from_sporttery 的解析逻辑,但产 MarketSnapshot、
    fair 逐市场去水、**不产 tags/信号字段**、不调 _strong_favorite_tags。
    只保留在售且 businessDate==run_date 的场;每市场有可用赔率才写 fair。
    """
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(
                raw.get("businessDate") or day.get("businessDate") or ""
            )
            if run_date and business_date and business_date != run_date:
                continue
            match_no = str(raw.get("matchNumStr") or "")
            home = str(raw.get("homeTeamAbbName") or "")
            away = str(raw.get("awayTeamAbbName") or "")
            hhad_pool = raw.get("hhad") or {}
            had_odds = _had_from_pool(raw.get("had") or {})
            hhad_odds = _had_from_pool(hhad_pool)
            ttg_odds = _ttg_from_pool(raw.get("ttg") or {})
            crs_odds = _crs_from_pool(raw.get("crs") or {})
            if not (len(had_odds) >= 3 or len(hhad_odds) >= 3 or ttg_odds or crs_odds):
                continue
            raw_odds: dict[str, dict[str, float]] = {}
            fair: dict[str, dict[str, float]] = {}
            if len(had_odds) >= 3:
                raw_odds["had"] = had_odds
                fair["had"] = fair_1x2(had_odds)
            if len(hhad_odds) >= 3:
                raw_odds["hhad"] = hhad_odds
                fair["hhad"] = fair_1x2(hhad_odds)
            if ttg_odds:
                raw_odds["ttg"] = ttg_odds
                fair["ttg"] = devig(ttg_odds)
            if crs_odds:
                raw_odds["crs"] = crs_odds
                fair["crs"] = devig(crs_odds)
            hhad_line = (
                _signed_float(hhad_pool.get("goalLineValue"))
                or _signed_float(hhad_pool.get("goalLine")) or 0.0
            )
            snaps.append(MarketSnapshot(
                snapshot_id=_snapshot_id(match_no, taken_at, kind, source),
                match_id=canonical_match_id(home, away, run_date),
                taken_at=taken_at, kind=kind, source=source,
                fair=fair, raw_odds=raw_odds,
                lines={"hhad_line": hhad_line},
            ))
    return snaps


def euro_snapshot_from_bold_odds(
    bold_odds: dict, *, run_date: str, taken_at: str, kind: str, source: str,
) -> list:
    """欧赔 bold_odds（{竞彩号: {market: MarketOdds}}）→ MarketSnapshot 列表。

    只取 match_winner 的去水 fair_probability（欧赔已去水，是最 sharp 三路估计），
    作为 had 市场的 fair。空 fair 的场跳过。不产 tags/信号字段（净化不变）。
    收盘快照(kind=closing)与读时锚(kind=read_time)共用本构造器。
    """
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for match_no, markets in bold_odds.items():
        mw = markets.get("match_winner")
        fair = dict(getattr(mw, "fair_probability", {}) or {}) if mw else {}
        if not fair or abs(sum(fair.values())) < 1e-9:
            continue
        snaps.append(MarketSnapshot(
            snapshot_id=_snapshot_id(match_no, taken_at, kind, source),
            match_id=f"M-{run_date}-{match_no}",
            taken_at=taken_at, kind=kind, source=source,
            fair={"had": fair}, raw_odds={},
            lines={},
        ))
    return snaps
