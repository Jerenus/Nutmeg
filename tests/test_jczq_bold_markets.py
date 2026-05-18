"""Tests for the bold engine's 体彩 multi-market math (pure, no I/O)."""

from nutmeg.services.jczq_bold_markets import (
    aggregate_crs_to_had,
    aggregate_crs_to_hhad,
    aggregate_crs_to_ttg,
    aggregate_ttg_to_over_under,
    crs_scoreline_distribution,
)


def test_crs_scoreline_distribution_devigs_exact_and_other() -> None:
    # Three exact scorelines + one 其他 bucket; equal odds → equal de-vigged mass.
    crs_odds = {"s01s00": 4.0, "s00s00": 4.0, "s00s01": 4.0, "s1sa": 4.0}

    exact, other = crs_scoreline_distribution(crs_odds)

    assert set(exact) == {(1, 0), (0, 0), (0, 1)}
    assert set(other) == {"away"}
    total = sum(exact.values()) + sum(other.values())
    assert abs(total - 1.0) < 1e-9          # de-vigged over ALL crs outcomes
    assert abs(exact[(1, 0)] - 0.25) < 1e-9


def test_aggregate_crs_to_had_sums_by_sign() -> None:
    # 1:0 → home, 0:0 → draw, 0:1 → away, 其他负 → away. Equal mass 0.25 each.
    crs_odds = {"s01s00": 4.0, "s00s00": 4.0, "s00s01": 4.0, "s1sa": 4.0}

    had = aggregate_crs_to_had(*crs_scoreline_distribution(crs_odds))

    assert abs(had["home"] - 0.25) < 1e-9
    assert abs(had["draw"] - 0.25) < 1e-9
    assert abs(had["away"] - 0.50) < 1e-9   # 0:1 + 其他负
    assert abs(sum(had.values()) - 1.0) < 1e-9


def test_aggregate_crs_to_ttg_buckets_by_total_and_renormalizes() -> None:
    # 1:0 (total 1), 1:1 (total 2), 2:1 (total 3) — equal exact mass. The 0.25
    # of 其他 mass carries no definite total → DROPPED then re-normalized away
    # (aggregate_crs_to_ttg takes only the exact distribution).
    exact = {(1, 0): 0.25, (1, 1): 0.25, (2, 1): 0.25}

    ttg = aggregate_crs_to_ttg(exact)

    assert set(ttg) == {f"total_{k}" for k in range(8)}
    assert abs(sum(ttg.values()) - 1.0) < 1e-9          # re-normalized over exact mass
    assert abs(ttg["total_1"] - 1 / 3) < 1e-9           # 0.25 / 0.75
    assert ttg["total_0"] == 0.0


def test_aggregate_crs_to_ttg_caps_at_total_7() -> None:
    ttg = aggregate_crs_to_ttg({(5, 3): 0.5, (4, 4): 0.5})  # totals 8 and 8
    assert abs(ttg["total_7"] - 1.0) < 1e-9               # 7+ bucket


def test_aggregate_crs_to_hhad_shifts_by_line() -> None:
    # line -1 (home gives 1): 2:0 → adj 1:0 让胜, 1:0 → adj 0:0 让平,
    # 0:1 → adj -1:1 让负. Equal mass.
    exact = {(2, 0): 1 / 3, (1, 0): 1 / 3, (0, 1): 1 / 3}

    hhad = aggregate_crs_to_hhad(exact, line=-1.0)

    assert abs(hhad["home"] - 1 / 3) < 1e-9
    assert abs(hhad["draw"] - 1 / 3) < 1e-9
    assert abs(hhad["away"] - 1 / 3) < 1e-9
    assert abs(sum(hhad.values()) - 1.0) < 1e-9


def test_aggregate_ttg_to_over_under_splits_on_line() -> None:
    ttg_fair = {f"total_{k}": 0.0 for k in range(8)}
    ttg_fair["total_1"] = 0.4   # under 2.5
    ttg_fair["total_2"] = 0.2   # under 2.5
    ttg_fair["total_3"] = 0.4   # over 2.5

    ou = aggregate_ttg_to_over_under(ttg_fair, line=2.5)

    assert abs(ou["over"] - 0.4) < 1e-9
    assert abs(ou["under"] - 0.6) < 1e-9
