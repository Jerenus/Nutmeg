"""规则瘦身（Jun 2026-09-27：只保留有正向实证的规则）。

判断类规则全部按 T13 / 研究表态实测降级：与置换基线分不开的降为 INFO（记录），
唯一方向偏正但样本不足的 C19 为 WARN；没有任何判断类规则拦截出票。
结构算术类（弃模态面、多票共享死点）保留原级别。"""
from nutmeg.decision.legs_audit import Leg, audit_legs, audit_ticket, has_blocking

FAIR = {"home": 0.62, "draw": 0.22, "away": 0.16}


def _leg(**over) -> Leg:
    base = dict(match_no=1, name="A-B", faces="3", fair=FAIR, confidence=4,
                anchor_integrity="pass")
    base.update(over)
    return Leg(**base)


def _levels(legs):
    return {f.code: f.level for f in audit_legs(legs)}


def test_rules_without_positive_evidence_are_records_not_warnings():
    levels = _levels([_leg(confidence=3), _leg(match_no=2, anchor_integrity="fail")])
    assert levels["low_conf_single"] == "INFO"
    assert levels["broken_anchor_single"] == "INFO"
    flagged_double = _leg(faces="30", directional_flags=(("anchor_shield_out", "1"),))
    assert _levels([flagged_double])["flag_face_uncovered"] == "INFO"


def test_structural_arithmetic_keeps_its_level():
    assert _levels([_leg(faces="10")])["modal_face_dropped"] == "WARN"


def test_flagged_naked_single_no_longer_blocks():
    legs = [_leg(directional_flags=(("anchor_shield_out", "1"),))]
    finding = next(f for f in audit_legs(legs) if f.code == "flagged_naked_single")
    assert finding.level == "INFO" and "n=61" in finding.message
    assert not has_blocking(audit_legs(legs))


def test_research_cover_naked_is_an_unproven_warning():
    naked = _leg(research_stance={"face": "3", "structure": "double", "cover": "1",
                                  "confidence": 3})
    finding = next(f for f in audit_legs([naked]) if f.code == "research_cover_naked")
    assert finding.level == "WARN" and "n=33" in finding.message
    researched_single = _leg(research_stance={"face": "3", "structure": "single"})
    assert not any(f.code == "research_cover_naked" for f in audit_legs([researched_single]))
    covered = _leg(faces="31", research_stance={"face": "3", "structure": "double", "cover": "1"})
    assert not any(f.code == "research_cover_naked" for f in audit_legs([covered]))


def test_no_channel_is_blocked_by_judgment_rules_anymore():
    leg = {"name": "A-B", "faces": "3", "fair": FAIR, "confidence": 3, "anchor_integrity": "pass",
           "directional_flags": [["anchor_shield_out", "1"]],
           "research_stance": {"face": "3", "structure": "double", "cover": "1"}}
    for channel in ("shengfucai", "renjiu", "jczq"):
        assert not has_blocking(audit_ticket({"issue": "26133", "channel": channel,
                                              "legs": {"1": leg}}))
