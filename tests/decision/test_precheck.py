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
