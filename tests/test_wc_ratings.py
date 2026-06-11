# tests/test_wc_ratings.py
"""worldcup.ratings — 攻/防两维 Elo(spec §3.1-§3.2)。"""
from __future__ import annotations

from nutmeg.services.worldcup.ratings import (
    HOST_BOOST,
    TeamRating,
    expected_lambdas,
    injury_adjusted,
    update_after_match,
)


def test_stronger_attack_gets_higher_lambda() -> None:
    strong = TeamRating(atk=1000.0, dfn=1000.0)
    weak = TeamRating(atk=850.0, dfn=850.0)
    lam_s, lam_w = expected_lambdas(strong, weak, host_advantage=False)
    assert lam_s > lam_w > 0


def test_host_boost_only_inflates_host_side() -> None:
    a = TeamRating(atk=900.0, dfn=900.0)
    base_h, base_a = expected_lambdas(a, a, host_advantage=False)
    boost_h, boost_a = expected_lambdas(a, a, host_advantage=True)
    assert abs(boost_h - base_h * HOST_BOOST) < 1e-9
    assert boost_a == base_a


def test_update_moves_ratings_toward_residual() -> None:
    h, a = TeamRating(900.0, 900.0), TeamRating(900.0, 900.0)
    # 主队 3:0 大胜均势对手 → 主队 atk↑ dfn↑,客队反向
    h2, a2 = update_after_match(h, a, goals_h=3, goals_a=0, host_advantage=False)
    assert h2.atk > h.atk and h2.dfn > h.dfn
    assert a2.atk < a.atk and a2.dfn < a.dfn


def test_update_is_zero_sum_in_direction() -> None:
    h, a = TeamRating(950.0, 920.0), TeamRating(880.0, 905.0)
    lam_h, lam_a = expected_lambdas(h, a, host_advantage=False)
    # 赛果恰等于期望(取整数最接近) → 变动很小
    h2, a2 = update_after_match(h, a, goals_h=round(lam_h), goals_a=round(lam_a),
                                host_advantage=False)
    assert abs(h2.atk - h.atk) < 10.0


def test_injury_adjusted_below_threshold_is_noop() -> None:
    r = TeamRating(900.0, 900.0)
    assert injury_adjusted(r, n_out=2) == r
    adj = injury_adjusted(r, n_out=3)
    assert adj.atk == 900.0 * 0.95 and adj.dfn == 900.0 * 0.95


def test_seed_covers_all_48_teams() -> None:
    from pathlib import Path

    import pytest

    if not Path("nutmeg/data/wc2026_elo_seed.json").exists():
        pytest.skip("种子未落库")
    from nutmeg.services.worldcup.ratings import load_seed
    from nutmeg.services.worldcup.tournament import load_tournament

    seed = load_seed()
    assert set(seed) == set(load_tournament().teams)
