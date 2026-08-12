# tests/decision/test_dcfit.py
from nutmeg.decision.dcfit import (
    fit_match,
    hhad_cover,
    margin_dist,
    matrix,
    outcomes,
    ttg_bands,
)


def test_matrix_is_a_distribution():
    m = matrix(1.5, 1.2, -0.06)
    assert abs(sum(m.values()) - 1.0) < 1e-9
    assert all(p >= 0 for p in m.values())


def test_fit_recovers_the_fair_it_was_given():
    """拟合是"从去水 fair 反推 λ/ρ",所以 DC 三路必须几乎重现输入 fair。

    这条守住的是整条链的可信度:模态比分/进球带都建立在这个复现之上。
    """
    fair = {"home": 0.5657, "draw": 0.2336, "away": 0.2007}
    rec = fit_match(fair)
    for got, want in zip(rec["dc_had"], (fair["home"], fair["draw"], fair["away"]), strict=True):
        assert abs(got - want) < 0.01


def test_ttg_bands_cover_all_mass():
    m = matrix(1.4, 1.1, -0.06)
    assert abs(sum(ttg_bands(m).values()) - 1.0) < 1e-9


def test_hhad_is_three_way_not_asian_handicap():
    """⚠️体彩让球是三路胜平负:整数盘让 1 球时"主队恰好胜 1 球"落进【让平】,
    不像亚盘那样退款给受让方。这条一旦弄反,受让腿命中率会被系统性高估 ~28pp。
    """
    md = margin_dist(matrix(1.8, 1.0, -0.06))
    cover = hhad_cover(md, "-1")                                # 输出 round 到 4 位
    assert abs(cover["让平"] - md[1]) < 1e-4                    # 恰净胜 1 → 让平
    assert abs(cover["让胜"] - sum(v for k, v in md.items() if k >= 2)) < 1e-4
    assert abs(cover["让负"] - sum(v for k, v in md.items() if k <= 0)) < 1e-4
    assert abs(sum(cover[k] for k in ("让胜", "让平", "让负")) - 1.0) < 1e-3


def test_hhad_cover_absent_without_line():
    assert hhad_cover({0: 1.0}, None) is None


def test_ttg_constraint_changes_the_shape():
    """给了体彩 ttg 分布做形状约束时,ρ 参与拟合;没给则固定 —— 两者应当不同。"""
    fair = {"home": 0.41, "draw": 0.28, "away": 0.31}
    free = fit_match(fair)
    lowscoring = {f"total_{k}": v for k, v in
                  zip(range(8), [0.14, 0.24, 0.26, 0.18, 0.10, 0.05, 0.02, 0.01],
                      strict=True)}
    tied = fit_match(fair, ttg_fair=lowscoring)
    assert free["ttg_anchor"] is False and tied["ttg_anchor"] is True
    assert tied["over25"] < free["over25"]      # 被低进球分布拽下来


def test_outcomes_partition_the_matrix():
    m = matrix(1.3, 1.3, -0.06)
    assert abs(sum(outcomes(m)) - 1.0) < 1e-9
