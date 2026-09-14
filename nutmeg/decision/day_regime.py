"""day_regime — 日级盘面热度诊断(2026-07-07 用户定)。

确定性算术,从当日读时快照聚合"盘面气质"指标(热门强度/均势度/欧-体 gap/期望进球),
写 daily/<date>/day-regime.json **只攒样本**——不进任何决策路径(n<30 只攒不改模型,
反积累免疫)。若日后校准显示某 regime 指标与冷门率相关,再走 scoped 因子入词典。
"""
from __future__ import annotations

from nutmeg.decision.ontology import MarketSnapshot

# 与 anchor 同序:欧赔最 sharp。titan007 是 2026-09-14 起的主源,apifootball 保留
# 在列——历史快照全是它。
_SOURCE_PRIORITY = ("titan007", "apifootball", "fcom500", "sporttery")
_EURO_SOURCES = ("titan007", "apifootball", "fcom500")
_HEAVY_FAV = 0.65      # 重热门阈(fair 最大方向 ≥)
_TOSSUP = 0.45         # 均势阈(fair 最大方向 <)
_GAP_ALERT = 0.08      # 欧-体 gap 警戒(分量最大差 ≥,继承 §17 gap 口径)


def _latest_by_source(snaps: list) -> dict[str, MarketSnapshot]:
    by_source: dict[str, MarketSnapshot] = {}
    for s in snaps:
        prev = by_source.get(s.source)
        if prev is None or s.taken_at > prev.taken_at:
            by_source[s.source] = s
    return by_source


def compute_day_regime(store, *, run_date: str) -> dict:
    """当日读时快照 → 日级盘面热度指标 dict(纯读,无副作用)。"""
    prefix = f"M-{run_date}-"
    snaps_by_match: dict[str, list] = {}
    for s in store.load(MarketSnapshot):
        if (s.match_id.startswith(prefix) and s.kind == "read_time"
                and (s.fair or {}).get("had")):
            snaps_by_match.setdefault(s.match_id, []).append(s)

    matches: list[dict] = []
    for match_id, snaps in sorted(snaps_by_match.items()):
        by_source = _latest_by_source(snaps)
        anchor = next((by_source[src] for src in _SOURCE_PRIORITY
                       if src in by_source), None)
        if anchor is None:                        # 非常规源,仍取任意一个当锚
            anchor = next(iter(by_source.values()))
        had = anchor.fair["had"]
        fav_side = max(had, key=had.get)
        euro = next(
            (by_source[src] for src in _EURO_SOURCES if src in by_source), None
        )
        spot = by_source.get("sporttery")
        gap = None
        if (euro is not None and spot is not None
                and (euro.fair or {}).get("had") and (spot.fair or {}).get("had")):
            gap = max(abs(spot.fair["had"].get(k, 0.0) - euro.fair["had"].get(k, 0.0))
                      for k in ("home", "draw", "away"))
        expected_goals = None
        ttg = (spot.fair or {}).get("ttg") if spot is not None else None
        if ttg:
            expected_goals = sum(
                int(k.rsplit("_", 1)[1]) * p for k, p in ttg.items())
        matches.append({
            "match_id": match_id, "anchor_source": anchor.source,
            "fav_side": fav_side, "fav_prob": had[fav_side],
            "draw_prob": had.get("draw"), "gap": gap,
            "expected_goals": expected_goals,
        })

    fav_probs = [m["fav_prob"] for m in matches]
    draws = [m["draw_prob"] for m in matches if m["draw_prob"] is not None]
    gaps = [m["gap"] for m in matches if m["gap"] is not None]
    xgs = [m["expected_goals"] for m in matches if m["expected_goals"] is not None]
    return {
        "run_date": run_date,
        "n_matches": len(matches),
        "mean_fav_prob": (sum(fav_probs) / len(fav_probs)) if fav_probs else None,
        "max_fav_prob": max(fav_probs) if fav_probs else None,
        "n_heavy_fav": sum(1 for p in fav_probs if p >= _HEAVY_FAV),
        "n_tossup": sum(1 for p in fav_probs if p < _TOSSUP),
        "mean_draw_prob": (sum(draws) / len(draws)) if draws else None,
        "n_gap_alert": sum(1 for g in gaps if g >= _GAP_ALERT),
        "mean_expected_goals": (sum(xgs) / len(xgs)) if xgs else None,
        "matches": matches,
        "note": "日级盘面热度诊断:只攒样本,不进决策(n<30 只攒不改模型)",
    }
