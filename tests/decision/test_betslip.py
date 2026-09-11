# tests/decision/test_betslip.py
"""实票登记的算术与结算。注数公式全部用 2026-09-11 的真实票面反算核对过。"""
import pytest

from nutmeg.decision.betslip import (
    BetSlip,
    BetslipError,
    SlipLeg,
    format_slips,
    load_slips,
    parlay_note_count,
    parse_faces,
    parse_faces_row,
    register_slip,
    settle_slip,
    zucai_note_count,
)

FAIR_H = {"home": 0.605, "draw": 0.220, "away": 0.174}
FAIR_FLAT = {"home": 0.370, "draw": 0.252, "away": 0.378}


# ── 面集合解析（不再人肉读截图） ──

def test_parse_faces_normalises_and_rejects_garbage():
    assert parse_faces("13") == "31"          # 顺序规范化到 3→1→0
    assert parse_faces("310") == "310"
    assert parse_faces("*") == ""             # 未选该场
    with pytest.raises(BetslipError):
        parse_faces("32")                     # 2 不是合法面
    with pytest.raises(BetslipError):
        parse_faces("33")                     # 重复面


def test_parse_positional_row_matches_real_ticket():
    """26122 T2 方案 9007 的整行：`*` 表示未选，恰好 14 个 token。"""
    row = "310 10 0 3 310 31 30 * 1 * * * 3 *"
    faces = parse_faces_row(row)
    assert faces == {"1": "310", "2": "10", "3": "0", "4": "3", "5": "310",
                     "6": "31", "7": "30", "9": "1", "13": "3"}


def test_parse_named_row_is_order_free():
    assert parse_faces_row("13·3 2·310 6·31", n_matches=14) == {
        "13": "3", "2": "310", "6": "31"}


def test_positional_row_requires_full_width():
    """少一个 token 就会整列错位——这正是人眼读票的死法，必须抛错而不是猜。"""
    with pytest.raises(BetslipError):
        parse_faces_row("310 10 0 3", n_matches=14)


# ── 注数算术（对着真票反算） ──

def test_renjiu_exactly_nine_matches_real_ticket():
    """26122 T1：2/5 全包 + 3·10 4·31 6·31 11·31 12·31 + 7·3 13·3 = 288 注 ¥576。"""
    faces = {"2": "310", "3": "10", "4": "31", "5": "310", "6": "31",
             "7": "3", "11": "31", "12": "31", "13": "3"}
    assert zucai_note_count(faces, channel="renjiu") == 288


def test_renjiu_ten_matches_is_combinatorial_not_product():
    """任九选 10 场是复式：Σ 9-场子集的连乘，不是简单连乘（否则会少算）。"""
    faces = {str(i): "3" for i in range(1, 10)} | {"10": "31"}
    # 9 个单选 + 1 个双选：C(10,9) 个子集，其中 9 个含双选(=2 注)、1 个不含(=1 注)
    assert zucai_note_count(faces, channel="renjiu") == 9 * 2 + 1


def test_shengfucai_needs_all_fourteen():
    faces = {str(i): "3" for i in range(1, 14)}
    with pytest.raises(BetslipError):
        zucai_note_count(faces, channel="shengfucai")


def test_parlay_counts_match_real_jczq_slips():
    """三张竞彩实票反算：J1 4串1=2 注、J2 5串1=1 注、J3 混合过关=4 注。"""
    assert parlay_note_count([1, 1, 1, 2], [4]) == 2        # 011 选了胜+平
    assert parlay_note_count([1, 1, 1, 1, 1], [5]) == 1
    assert parlay_note_count([1, 1, 1], [2, 3]) == 4        # C(3,2)+C(3,3)


def test_parlay_rejects_impossible_combo():
    with pytest.raises(BetslipError):
        parlay_note_count([1, 1], [3])


# ── 票面对象 ──

def _jczq_slip(**kw):
    legs = [
        SlipLeg(key="周五003", name="纽伦堡-汉诺威", market="hhad", line=1.0,
                selections=("home",), odds=(1.45,), fair=FAIR_FLAT),
        SlipLeg(key="周五009", name="雷恩-马赛", market="had",
                selections=("home",), odds=(1.87,), fair=FAIR_H),
    ]
    base = dict(slip_id="J-test", channel="jczq", placed_at="2026-09-11",
                legs=legs, multiplier=25, combo_sizes=(2,))
    base.update(kw)
    return BetSlip(**base)


def test_slip_stake_includes_multiplier():
    slip = _jczq_slip()
    assert slip.notes == 1
    assert slip.stake_yuan == 1 * 2 * 25          # 注数 × ¥2 × 倍数


def test_hhad_coverage_uses_three_way_not_asian():
    """体彩让球是 3 路：受让 +1 的"让胜"= 主胜 + 平，不是亚盘直觉的"不败赔率"。"""
    leg = SlipLeg(key="周五003", market="hhad", line=1.0,
                  selections=("home", "draw"), fair=FAIR_FLAT)
    assert leg.coverage == pytest.approx(0.370 + 0.252)


def test_hit_probability_is_none_when_fair_missing():
    """禁嘴算：任何一腿缺 fair，整票 P 留空，不拿部分数据凑一个数。"""
    slip = _jczq_slip()
    slip.legs[0].fair = None
    assert slip.hit_probability is None


def test_trial_slip_excluded_from_stake_total():
    """试玩虚拟方案不进净值——26121 U1/U2 就是试玩方案号，混进账会污染行权记分。"""
    real = _jczq_slip(slip_id="real")
    trial = _jczq_slip(slip_id="trial", purchased=False)
    out = format_slips([real, trial])
    assert "[试玩]" in out
    assert f"合计实购投入 ¥{real.stake_yuan:,}" in out


# ── 结算（多市场 + 串关） ──

_RESULTS = {
    "周五003": {"outcome_90": "away", "goals_h": 1, "goals_a": 2},   # 受让+1 → 让平
    "周五009": {"outcome_90": "home", "goals_h": 2, "goals_a": 1},
}


def test_parlay_settlement_pays_only_winning_combos():
    slip = _jczq_slip(multiplier=1)
    s = settle_slip(slip, _RESULTS)
    # 003 受让 +1、实际 1:2 → margin+line = 0 → 让平；票选让胜 → 未中 → 串关全废
    assert s.won_legs == 1
    assert s.combos_won == 0
    assert s.payout_yuan == 0.0
    assert s.pnl_yuan == -slip.stake_yuan


def test_parlay_settlement_wins_when_all_legs_hit():
    legs = [
        SlipLeg(key="a", market="had", selections=("home",), odds=(2.0,), fair=FAIR_H),
        SlipLeg(key="b", market="had", selections=("home",), odds=(1.5,), fair=FAIR_H),
    ]
    slip = BetSlip(slip_id="J2", channel="jczq", placed_at="2026-09-11",
                   legs=legs, multiplier=10, combo_sizes=(2,))
    s = settle_slip(slip, {"a": {"outcome_90": "home", "goals_h": 1, "goals_a": 0},
                           "b": {"outcome_90": "home", "goals_h": 2, "goals_a": 0}})
    assert s.combos_won == 1
    assert s.payout_yuan == pytest.approx(2.0 * 1.5 * 2 * 10)   # ¥60
    assert s.pnl_yuan == pytest.approx(60.0 - slip.stake_yuan)  # 注金 1×¥2×10 = ¥20


def test_mixed_parlay_settles_each_combo_size():
    """J3 型混合过关（2串1+3串1）：三腿全中时 4 个组合全中。"""
    legs = [SlipLeg(key=k, market="ttg", selections=("7",), odds=(7.6,))
            for k in ("a", "b", "c")]
    slip = BetSlip(slip_id="J3", channel="jczq", placed_at="2026-09-11",
                   legs=legs, multiplier=1, combo_sizes=(2, 3))
    res = {k: {"outcome_90": "home", "goals_h": 5, "goals_a": 3} for k in ("a", "b", "c")}
    s = settle_slip(slip, res)
    assert (s.combos_total, s.combos_won) == (4, 4)


def test_pending_leg_keeps_payout_none():
    """赛果缺 → 整票 pending，绝不按"已知部分"伪造派奖。"""
    slip = _jczq_slip()
    s = settle_slip(slip, {"周五003": _RESULTS["周五003"]})
    assert s.pending_legs == 1
    assert s.payout_yuan is None and s.pnl_yuan is None


def test_zucai_settlement_needs_official_prize():
    """足彩是派彩式：没有官方单注奖金就不产派奖数字（26102 曾把奖金写成注数）。"""
    faces = {str(i): "3" for i in range(1, 10)}
    legs = [SlipLeg(key=str(i), market="had", selections=("home",)) for i in range(1, 10)]
    slip = BetSlip(slip_id="U1", channel="renjiu", placed_at="2026-09-11",
                   legs=legs, faces=faces, multiplier=50)
    res = {str(i): {"outcome_90": "home", "goals_h": 1, "goals_a": 0} for i in range(1, 10)}
    assert settle_slip(slip, res).payout_yuan is None
    paid = settle_slip(slip, res, prize_per_note=14.0)
    assert paid.payout_yuan == pytest.approx(14.0 * 1 * 50)


# ── 登记簿 ──

def test_register_is_idempotent_by_slip_id(tmp_path):
    slip = _jczq_slip()
    register_slip(tmp_path, slip)
    slip.note = "改过备注"
    line = register_slip(tmp_path, slip)
    assert len(load_slips(tmp_path)) == 1
    assert "登记 J-test 竞彩" in line
    assert load_slips(tmp_path)[0].note == "改过备注"


def test_register_warns_when_scheme_number_missing(tmp_path):
    """方案号缺失要在摘要里喊出来——26120/26121/26122 的账就是这么空着的。"""
    assert "方案号待补" in register_slip(tmp_path, _jczq_slip())
    assert "方案 2026" in register_slip(
        tmp_path, _jczq_slip(slip_id="J-2", scheme_no="20260911000322610008531"))


def test_register_rejects_unknown_channel(tmp_path):
    with pytest.raises(BetslipError):
        register_slip(tmp_path, _jczq_slip(channel="hafu"))


def test_p_any_combo_is_exact_not_sum_of_combos():
    """混合过关"中任意一串"必须枚举情景算，串与串共享腿、相加会高估。

    3 腿各 50%、2串1+3串1：至少 2 腿命中 = 3×0.25×0.5 + 0.125 = 0.5。
    若按"各串概率相加"会得到 3×0.25 + 0.125 = 0.875 —— 高估 37.5pp。
    """
    fair = {"home": 0.5, "draw": 0.3, "away": 0.2}
    legs = [SlipLeg(key=k, market="had", selections=("home",), odds=(2.0,), fair=fair)
            for k in ("a", "b", "c")]
    slip = BetSlip(slip_id="mix", channel="jczq", placed_at="2026-09-11",
                   legs=legs, combo_sizes=(2, 3))
    assert slip.p_any_combo == pytest.approx(0.5)
    assert slip.hit_probability == pytest.approx(0.125)   # P(全对) 是另一个数
