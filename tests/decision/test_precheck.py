from nutmeg.decision.betslip import load_slips
from nutmeg.decision.precheck import build_slip, precheck, register_reviewed

_FAIR = {str(i): {"home": 0.5, "draw": 0.3, "away": 0.2} for i in range(1, 15)}


def _slip(faces, **kw):
    return build_slip(slip_id=kw.pop("slip_id", "preview"), channel="renjiu",
                      placed_at="2026-10-27", faces=faces, issue="26151", fair=_FAIR, **kw)


def test_precheck_reports_arithmetic_and_v4(tmp_path):
    ten = "3 3 3 3 3 3 3 3 3 3 * * * *"           # 任九 10 场 → V4 否决
    out = precheck(_slip(ten), tmp_path, log=False)
    assert out["notes"] == 10 and out["stake"] == 20   # 任九 >9 场是复式：C(10,9)＝10 注
    assert out["vetoed"] is True
    assert any(v["code"] == "V4" and v["level"] == "veto" for v in out["verdicts"])
    assert out["brake_line"]                       # 月度止损状态行永远在


_NINE = "* 31 * 10 10 * 31 3 3 31 * 10 3 *"     # 3单6双：单 8/9/13，双 2/4/5/7/10/12


def test_precheck_nine_matches_has_p_and_no_v4(tmp_path):
    out = precheck(_slip(_NINE), tmp_path, log=False)
    assert out["notes"] == 64 and out["stake"] == 128
    # 面质量：「3」=0.5，「31」=0.8，「10」=0.5 → 0.5³ × 0.8³ × 0.5³
    assert round(out["p"], 6) == round(0.5 ** 3 * 0.8 ** 3 * 0.5 ** 3, 6)
    assert not any(v["code"] == "V4" for v in out["verdicts"])


def test_register_reviewed_keeps_deviation_and_review_record(tmp_path):
    nine = _NINE
    slip = _slip(nine, slip_id="26151-T1", deviation="fact_self_judged",
                 prediction="门兴 90 分钟赢不了")
    summary = register_reviewed(slip, tmp_path)
    assert "26151-T1" in summary["summary"]
    saved = load_slips(tmp_path, issue="26151")[0]
    assert saved.deviation == "fact_self_judged" and saved.prediction
    assert "review" in saved.diagnosis and "codes" in saved.diagnosis["review"]


def test_precheck_vetoes_a_second_ticket_that_adds_nothing(tmp_path):
    """一期两张上限（2026-11-08）：同面第二张至少中一张增量 0 → 预审否决，登记照收。"""
    register_reviewed(_slip(_NINE, slip_id="26151-T1"), tmp_path)
    out = precheck(_slip(_NINE), tmp_path, log=False)
    assert any(x.startswith("⛔两张上限：第二张") for x in out["discipline"])
    assert out["vetoed"] is True


def test_precheck_vetoes_raising_stakes_right_after_a_win(tmp_path):
    import json

    (tmp_path / "scoreboard.json").write_text(json.dumps({"tickets": {
        "26148": {"stake": 64, "payout": 0}, "26149": {"stake": 64, "payout": 0},
        "26150": {"stake": 64, "payout": 900.0}}}), encoding="utf-8")
    out = precheck(_slip(_NINE), tmp_path, log=False)       # ¥128 > 中奖前均 ¥64
    assert any(x.startswith("⛔中奖后不加码：26150 中奖后第 1 期") for x in out["discipline"])


def test_precheck_reminds_white_doubles_without_vetoing(tmp_path):
    hot = {**_FAIR, "2": {"home": 0.73, "draw": 0.16, "away": 0.11}}
    slip = build_slip(slip_id="preview", channel="renjiu", placed_at="2026-10-27", faces=_NINE,
                      issue="26151", fair=hot)
    out = precheck(slip, tmp_path, log=False)
    assert out["reminders"][0].startswith("ℹ️白防线 0.80：场 2 双 31（一赔条件 0.82）")
    assert not any("白防" in x for x in out["discipline"])
