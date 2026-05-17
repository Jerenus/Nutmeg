from __future__ import annotations

from nutmeg.services.value_calibration import (
    MatchWinnerView,
    calibration_stats,
)


def _view(
    fid: str,
    *,
    model: tuple[float, float, float],
    market: tuple[float, float, float],
) -> MatchWinnerView:
    return MatchWinnerView(
        fixture_id=fid,
        model_home=model[0],
        model_draw=model[1],
        model_away=model[2],
        market_home=market[0],
        market_draw=market[1],
        market_away=market[2],
    )


def test_calibration_stats_empty_input() -> None:
    stats = calibration_stats([])

    assert stats.fixtures == 0
    assert stats.direction_agreement == 0.0
    assert stats.home_prob_correlation == 0.0


def test_calibration_stats_direction_agreement() -> None:
    # 3 of 4 fixtures: model's argmax direction matches the market's.
    views = [
        _view('a', model=(0.6, 0.2, 0.2), market=(0.55, 0.25, 0.20)),  # both home
        _view('b', model=(0.2, 0.2, 0.6), market=(0.25, 0.25, 0.50)),  # both away
        _view('c', model=(0.5, 0.3, 0.2), market=(0.45, 0.35, 0.20)),  # both home
        _view('d', model=(0.6, 0.2, 0.2), market=(0.20, 0.25, 0.55)),  # model home, market away
    ]

    stats = calibration_stats(views)

    assert stats.fixtures == 4
    assert stats.direction_agreement == 0.75


def test_calibration_stats_home_prob_correlation_is_strong_when_aligned() -> None:
    # model P(home) tracks market P(home) closely -> correlation near 1.
    views = [
        _view('a', model=(0.20, 0.3, 0.5), market=(0.22, 0.3, 0.48)),
        _view('b', model=(0.45, 0.3, 0.25), market=(0.43, 0.3, 0.27)),
        _view('c', model=(0.70, 0.2, 0.1), market=(0.68, 0.2, 0.12)),
    ]

    stats = calibration_stats(views)

    assert stats.home_prob_correlation > 0.9


def test_calibration_stats_home_prob_correlation_negative_when_fading() -> None:
    # model fades the market: where the market likes home, the model doesn't.
    views = [
        _view('a', model=(0.70, 0.2, 0.10), market=(0.20, 0.3, 0.50)),
        _view('b', model=(0.45, 0.3, 0.25), market=(0.45, 0.3, 0.25)),
        _view('c', model=(0.20, 0.2, 0.60), market=(0.70, 0.2, 0.10)),
    ]

    stats = calibration_stats(views)

    assert stats.home_prob_correlation < 0.0
