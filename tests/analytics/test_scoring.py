import math

from nutmeg.analytics.scoring import (
    brier,
    brier_skill,
    closing_skill_delta,
    directional_alignment,
    log_score,
    rps,
    ticket_clv_log,
)


def test_brier_perfect_and_worst() -> None:
    perfect = {"home": 1.0, "draw": 0.0, "away": 0.0}
    assert brier(perfect, perfect) == 0.0
    assert brier({"home": 0.0, "draw": 0.0, "away": 1.0}, perfect) == 2.0


def test_brier_skill_and_zero_denominator() -> None:
    assert brier_skill([0.2], [0.5]) == 1 - 0.2 / 0.5
    assert brier_skill([0.0], [0.0]) is None


def test_closing_and_directional() -> None:
    q = {"home": 0.6, "draw": 0.25, "away": 0.15}
    p = {"home": 0.5, "draw": 0.3, "away": 0.2}
    c = {"home": 0.62, "draw": 0.24, "away": 0.14}
    assert closing_skill_delta(q, p, c) < 0
    assert directional_alignment(q, p, c) > 0


def test_log_score_and_rps_and_clv() -> None:
    assert log_score({"home": 0.5}, {"home": 1.0}, clip=1e-9) == -math.log(0.5)
    exact = {"a": 0.0, "b": 1.0, "c": 0.0}
    assert rps(exact, exact) == 0.0
    # off-by-one-bucket ordered miss is penalised, unordered Brier would not see order
    assert rps({"a": 1.0, "b": 0.0, "c": 0.0}, {"a": 0.0, "b": 0.0, "c": 1.0}) == 2.0
    assert ticket_clv_log(2.10, 2.00) == math.log(2.10 / 2.00)
