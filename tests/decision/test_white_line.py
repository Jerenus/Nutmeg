"""白防线（2026-11-08 Jun 批：过度防御的缩减 + 预警多时提醒）。"""
from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.white_line import (
    month_cost,
    ratio,
    reference,
    reminder_lines,
    warnings,
)

HOT = {"home": 0.73, "draw": 0.16, "away": 0.11}     # 一赔条件 0.82，线以上
WARM = {"home": 0.65, "draw": 0.18, "away": 0.17}    # 0.78
COIN = {"home": 0.52, "draw": 0.26, "away": 0.22}    # 0.67
LOW = {"home": 0.38, "draw": 0.30, "away": 0.32}     # 一二赔＝主客，0.54


def _legs(spec: dict[str, dict], raw: dict[str, dict] | None = None) -> dict:
    raw = raw or {}
    return {no: {"name": f"m{no}", "belief": dict(b), "raw": raw.get(no, {})}
            for no, b in spec.items()}


BOARD = {**{n: HOT for n in ("1", "2")}, "3": WARM,
         **{str(n): COIN for n in range(4, 10)}, **{str(n): LOW for n in range(10, 15)}}


def test_ratio_is_top_face_share_of_the_top_two():
    assert ratio(HOT) == ("3", "1", round(0.73 / 0.89, 4))
    assert ratio(LOW)[:2] == ("3", "0")


def test_renjiu_reference_singles_above_the_line_and_doubles_below():
    ref = reference(_legs(BOARD), channel="renjiu", cap_yuan=800)
    assert ref["faces"] == {"1": "3", "2": "3", "3": "31", **{str(n): "31" for n in range(4, 10)}}
    assert ref["stake_yuan"] == 256 and ref["dropped"] == [str(n) for n in range(10, 15)]
    assert ref["alerts"] == []


def test_renjiu_reference_adds_doubles_lowest_share_first_until_the_cap():
    ref = reference(_legs(BOARD), channel="renjiu", cap_yuan=128)
    assert ref["stake_yuan"] == 128
    assert ref["faces"]["3"] == "3"                    # 0.78 最接近线，帽满时它先留单
    assert all(ref["faces"][str(n)] == "31" for n in range(4, 10))


def test_shengfucai_reference_starts_from_fourteen_singles():
    ref = reference(_legs(BOARD), channel="shengfucai", cap_yuan=256)
    assert len(ref["faces"]) == 14 and ref["notes"] == 128
    assert all(ref["faces"][str(n)] == "30" for n in range(10, 15))   # 最低的五场先补
    assert ref["faces"]["4"] == "31" and ref["faces"]["5"] == "31"     # 再补两场，同比例按场号
    assert ref["faces"]["6"] == "3" and ref["faces"]["1"] == "3"


def test_warnings_read_the_research_fields():
    raw = {"fair": HOT, "research_stance": {"face": "0", "structure": "double", "cover": "1"},
           "anchor_integrity": "fail",
           "_hole": {"side": "home", "priced_in": False},
           "rubric": {"items": {"S_crash_candidate": {"answer": "yes"},
                                "M_market_read": {"answer": "overpriced_fav"}}},
           "license_questions": {"q5_no_rotation_window": False}}
    assert warnings(raw) == ["研究不站热门", "研究开双", "锚方 fail", "锚方洞未价", "崩塌候选",
                             "研究读高估", "轮换窗口"]
    assert warnings({"fair": HOT, "_hole": {"side": "away", "priced_in": False}}) == []


def test_reference_alerts_lines_above_the_line_with_two_warnings():
    raw = {"1": {"fair": HOT, "research_stance": {"face": "3", "structure": "double"},
                 "anchor_integrity": "fail"},
           "2": {"fair": HOT, "anchor_integrity": "fail"}}
    ref = reference(_legs(BOARD, raw), channel="renjiu", cap_yuan=800)
    assert ref["alerts"] == [{"no": "1", "ratio": 0.8202, "flags": ["研究开双", "锚方 fail"]}]
    assert ref["faces"]["1"] == "3"                    # 只提醒，不替人改面


def test_reminder_lines_price_the_white_doubles_and_name_the_alerts():
    faces = {"1": "31", "2": "3", "4": "31"}
    fair = {"1": HOT, "2": HOT, "4": COIN}
    raw = {"2": {"fair": HOT, "anchor_integrity": "fail", "research_stance": {"face": "0"}}}
    lines = reminder_lines(faces, fair, raw, stake_yuan=8)
    assert lines[0].startswith("ℹ️白防线 0.80：场 1 双 31（一赔条件 0.82）")
    assert "改单省 ¥4" in lines[0]
    assert lines[1].startswith("⚠️预警 2 条在线以上：场 2（0.82）研究不站热门、锚方 fail")


def _slip(slip_id: str, issue: str, legs: list[tuple[str, tuple[str, ...], dict]]) -> BetSlip:
    code = {"home": "3", "draw": "1", "away": "0"}
    return BetSlip(slip_id=slip_id, channel="renjiu", placed_at="2026-11-07", issue=issue,
                   legs=[SlipLeg(key=no, selections=sel, fair=f) for no, sel, f in legs],
                   faces={no: "".join(code[s] for s in sel) for no, sel, _ in legs})


def test_month_cost_counts_extra_yuan_and_white_doubles():
    legs = [("1", ("home", "draw"), HOT), ("2", ("home", "draw"), COIN),
            *[(str(n), ("home",), COIN) for n in range(3, 10)]]
    slip = _slip("T1", "26161", legs)                  # 4 注 ¥8，线以上的双 1 条
    out = month_cost([slip], {"26161": "3 1 3 3 3 3 3 3 3 3 3 3 3 3".split()})
    assert out == {"slips": 1, "doubles": 1, "extra_yuan": 4.0, "settled": 1, "white": 1}
    assert month_cost([slip], {})["settled"] == 0
