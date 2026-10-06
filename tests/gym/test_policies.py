import json
from pathlib import Path

import pytest

from nutmeg.gym.board import load_jczq_board, load_zucai_issue
from nutmeg.gym.payout import check_jczq_legal, settle_jczq
from nutmeg.gym.policy import Ctx, get, names
from tests.gym.test_board import DAY, _jczq_day, _match, _zucai_issue


def _three_match_board(tmp_path: Path):
    data = _jczq_day(tmp_path)
    day_dir = data / "jczq" / "daily" / DAY
    doc = json.loads((day_dir / "sporttery_markets.json").read_text(encoding="utf-8"))
    doc["matchInfoList"][0]["subMatchList"].append(
        _match("周六004", single=0, had=("1.25", "5.50", "9.00")))
    (day_dir / "sporttery_markets.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                     encoding="utf-8")
    def sharp(h, d, a):
        return {"sharp": {"fair_probability": {"home": h, "draw": d, "away": a}}}

    closing = {"周六001": sharp(0.52, 0.26, 0.22), "周六002": sharp(0.72, 0.18, 0.10),
               "周六004": sharp(0.78, 0.14, 0.08)}
    (day_dir / "closing_odds.json").write_text(json.dumps(closing), encoding="utf-8")
    return data, load_jczq_board(data, DAY)


def test_registry_lists_the_preregistered_policies() -> None:
    assert {"flat", "jczq_max_p", "jczq_ev_filter", "jczq_fav_pairs", "zucai_max_p",
            "zucai_fav_single", "zucai_prescription", "real"} <= set(names())
    assert get("flat").decide(None, Ctx()) == []


def test_jczq_max_p_builds_legal_parlays_within_cap(tmp_path: Path) -> None:
    _, board = _three_match_board(tmp_path)
    slips = get("jczq_max_p").decide(board.visible(), Ctx(cap_jczq_day=400))

    assert slips and sum(s.stake_yuan for s in slips) <= 400
    for slip in slips:
        assert check_jczq_legal(slip, board) is None
        assert len(slip.legs) >= 2 and slip.combo_sizes == (len(slip.legs),)
        assert all(leg.key in board.matches for leg in slip.legs)
        assert all(set(leg.selections) <= {"home", "draw", "away"} for leg in slip.legs)


def test_jczq_fav_pairs_only_pairs_closing_favorites(tmp_path: Path) -> None:
    _, board = _three_match_board(tmp_path)
    slips = get("jczq_fav_pairs").decide(board.visible(), Ctx())

    assert len(slips) == 1          # 周六002 × 周六004 一对；周六001 终盘 0.52 不算热门
    [slip] = slips
    assert {leg.key for leg in slip.legs} == {"周六002", "周六004"}
    assert all(leg.selections == ("home",) for leg in slip.legs)
    assert slip.stake_yuan == 2


def test_jczq_ev_filter_uses_only_positive_closing_ev_faces(tmp_path: Path) -> None:
    _, board = _three_match_board(tmp_path)
    slips = get("jczq_ev_filter").decide(board.visible(), Ctx())
    # 周六001: home 0.52×1.85=0.96 ✗ draw 0.26×3.4=0.88 ✗ away 0.22×3.9=0.86 ✗ → 无面
    # 周六002: home 0.72×1.85=1.33 ✓；周六004: home 0.78×1.25=0.975 ✗ → 只剩一条腿，凑不成 2 串 1
    assert slips == []


def test_zucai_max_p_and_fav_single_return_one_renjiu_slip_each(tmp_path: Path) -> None:
    data = _zucai_issue(tmp_path)
    issue = load_zucai_issue(data, "26127")
    ctx = Ctx(cap_zucai_slip=400, extra={"data_dir": data})

    [slip] = get("zucai_max_p").decide(issue.visible(), ctx)
    assert slip.channel == "renjiu" and len(slip.faces) == 9 and slip.stake_yuan <= 400
    assert slip.issue == "26127" and slip.placed_at == "2026-09-16"

    [fav] = get("zucai_fav_single").decide(issue.visible(), ctx)
    assert fav.channel == "renjiu" and len(fav.faces) == 9
    assert all("0" not in f or len(f) > 1 for f in fav.faces.values())   # 0.2 以下的客胜不进全包


def test_zucai_prescription_and_real_replay_from_files(tmp_path: Path) -> None:
    data = _zucai_issue(tmp_path)
    issue = load_zucai_issue(data, "26127")
    final = {"issue": "26127", "tickets": [
        {"id": "R9", "kind": "任九", "faces": {str(i): "3" for i in range(1, 10)}},
        {"id": "SFC", "kind": "胜负彩", "faces": {str(i): "31" for i in range(1, 15)}},
        {"id": "bad", "kind": "任九", "faces": {"1": "3"}}]}
    (data / "zucai" / "26127-final-tickets.json").write_text(json.dumps(final), encoding="utf-8")
    (data / "betslips.jsonl").write_text("\n".join(json.dumps(row) for row in [
        {"slip_id": "20260920-J1", "channel": "jczq", "placed_at": "2026-09-20", "purchased": True,
         "legs": [{"key": "周六001", "name": "x", "market": "had", "line": None,
                   "selections": ["home"], "odds": [1.85]},
                  {"key": "周六002", "name": "y", "market": "had", "line": None,
                   "selections": ["home"], "odds": [1.85]}], "combo_sizes": [2], "multiplier": 1},
        {"slip_id": "R-26127", "channel": "renjiu", "placed_at": "2026-09-16", "purchased": True,
         "issue": "26127", "legs": [], "faces": {str(i): "3" for i in range(1, 10)}},
        {"slip_id": "trial", "channel": "renjiu", "placed_at": "2026-09-16", "purchased": False,
         "issue": "26127", "legs": [], "faces": {str(i): "3" for i in range(1, 10)}},
    ]) + "\n", encoding="utf-8")
    ctx = Ctx(extra={"data_dir": data})

    rx = get("zucai_prescription").decide(issue.visible(), ctx)
    assert [(s.channel, len(s.faces)) for s in rx] == [("renjiu", 9), ("shengfucai", 14)]

    real_zucai = get("real").decide(issue.visible(), ctx)
    assert [s.slip_id for s in real_zucai] == ["R-26127"]            # 试玩票不回放
    board = load_jczq_board(_jczq_day(tmp_path), DAY)
    assert [s.slip_id for s in get("real").decide(board.visible(), ctx)] == ["20260920-J1"]


def test_fav_pairs_runs_on_history_boards_with_closing_belief(tmp_path: Path) -> None:
    from tests.gym.test_board import _history_data

    data = _history_data(tmp_path)
    board = load_jczq_board(data, "2025-12-14", allow_history=True)

    [slip] = get("jczq_fav_pairs").decide(board.visible(), Ctx())
    assert {leg.key for leg in slip.legs} == {"周日001", "周日003"}
    assert check_jczq_legal(slip, board) is None
    assert settle_jczq(slip, board).payout_yuan == pytest.approx(1.45 * 1.3 * 2)


def test_jczq_rule_v3_goes_flat_unless_expected_return_reaches_one(tmp_path: Path) -> None:
    """Dream 评估器 v3 迁入 gym：最高期望回报 < 1 → 规则最优＝空仓；否则只出最高那一张。"""
    _, board = _three_match_board(tmp_path)
    # 市场口径＝体彩价去水：任何组合的期望回报都 < 1 → 空仓
    assert get("jczq_rule_v3").decide(board.visible(), Ctx(belief_source="market")) == []
    # 终盘口径：周六002 终盘主胜 0.72 × 体彩 1.85 > 1 → 只出期望回报最高的一张
    slips = get("jczq_rule_v3").decide(board.visible(), Ctx(belief_source="closing"))
    assert len(slips) == 1 and len(slips[0].legs) >= 2
    assert check_jczq_legal(slips[0], board) is None


def test_zucai_draft_replays_the_prescription_faithful_rule_from_legs_base(tmp_path: Path) -> None:
    data = _zucai_issue(tmp_path)
    fair = {"home": 0.6, "draw": 0.25, "away": 0.15}
    prescription = {str(i): ("3" if i <= 9 else "310") for i in range(1, 15)}
    prescription["1"] = "31"
    (data / "zucai" / "26127-legs-base.json").write_text(json.dumps({
        "issue": "26127", "prescription": prescription,
        "legs": {str(i): {"name": f"H{i}-A{i}", "fair": fair} for i in range(1, 15)}}),
        encoding="utf-8")
    issue = load_zucai_issue(data, "26127")

    [slip] = get("zucai_draft").decide(issue.visible(), Ctx(cap_zucai_slip=400,
                                                             extra={"data_dir": data}))
    # 只丢场不降档，帽内取 P 最高：四个全包（第五个就超帽、要降档）+ 场1 双选 + 四个裸单，
    # 2×3⁴=162 注 ¥324；同 P 按场号取先
    assert slip.channel == "renjiu" and slip.placed_at == "2026-09-16"
    assert slip.faces == {"1": "31", "2": "3", "3": "3", "4": "3", "5": "3",
                          "10": "310", "11": "310", "12": "310", "13": "310"}
    assert slip.stake_yuan == 324
    assert all(slip.faces[no] == prescription[no] for no in slip.faces)   # 没有降档
    assert get("zucai_draft").decide(issue.visible(), Ctx()) == []        # 没有 data_dir
    (data / "zucai" / "26127-legs-base.json").unlink()
    assert get("zucai_draft").decide(issue.visible(), Ctx(extra={"data_dir": data})) == []
