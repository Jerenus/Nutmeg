"""matplotlib 图表 — 只验证「能出非空 PNG」与字体降级,不验证像素。"""
from __future__ import annotations

from nutmeg.services.worldcup.charts import (
    champion_bar_png,
    champion_trend_png,
    group_table_png,
)
from nutmeg.services.worldcup.sim import SimOutput
from nutmeg.services.worldcup.tournament import Tournament

from tests.test_wc_tournament import _mini_tournament_dict

KEYS = ("qualify", "r32", "r16", "qf", "sf", "final", "champion")


def _sim(d: str, mex: float) -> SimOutput:
    probs = {t: dict.fromkeys(KEYS, 0.1)
             for t in ("Mexico", "Poland", "Senegal", "Jordan")}
    probs["Mexico"]["champion"] = mex
    return SimOutput(run_date=d, seed=1, n_sims=100, probs=probs)


def _t() -> Tournament:
    return Tournament.from_dict(_mini_tournament_dict())


def test_champion_bar_png_nonempty() -> None:
    png = champion_bar_png(_t(), _sim("2026-06-12", 0.4), _sim("2026-06-11", 0.3))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000


def test_champion_bar_handles_missing_yesterday() -> None:
    assert champion_bar_png(_t(), _sim("2026-06-12", 0.4), None)[:4] == b"\x89PNG"


def test_trend_png_with_history() -> None:
    history = [_sim(f"2026-06-{d:02d}", 0.2 + d / 100) for d in (11, 12, 13)]
    assert champion_trend_png(_t(), history)[:4] == b"\x89PNG"


def test_group_table_png() -> None:
    assert group_table_png(_t(), results=[])[:4] == b"\x89PNG"


def test_judge_trend_png() -> None:
    from nutmeg.services.worldcup.charts import judge_trend_png

    png = judge_trend_png(
        dates=["06-12", "06-13", "06-14"],
        judge_rates=[0.5, 0.6, 0.55],
        baseline_rates=[0.5, 0.5, 0.52],
    )
    assert png[:4] == b"\x89PNG"
