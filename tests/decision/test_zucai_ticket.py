# tests/decision/test_zucai_ticket.py
import json

import pytest

from nutmeg.decision.zucai_ticket import (
    format_stats,
    ledger_add,
    ledger_summary,
    ticket_stats,
)


def _leg(faces, h, d, a, name=""):
    return {"faces": faces, "name": name,
            "fair": {"home": h / 100, "draw": d / 100, "away": a / 100}}


def test_stats_match_26103_hand_computed():
    """26103 用户实票:手工算过 432 注 ¥864 / P 9.03% / 门槛 ¥9,563 —— 必须逐位一致。"""
    legs = {"1": _leg("310", 37.1, 29.5, 33.4), "2": _leg("31", 57.3, 21.3, 21.4),
            "5": _leg("3", 52.4, 25.7, 21.9), "6": _leg("0", 25.0, 30.0, 45.0),
            "7": _leg("31", 66.2, 19.8, 14.0), "9": _leg("310", 68.1, 20.5, 11.4),
            "11": _leg("01", 33.0, 28.0, 39.0), "12": _leg("310", 59.7, 22.7, 17.6),
            "13": _leg("01", 15.4, 19.9, 64.7)}
    s = ticket_stats(legs)
    assert (s["notes"], s["cost"]) == (432, 864)
    assert abs(s["p_all"] - 0.0903) < 0.0005
    assert s["breakeven"] == 9563
    assert s["max_winners_for_breakeven"] == 870


def test_duplicate_faces_do_not_double_count():
    """faces="33" 之类的重复字符不重复计价/计盖率。"""
    s = ticket_stats({"1": _leg("33", 50, 30, 20)})
    assert s["notes"] == 1 and abs(s["p_all"] - 0.50) < 1e-9


def test_empty_ticket_raises():
    with pytest.raises(ValueError):
        ticket_stats({})


def test_format_mentions_negative_correlation_warning():
    s = ticket_stats({"1": _leg("3", 50, 30, 20)})
    assert "负相关" in format_stats(s)


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
