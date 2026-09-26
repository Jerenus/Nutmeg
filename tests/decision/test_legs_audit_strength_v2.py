"""strength-v2（2026-09-26 Jun 批准）：立论被闭环证伪的码降为 WARN；只留有死亡记录的硬门。"""
from nutmeg.decision.legs_audit import Leg, audit_legs, has_blocking

FAIR = {"home": 0.62, "draw": 0.22, "away": 0.16}


def _leg(**over) -> Leg:
    base = dict(match_no=1, name="A-B", faces="3", fair=FAIR, confidence=4,
                anchor_integrity="pass")
    base.update(over)
    return Leg(**base)


def _levels(legs):
    return {f.code: f.level for f in audit_legs(legs)}


def test_falsified_rules_are_hints_not_gates():
    levels = _levels([_leg(confidence=3), _leg(match_no=2, anchor_integrity="fail")])
    assert levels["low_conf_single"] == "WARN"
    assert levels["broken_anchor_single"] == "WARN"
    assert _levels([_leg(faces="10")])["modal_face_dropped"] == "WARN"
    flagged_double = _leg(faces="30", directional_flags=(("anchor_shield_out", "1"),))
    assert _levels([flagged_double])["flag_face_uncovered"] == "WARN"


def test_flagged_naked_single_is_still_a_gate():
    legs = [_leg(directional_flags=(("anchor_shield_out", "1"),))]
    assert _levels(legs)["flagged_naked_single"] == "ERROR" and has_blocking(audit_legs(legs))


def test_naked_single_against_research_cover_is_a_gate():
    naked = _leg(research_stance={"face": "3", "structure": "double", "cover": "1",
                                  "confidence": 3})
    findings = audit_legs([naked])
    assert any(f.code == "research_cover_naked" and f.level == "ERROR" for f in findings)
    researched_single = _leg(research_stance={"face": "3", "structure": "single"})
    assert not any(f.code == "research_cover_naked" for f in audit_legs([researched_single]))
    covered = _leg(faces="31", research_stance={"face": "3", "structure": "double", "cover": "1"})
    assert not any(f.code == "research_cover_naked" for f in audit_legs([covered]))
