# tests/decision/test_zucai_ticket.py
import json

import pytest

from nutmeg.decision.zucai_ticket import ledger_add, ledger_summary


def _leg(faces, h, d, a, name=""):
    return {"faces": faces, "name": name,
            "fair": {"home": h / 100, "draw": d / 100, "away": a / 100}}


def test_ledger_add_requires_fields(tmp_path):
    with pytest.raises(ValueError):
        ledger_add(tmp_path, {"issue": "26104"})
    msg = ledger_add(tmp_path, {"issue": "26104", "kind": "任九", "stake_yuan": 216,
                                "tickets": 108, "code": "…", "note": "n"})
    assert "¥216" in msg
    row = json.loads((tmp_path / "zucai-ledger.jsonl").read_text("utf-8").strip())
    assert row["settled_at"] is None and row["prize_yuan"] == 0


def test_ledger_summary_nets(tmp_path):
    ledger_add(tmp_path, {"issue": "A", "kind": "任九", "stake_yuan": 100,
                          "tickets": 50, "code": "c", "note": ""})
    rows = [json.loads(ln) for ln in
            (tmp_path / "zucai-ledger.jsonl").read_text("utf-8").splitlines()]
    rows[0]["prize_yuan"] = 300
    rows[0]["settled_at"] = "t"
    (tmp_path / "zucai-ledger.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    txt = ledger_summary(tmp_path)
    assert "+200" in txt


def test_ledger_summary_excludes_trial_plans_from_net(tmp_path):
    """体验/试玩方案登记但不进净值。

    混进合计会污染 `user_exercise_record`，而那条记分正是刹车条款
    （连续两期全灭→减半）的输入——一张没花钱的票不该影响该不该减注。
    """
    from nutmeg.decision.zucai_ticket import ledger_add, ledger_summary

    ledger_add(tmp_path, {"issue": "26122", "kind": "任九", "stake_yuan": 576,
                          "tickets": 288, "code": "…", "note": "实购"})
    ledger_add(tmp_path, {"issue": "26122", "kind": "任九", "stake_yuan": 162,
                          "tickets": 81, "code": "…", "note": "体验方案",
                          "trial": True})
    out = ledger_summary(tmp_path, issue="26122")
    assert "投入 ¥576" in out
    assert "体验方案 ¥162 不计" in out
    assert "[体验方案·不计净值]" in out
