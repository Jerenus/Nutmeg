"""世界杯 2026 专题层 — spec docs/superpowers/specs/2026-06-11-jczq-worldcup-2026-design.md。

门控原则(spec §9):窗口外本包对管线零影响,7/19 后自动退役。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

WC_WINDOW_START = date(2026, 6, 11)
WC_WINDOW_END = date(2026, 7, 19)


def is_wc_active(run_date: str) -> bool:
    """世界杯窗口门控 — 解析失败一律 False(绝不让坏日期把世界杯层拉起来)。"""
    try:
        d = date.fromisoformat(run_date)
    except (TypeError, ValueError):
        return False
    return WC_WINDOW_START <= d <= WC_WINDOW_END


@dataclass(slots=True)
class WorldcupLayerOutput:
    section_md: str
    extra_questions: list = field(default_factory=list)


def run_worldcup_layer(
    *, run_date: str, matches: list, output_dir: Path, replay: bool,
    fixtures_fetcher=None, injuries_fetcher=None,
) -> WorldcupLayerOutput | None:
    """世界杯层总入口(spec §1)。窗口外或赛制文件缺失 → None(零影响)。

    live:摄取昨日赛果→更新 Elo→校准入账→模拟→落盘→渲染 §E。
    replay:只读已落盘 sim,绝不发网络请求(§26.4 纪律)。
    任何子步骤失败都降级:记日志、§E 缺席,决策包照常出。
    """
    if not is_wc_active(run_date):
        return None
    try:
        from .tournament import load_tournament

        tournament = load_tournament()
    except Exception:  # noqa: BLE001 — 静态文件缺失=专题层未启用
        logger.warning("worldcup: 赛制文件加载失败,§E 缺席", exc_info=True)
        return None

    from .packet_section import render_wc_section, wc_judgment_questions
    from .sim import load_sim

    wc_dir = output_dir / "wc2026"
    sim_today = None
    if not replay:
        try:
            sim_today = _live_update_and_simulate(
                run_date=run_date, matches=matches, tournament=tournament,
                wc_dir=wc_dir, fixtures_fetcher=fixtures_fetcher,
                injuries_fetcher=injuries_fetcher,
            )
        except Exception:  # noqa: BLE001
            logger.warning("worldcup: live 更新/模拟失败,尝试读盘", exc_info=True)
    if sim_today is None:
        sim_today = load_sim(wc_dir / f"sim-{run_date}.json")
    if sim_today is None:
        return None

    from datetime import timedelta

    prev = (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()
    sim_yesterday = load_sim(wc_dir / f"sim-{prev}.json")
    from .calibration import calibration_alert, load_entries

    note = calibration_alert(load_entries(wc_dir / "calibration-log.jsonl"))
    section = render_wc_section(
        tournament, sim_today=sim_today, sim_yesterday=sim_yesterday,
        todays_matches=_todays_rows(tournament, matches, sim_today),
        calibration_note=note,
    )
    questions = wc_judgment_questions(matches, tournament, run_date=run_date)
    return WorldcupLayerOutput(section_md=section, extra_questions=questions)


def _live_update_and_simulate(
    *, run_date, matches, tournament, wc_dir: Path,
    fixtures_fetcher, injuries_fetcher,
):
    """昨日赛果 → Elo/校准 → 今日模拟落盘。fetcher 为 None 时从 settings 装配。"""
    from datetime import timedelta

    from .calibration import CalibrationEntry, append_entries, brier
    from .ratings import (
        expected_lambdas,
        load_ratings,
        load_seed,
        save_ratings,
        update_after_match,
    )
    from .results import ingest_results, load_results, save_results
    from .sim import save_sim, simulate_tournament

    owned_client = None
    if fixtures_fetcher is None:
        from nutmeg.config.settings import get_settings
        from nutmeg.data.api_football import ApiFootballClient

        settings = get_settings()
        if not settings.api_football_key:
            raise RuntimeError("API_FOOTBALL key 缺失")
        owned_client = ApiFootballClient(
            base_url=settings.api_football_base_url,
            api_key=settings.api_football_key,
        )
        fixtures_fetcher = lambda d: owned_client.fetch_fixtures_by_date(d).fixtures  # noqa: E731

    results_path = wc_dir / "results.json"
    existing = load_results(results_path)
    fixtures = []
    today = date.fromisoformat(run_date)
    try:
        for back in (2, 1):  # 北京时差:UTC 昨天+前天覆盖"昨夜今晨"
            fixtures.extend(fixtures_fetcher(today - timedelta(days=back)))
    finally:
        if owned_client is not None:
            owned_client.close()
    merged = ingest_results(fixtures, tournament, existing=existing)
    new_results = merged[len(existing):]

    ratings = load_ratings(wc_dir / "ratings.json") or load_seed()
    cal_entries = []
    for r in new_results:
        if r.home not in ratings or r.away not in ratings:
            continue
        host = bool(tournament.teams.get(r.home, None) and tournament.teams[r.home].host)
        lam_h, lam_a = expected_lambdas(ratings[r.home], ratings[r.away],
                                        host_advantage=host)
        gh = r.goals_h_90 if r.goals_h_90 is not None else 1
        ga = r.goals_a_90 if r.goals_a_90 is not None else 1
        if r.status == "FT":
            ratings[r.home], ratings[r.away] = update_after_match(
                ratings[r.home], ratings[r.away],
                goals_h=gh, goals_a=ga, host_advantage=host,
            )
        # 只有 FT 场次 90 分钟进球可知,才能进 λ 残差校准;AET/PEN 只更新不入账。
        if r.status == "FT":
            model_p = _wdl_from_lambdas(lam_h, lam_a)
            cal_entries.append(CalibrationEntry(
                date=run_date, match_id=r.match_id, model_p=model_p, market_p=None,
                outcome=r.outcome_90, brier_model=brier(model_p, r.outcome_90),
                brier_market=None, lambda_pred_total=lam_h + lam_a,
                goals_actual=(gh + ga),
            ))
    if new_results:
        save_results(results_path, merged)
        save_ratings(wc_dir / "ratings.json", ratings, run_date=run_date)
    if cal_entries:
        append_entries(wc_dir / "calibration-log.jsonl", cal_entries)

    anchors = _anchors_from_matches(tournament, matches)
    injuries = _injury_counts(matches, tournament, injuries_fetcher)
    if injuries:
        from .ratings import injury_adjusted

        ratings = {
            t: injury_adjusted(r, n_out=injuries.get(t, 0)) for t, r in ratings.items()
        }
    sim = simulate_tournament(tournament, merged, ratings, anchors,
                              run_date=run_date)
    save_sim(wc_dir / f"sim-{run_date}.json", sim)
    return sim


def _wdl_from_lambdas(lam_h: float, lam_a: float) -> dict[str, float]:
    """双 Poisson 0..10 截断求和 → 胜平负概率(确定性,非采样)。"""
    import math

    def pmf(lam, k):
        return math.exp(-lam) * lam**k / math.factorial(k)

    p = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for i in range(11):
        for j in range(11):
            key = "home" if i > j else "away" if i < j else "draw"
            p[key] += pmf(lam_h, i) * pmf(lam_a, j)
    total = sum(p.values())
    return {k: v / total for k, v in p.items()}


def _anchors_from_matches(tournament, matches) -> dict:
    """BoldMatch.euro_fair_prob(已 de-vig)→ {frozenset(en队名对): 概率}(spec §3.3)。"""
    zh_to_en = {t.zh: t.id for t in tournament.teams.values()}
    anchors = {}
    for m in matches:
        if not getattr(m, "euro_fair_prob", None):
            continue
        h, a = zh_to_en.get(m.home), zh_to_en.get(m.away)
        if h and a:
            anchors[frozenset((h, a))] = dict(m.euro_fair_prob)
    return anchors


def _injury_counts(matches, tournament, injuries_fetcher) -> dict[str, int]:
    """当日参赛队伤病人数;fetcher 缺省/失败 → 空(spec §3.2 静默跳过)。"""
    if injuries_fetcher is None:
        return {}
    try:
        return dict(injuries_fetcher([m for m in matches]))
    except Exception:  # noqa: BLE001
        logger.warning("worldcup: injuries 获取失败,跳过折减", exc_info=True)
        return {}


def _todays_rows(tournament, matches, sim) -> list[dict]:
    zh_to_en = {t.zh: t.id for t in tournament.teams.values()}
    rows = []
    for m in matches:
        h, a = zh_to_en.get(m.home), zh_to_en.get(m.away)
        if not h or not a:
            continue
        ph, pa = sim.probs.get(h), sim.probs.get(a)
        if not ph or not pa:
            continue
        rows.append({
            "label": f"{m.home} vs {m.away}",
            "qualify": f"{ph['qualify']:.0%}/{pa['qualify']:.0%}",
            "r16": f"{ph['r16']:.0%}/{pa['r16']:.0%}",
            "champion": f"{ph['champion']:.1%}/{pa['champion']:.1%}",
        })
    return rows
