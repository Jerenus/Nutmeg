# tests/decision/test_zucai_official.py
import json

import pytest

from nutmeg.decision.zucai_official import (
    fetch_official,
    parse_draw,
    settle_ledger,
    ticket_hits,
    write_outcomes,
)

# 26102 官方真实数据(2026-08-10 开奖,已用 API 实测核对)作 fixture
_ITEM = {
    "lotteryDrawNum": "26102",
    "lotteryDrawTime": "2026-08-10",
    "lotteryDrawResult": "3 0 3 3 1 3 1 3 0 0 1 3 1 0",
    "prizeLevelListRj": [{"prizeLevel": "任选9场", "stakeCount": "408", "stakeAmount": "21,018"}],
    "prizeLevelList": [
        {"prizeLevel": "一等奖", "stakeCount": "2", "stakeAmount": "4,567,569"},
        {"prizeLevel": "二等奖", "stakeCount": "61", "stakeAmount": "48,401"},
    ],
    "totalSaleAmountRj": "15,209,134",
}


def test_parse_draw_official_string_is_the_authority():
    d = parse_draw(_ITEM)
    assert d.results["1"] == "3" and d.results["14"] == "0" and len(d.results) == 14
    assert d.renjiu == {"stake_count": 408, "stake_amount": 21018.0}
    assert d.sfc_first["stake_amount"] == 4567569.0
    assert d.sale_amount_rj == 15209134.0


def test_parse_rejects_malformed_result_string():
    """赛果串不是 14 个合法码必须抛错——宁死不猜,静默降级是最贵的坏。"""
    bad = dict(_ITEM, lotteryDrawResult="3 0 3")
    with pytest.raises(ValueError):
        parse_draw(bad)
    bad2 = dict(_ITEM, lotteryDrawResult="3 0 3 3 1 3 1 3 0 0 1 3 1 X")
    with pytest.raises(ValueError):
        parse_draw(bad2)


def test_aet_guard_source_never_touches_goals():
    """D3 守卫:本模块不得引用 API-Football 的 goals 字段(含加时)。

    2026-08-11 博德实测:90' 2-2 / goals 3-2 —— 用 goals 结算会把平局记成主胜。
    官方 lotteryDrawResult 是 90 分钟口径,是唯一权威。
    """
    import inspect

    import nutmeg.decision.zucai_official as mod
    src = inspect.getsource(mod)
    assert "api-sports" not in src.lower()
    assert '"goals"' not in src and "['goals']" not in src


def test_fetch_returns_none_when_not_drawn():
    payload = {"value": {"list": [_ITEM]}}
    assert fetch_official("26103", fetcher=lambda _u: payload) is None
    got = fetch_official("26102", fetcher=lambda _u: payload)
    assert got and got.issue == "26102"


def test_ticket_hits_multi_face():
    results = parse_draw(_ITEM).results
    # 26102 的两版处方对照(复盘已算过:判决表版 11/13)
    faces9 = {"2": "01", "4": "31", "5": "3", "7": "01", "8": "310",
              "9": "01", "10": "30", "13": "31", "14": "310"}
    hit, total = ticket_hits(faces9, results)
    assert (hit, total) == (8, 9)          # 唯一断腿 = 场5(裸单3,实开1)


def test_write_outcomes_matches_reconcile_schema(tmp_path):
    d = parse_draw(_ITEM)
    p = write_outcomes(d, tmp_path)
    doc = json.loads(p.read_text("utf-8"))
    assert doc["results"]["5"] == "1"       # verbs._zucai_outcomes 读 results:{no:code}
    assert "90分钟" in doc["source"]


def test_settle_ledger_is_idempotent(tmp_path):
    d = parse_draw(_ITEM)
    (tmp_path / "26102-rx.json").write_text(json.dumps({
        "final_ticket": {"2": "01", "4": "31", "5": "3", "7": "01", "8": "310",
                         "9": "01", "10": "30", "13": "31", "14": "310"}}), "utf-8")
    ledger = tmp_path / "zucai-ledger.jsonl"
    ledger.write_text(json.dumps({"issue": "26102", "kind": "任九", "stake_yuan": 1152,
                                  "note": "x", "settled_at": None}, ensure_ascii=False) + "\n",
                      "utf-8")
    out1 = settle_ledger("26102", tmp_path, d, settled_at="2026-08-12")
    assert any("8/9" in ln for ln in out1)
    row = json.loads(ledger.read_text("utf-8").strip())
    assert row["hits"] == 8 and row["prize_yuan"] == 0 and row["settled_at"] == "2026-08-12"
    # 第二次:已结不重结
    out2 = settle_ledger("26102", tmp_path, d, settled_at="2026-08-13")
    assert any("无待结行" in ln for ln in out2)
    assert json.loads(ledger.read_text("utf-8").strip())["settled_at"] == "2026-08-12"


def test_settle_ledger_pays_on_full_hit(tmp_path):
    d = parse_draw(_ITEM)
    # 构造一张 9/9 票(全对面)
    win = {str(i): d.results[str(i)] for i in range(1, 10)}
    (tmp_path / "26102-rx.json").write_text(json.dumps({"final_ticket": win}), "utf-8")
    ledger = tmp_path / "zucai-ledger.jsonl"
    ledger.write_text(json.dumps({"issue": "26102", "kind": "任九", "stake_yuan": 18,
                                  "note": "", "settled_at": None}) + "\n", "utf-8")
    settle_ledger("26102", tmp_path, d, settled_at="2026-08-12")
    row = json.loads(ledger.read_text("utf-8").strip())
    assert row["hits"] == 9 and row["prize_yuan"] == 21018.0
