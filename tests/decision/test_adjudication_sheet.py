# tests/decision/test_adjudication_sheet.py
"""裁决单 —— 行权的文书门。**它不放宽出票门，只规定按下去之前必须写清楚什么。**"""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.decision.adjudication_sheet import (
    AdjudicationSheetError,
    accepted_slots,
    error_signature,
    format_sheet_summary,
    issue_sheet,
    merge_deviation_registry,
    merge_rx_predictions,
    prediction_records,
    rejected_slots,
    validate_sheet,
)
from nutmeg.decision.legs_audit import (
    Finding,
    deviation_registrations,
    ticket_deviation_registrations,
)

ISSUED_AT = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)


def _finding(code="broken_anchor_single", match_no=7, level="ERROR"):
    return Finding(
        level=level,
        code=code,
        match_no=match_no,
        message=f"场{match_no} 锚方 FAIL 却裸单",
        since="8/08",
    )


def _payload():
    return {
        "issue": "26128",
        "version": "S333",
        "legs": {
            "7": {"name": "尤文-奈梅亨"},
            "11": {"name": "曼彻斯特城-诺维奇"},
        },
    }


def _sheet(findings=None, legs_file=Path("t.json")):
    findings = findings or [_finding()]
    return issue_sheet(
        _payload(), findings, legs_file=legs_file, issued_at=ISSUED_AT
    )


def _fill(sheet, **overrides):
    for ruling in sheet["rulings"]:
        ruling.update(
            {
                "ruling": "reject",
                "rule_ids": ["已定价≠免疫"],
                "reason": "FAIL 是洞已定价的标签",
                "predictions": [{"claim": "正路开出", "falsifier": "非正路即推翻"}],
            }
        )
        ruling.update(overrides)
    return sheet


# —— 签发 ——————————————————————————————————————————————

def test_issued_sheet_never_prefills_the_ruling():
    """判断永不入脚本：机器摊开 ERROR，但 ruling/reason/预测三栏一律留空。"""
    sheet = _sheet([_finding(), _finding(code="low_conf_single", match_no=11)])
    assert len(sheet["rulings"]) == 2
    for ruling in sheet["rulings"]:
        assert ruling["ruling"] == ""
        assert ruling["reason"] == ""
        assert ruling["rule_ids"] == []
        assert ruling["predictions"] == []


def test_issued_sheet_carries_match_names_and_audit_codes():
    sheet = _sheet()
    assert sheet["rulings"][0]["audit_code"] == "C5"
    assert sheet["rulings"][0]["match_name"] == "尤文-奈梅亨"
    assert sheet["issue"] == "26128"


def test_warnings_are_not_ruling_slots():
    """WARN 逐条显式裁决入账走别的路；裁决单只摊 ERROR。"""
    sheet = _sheet([_finding(), _finding(code="expensive_exclusion", level="WARN")])
    assert len(sheet["rulings"]) == 1


def test_clean_ticket_has_no_sheet():
    with pytest.raises(AdjudicationSheetError, match="没有 ERROR"):
        issue_sheet(_payload(), [], legs_file=Path("t.json"), issued_at=ISSUED_AT)


# —— 校验 ——————————————————————————————————————————————

def test_blank_ruling_blocks():
    findings = [_finding()]
    with pytest.raises(AdjudicationSheetError, match="还没裁"):
        validate_sheet(_sheet(findings), findings)


def test_reject_without_falsifier_blocks():
    """驳回必须可结账。26098-26103 四次撤保险理由一次比一次讲究且全亏——
    理由的质量不可自证，能自证的只有事后可判真假的断言。"""
    findings = [_finding()]
    sheet = _fill(_sheet(findings), predictions=[{"claim": "会赢"}])
    with pytest.raises(AdjudicationSheetError, match="falsifier"):
        validate_sheet(sheet, findings)


def test_reject_without_predictions_blocks():
    findings = [_finding()]
    sheet = _fill(_sheet(findings), predictions=[])
    with pytest.raises(AdjudicationSheetError, match="可证伪预测"):
        validate_sheet(sheet, findings)


def test_reject_with_unregistered_rule_id_blocks():
    """无名偏离不构成行权理由——否则"第五个更好的理由"照样能撤保险。"""
    findings = [_finding()]
    sheet = _fill(_sheet(findings), rule_ids=["我觉得这次可以"])
    with pytest.raises(AdjudicationSheetError, match="已登记"):
        validate_sheet(sheet, findings)


def test_reject_without_reason_blocks():
    findings = [_finding()]
    sheet = _fill(_sheet(findings), reason="")
    with pytest.raises(AdjudicationSheetError, match="reason"):
        validate_sheet(sheet, findings)


def test_unknown_ruling_value_blocks():
    findings = [_finding()]
    sheet = _fill(_sheet(findings), ruling="maybe")
    with pytest.raises(AdjudicationSheetError, match="accept 或 reject"):
        validate_sheet(sheet, findings)


def test_signature_drift_blocks_stale_sheet():
    """签发后票面被改过 → 旧单作废。否则可以先对干净票签单、再把票改脏。"""
    findings = [_finding()]
    sheet = _fill(_sheet(findings), ruling="accept")
    drifted = [*findings, _finding(code="low_conf_single", match_no=11)]
    with pytest.raises(AdjudicationSheetError, match="签发后票面被改过"):
        validate_sheet(sheet, drifted)


def test_accept_needs_no_reason_or_prediction():
    """接受门不必举证——不举证的那一侧永远是合法的默认。"""
    findings = [_finding()]
    sheet = _fill(
        _sheet(findings), ruling="accept", rule_ids=[], reason="", predictions=[]
    )
    slots = validate_sheet(sheet, findings)
    assert len(accepted_slots(slots)) == 1
    assert rejected_slots(slots) == ()


def test_signature_is_order_independent():
    a = [_finding(), _finding(code="low_conf_single", match_no=11)]
    assert error_signature(a) == error_signature(list(reversed(a)))


# —— 落文书 ————————————————————————————————————————————

def test_rejections_become_user_override_registrations():
    findings = [_finding()]
    slots = validate_sheet(_fill(_sheet(findings)), findings)
    updated = merge_deviation_registry(_payload(), slots)
    registry = deviation_registrations(updated)
    assert registry[7][0].user_override is True
    assert registry[7][0].known_rule_ids == ("已定价≠免疫",)


def test_accepted_errors_write_no_registration():
    """接受门 = 这张票不出，没有可登记的偏离。"""
    findings = [_finding()]
    sheet = _fill(_sheet(findings), ruling="accept")
    slots = validate_sheet(sheet, findings)
    updated = merge_deviation_registry(_payload(), slots)
    assert updated["deviation_registry"] == []


def test_ticket_level_error_registers_under_ticket_scope():
    """C15/C15b/C17 没有 match_no。2026-09-17 前它们在行权通道里根本无法登记，
    于是「知情行权」这条合法出口被一并堵死（26128 S333 的 C17 是首个真实样本）。"""
    findings = [_finding(code="read_ticket_inconsistency", match_no=None)]
    slots = validate_sheet(_fill(_sheet(findings)), findings)
    updated = merge_deviation_registry(_payload(), slots)
    assert deviation_registrations(updated) == {}
    ticket = ticket_deviation_registrations(updated)
    assert len(ticket) == 1
    assert ticket[0].match_no is None
    assert ticket[0].audit_code == "read_ticket_inconsistency"
    assert ticket[0].user_override is True


def test_re_adjudication_supersedes_the_previous_registration():
    findings = [_finding()]
    slots = validate_sheet(_fill(_sheet(findings), reason="第二次裁决"), findings)
    payload = {
        **_payload(),
        "deviation_registry": [
            {
                "match_no": 7,
                "audit_code": "broken_anchor_single",
                "rule_ids": ["conf"],
                "reason": "第一次裁决",
                "user_override": True,
            }
        ],
    }
    updated = merge_deviation_registry(payload, slots)
    assert len(updated["deviation_registry"]) == 1
    assert updated["deviation_registry"][0]["reason"] == "第二次裁决"


def test_unrelated_registrations_survive():
    findings = [_finding()]
    slots = validate_sheet(_fill(_sheet(findings)), findings)
    payload = {
        **_payload(),
        "deviation_registry": [
            {"match_no": 11, "rule_ids": ["k"], "reason": "处方偏离", "audit_code": ""}
        ],
    }
    updated = merge_deviation_registry(payload, slots)
    assert len(updated["deviation_registry"]) == 2


def test_predictions_are_numbered_and_tagged_with_their_ruling():
    findings = [_finding()]
    slots = validate_sheet(_fill(_sheet(findings)), findings)
    records = prediction_records(slots)
    assert records[0]["id"] == "P1"
    assert "C5@7" in records[0]["origin"]
    assert records[0]["falsifier"] == "非正路即推翻"


def test_predictions_merge_into_existing_rx_without_duplicates(tmp_path):
    findings = [_finding()]
    slots = validate_sheet(_fill(_sheet(findings)), findings)
    records = prediction_records(slots)
    rx = tmp_path / "26128-rx.json"
    first = merge_rx_predictions(rx, records, issue="26128", registered_at=ISSUED_AT)
    rx.write_text(__import__("json").dumps(first, ensure_ascii=False), "utf-8")
    second = merge_rx_predictions(rx, records, issue="26128", registered_at=ISSUED_AT)
    assert len(second["predictions"]) == 1


def test_prediction_ids_do_not_collide_with_existing_rx(tmp_path):
    findings = [_finding()]
    slots = validate_sheet(_fill(_sheet(findings)), findings)
    rx = tmp_path / "26128-rx.json"
    rx.write_text(
        __import__("json").dumps(
            {
                "issue": "26128",
                "predictions": [{"id": "P1", "claim": "别的预测", "falsifier": "x"}],
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )
    merged = merge_rx_predictions(
        rx, prediction_records(slots), issue="26128", registered_at=ISSUED_AT
    )
    ids = [item["id"] for item in merged["predictions"]]
    assert len(ids) == len(set(ids)) == 2


def test_summary_names_every_ruling_for_the_human():
    findings = [_finding(), _finding(code="low_conf_single", match_no=11)]
    sheet = _sheet(findings)
    sheet["rulings"][0].update(
        {
            "ruling": "reject",
            "rule_ids": ["已定价≠免疫"],
            "reason": "洞已定价",
            "predictions": [{"claim": "正路开出", "falsifier": "非正路"}],
        }
    )
    sheet["rulings"][1]["ruling"] = "accept"
    summary = format_sheet_summary(validate_sheet(sheet, findings))
    assert "接受 1 / 驳回 1" in summary
    assert "尤文-奈梅亨" in summary
    assert "正路开出" in summary
